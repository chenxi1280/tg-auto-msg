import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from backend.bot.session.redis_login_manager import LoginStatus, RedisLoginManager
from backend.h5_backend.services.login.service import LoginService


class _FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.ttls = {}
        self.strings = {}

    async def hset(self, key, field=None, value=None, mapping=None):
        bucket = self.hashes.setdefault(key, {})
        if mapping is not None:
            bucket.update({k: str(v) for k, v in mapping.items()})
        else:
            bucket[str(field)] = str(value)

    async def expire(self, key, ttl):
        self.ttls[key] = int(ttl)

    async def exists(self, key):
        return key in self.hashes or key in self.strings

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.strings:
            return False
        self.strings[key] = str(value)
        self.ttls[key] = int(ex or 0)
        return True

    async def ttl(self, key):
        return self.ttls.get(key, -1)


class RedisLoginManagerPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_status_refreshes_active_session_ttl(self):
        fake_redis = _FakeRedis()
        login_id = "login_test_123"
        key = RedisLoginManager.SESSION_KEY_PREFIX + login_id
        fake_redis.hashes[key] = {
            "login_id": login_id,
            "status": LoginStatus.PENDING.value,
            "expires_at": "2000-01-01T00:00:00",
        }

        manager = RedisLoginManager(redis_url="redis://example")
        with patch.object(manager, "_get_redis", AsyncMock(return_value=fake_redis)):
            updated = await manager.update_status(login_id, LoginStatus.CODE_INPUT_REQUIRED)

        self.assertTrue(updated)
        self.assertEqual(fake_redis.hashes[key]["status"], LoginStatus.CODE_INPUT_REQUIRED.value)
        self.assertIn("expires_at", fake_redis.hashes[key])
        self.assertEqual(fake_redis.ttls[key], manager.SESSION_TTL)

    async def test_acquire_bind_start_cooldown_returns_retry_after_when_locked(self):
        fake_redis = _FakeRedis()
        manager = RedisLoginManager(redis_url="redis://example")
        user_id = 42

        with patch.object(manager, "_get_redis", AsyncMock(return_value=fake_redis)):
            first = await manager.acquire_bind_start_cooldown(user_id, ttl_seconds=120)
            second = await manager.acquire_bind_start_cooldown(user_id, ttl_seconds=120)

        self.assertEqual(first, 0)
        self.assertEqual(second, 120)


class LoginServicePolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_phone_login_session_rejects_recent_bind_attempt(self):
        service = LoginService()
        me_service = SimpleNamespace(ensure_can_add_tg_account=AsyncMock())
        login_manager = SimpleNamespace(acquire_bind_start_cooldown=AsyncMock(return_value=45))

        with patch(
            "backend.h5_backend.services.login.service.get_me_service",
            return_value=me_service,
        ), patch(
            "backend.h5_backend.services.login.service.get_redis_login_manager",
            return_value=login_manager,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await service.create_phone_login_session(9)

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("2 分钟内只能发起 1 次 TG 账号绑定", str(ctx.exception.detail))
        self.assertIn("45 秒后重试", str(ctx.exception.detail))

    async def test_create_phone_login_session_includes_extended_expiry(self):
        service = LoginService()
        me_service = SimpleNamespace(ensure_can_add_tg_account=AsyncMock())
        developer_service = SimpleNamespace(
            choose_login_credentials_for_user=AsyncMock(return_value=SimpleNamespace(app_id=3))
        )
        login_manager = MagicMock()
        login_manager.acquire_bind_start_cooldown = AsyncMock(return_value=0)
        login_manager.create_session = AsyncMock(
            return_value=SimpleNamespace(expires_at="2026-04-08T13:40:00")
        )
        login_manager.update_status = AsyncMock()

        with patch(
            "backend.h5_backend.services.login.service.get_me_service",
            return_value=me_service,
        ), patch(
            "backend.h5_backend.services.login.service.get_developer_app_service",
            return_value=developer_service,
        ), patch(
            "backend.h5_backend.services.login.service.get_redis_login_manager",
            return_value=login_manager,
        ), patch.object(
            service,
            "generate_login_id",
            return_value="login_fixed",
        ):
            data = await service.create_phone_login_session(9)

        self.assertEqual(data["login_id"], "login_fixed")
        self.assertEqual(data["expires_in_seconds"], service.LOGIN_SESSION_TTL_SECONDS)
        self.assertEqual(data["status"], LoginStatus.PHONE_INPUT_REQUIRED.value)

