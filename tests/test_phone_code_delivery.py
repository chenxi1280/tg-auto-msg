import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from backend.bot.session.login_cooldown_store import (
    PHONE_CODE_SEND_KEY_PREFIX,
    LoginCooldownStore,
)
from backend.bot.session.redis_login_manager import LoginStatus
from backend.h5_backend.services.login.phone_code_delivery import (
    DELIVERY_METHOD_SMS,
    DELIVERY_METHOD_TELEGRAM_APP,
    PhoneCodeDelivery,
    describe_sent_code,
)
from backend.h5_backend.services.login.phone_code_sender import (
    PhoneCodeResendCooldownError,
    request_phone_code,
)
from backend.h5_backend.services.login.service import LoginService


INFLIGHT_LEASE_TTL_SECONDS = 900


def _sent_code(
    type_name: str,
    *,
    next_type_name: str | None = None,
    timeout: int | None = None,
    length: int | None = 5,
) -> SimpleNamespace:
    attributes = {"length": length} if length is not None else {}
    code_type = type(type_name, (), attributes)()
    next_type = type(next_type_name, (), {})() if next_type_name else None
    return SimpleNamespace(
        type=code_type,
        next_type=next_type,
        timeout=timeout,
        phone_code_hash="runtime-only-hash",
        email_pattern="private@example.test",
        url="https://example.test/private",
        nonce="private-nonce",
    )


class _MemoryRedis:
    def __init__(self):
        self.strings: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.strings:
            return False
        self.strings[key] = str(value)
        self.ttls[key] = int(ex or 0)
        return True

    async def ttl(self, key):
        return self.ttls.get(key, -2)

    async def eval(self, script, key_count, key, token, *args):
        del key_count
        if self.strings.get(key) != token:
            return 0
        if "EXPIRE" in script:
            self.ttls[key] = int(args[0])
            return 1
        self.strings.pop(key, None)
        self.ttls.pop(key, None)
        return 1

    def expire_key(self, key: str) -> None:
        self.strings.pop(key, None)
        self.ttls.pop(key, None)


class _StatefulLeaseStore:
    def __init__(self, *, retry_after_seconds: int = 0):
        self.active = retry_after_seconds > 0
        self.retry_after_seconds = retry_after_seconds
        self.acquire_ttl_seconds: int | None = None
        self.refresh_ttl_seconds: int | None = None
        self._token = ""

    async def acquire_phone_code_send(self, _login_id, token, *, ttl_seconds):
        self.acquire_ttl_seconds = ttl_seconds
        if self.active:
            return self.retry_after_seconds or ttl_seconds
        self.active = True
        self._token = token
        return 0

    async def refresh_phone_code_send(self, _login_id, token, *, ttl_seconds):
        if token != self._token:
            return False
        self.refresh_ttl_seconds = ttl_seconds
        self.retry_after_seconds = ttl_seconds
        return True

    async def release_phone_code_send(self, _login_id, token):
        if token != self._token:
            return False
        self.active = False
        self.retry_after_seconds = 0
        return True


class _RecordingClient:
    def __init__(self, *, sent_code=None, error: Exception | None = None):
        self.connect = AsyncMock()
        self.disconnect = AsyncMock()
        self.send_code_request = AsyncMock(return_value=sent_code)
        if error is not None:
            self.send_code_request.side_effect = error


class PhoneCodeDeliveryTests(unittest.TestCase):
    def test_sent_code_maps_only_safe_delivery_metadata(self):
        sent_code = _sent_code(
            "SentCodeTypeApp",
            next_type_name="SentCodeTypeSms",
            timeout=37,
            length=6,
        )

        delivery = describe_sent_code(sent_code, fallback_resend_cooldown_seconds=60)

        self.assertEqual(delivery.delivery_method, DELIVERY_METHOD_TELEGRAM_APP)
        self.assertEqual(delivery.next_delivery_method, DELIVERY_METHOD_SMS)
        self.assertEqual(delivery.code_length, 6)
        self.assertEqual(delivery.resend_after_seconds, 37)
        self.assertEqual(
            set(delivery.to_response_fields()),
            {
                "delivery_method",
                "next_delivery_method",
                "code_length",
                "resend_after_seconds",
            },
        )

    def test_sent_code_uses_fallback_when_telegram_omits_timeout(self):
        delivery = describe_sent_code(
            _sent_code("SentCodeTypeSms", timeout=None),
            fallback_resend_cooldown_seconds=60,
        )

        self.assertEqual(delivery.delivery_method, DELIVERY_METHOD_SMS)
        self.assertEqual(delivery.resend_after_seconds, 60)

    def test_sent_code_maps_each_supported_delivery_channel(self):
        cases = (
            ("SentCodeTypeCall", "phone_call"),
            ("SentCodeTypeEmailCode", "email"),
            ("SentCodeTypeUnrecognized", "unknown"),
        )

        for type_name, expected_method in cases:
            with self.subTest(type_name=type_name):
                delivery = describe_sent_code(
                    _sent_code(type_name, timeout=10),
                    fallback_resend_cooldown_seconds=60,
                )
                self.assertEqual(delivery.delivery_method, expected_method)


class LoginCooldownStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_phone_code_lease_rejects_until_expired_and_honors_owner(self):
        redis_client = _MemoryRedis()
        store = LoginCooldownStore(AsyncMock(return_value=redis_client))
        login_id = "login_cooldown"
        key = PHONE_CODE_SEND_KEY_PREFIX + login_id

        self.assertEqual(await store.acquire_phone_code_send(login_id, "owner-1", ttl_seconds=60), 0)
        self.assertTrue(await store.refresh_phone_code_send(login_id, "owner-1", ttl_seconds=42))
        self.assertEqual(await store.acquire_phone_code_send(login_id, "owner-2", ttl_seconds=60), 42)
        self.assertFalse(await store.release_phone_code_send(login_id, "owner-2"))
        self.assertEqual(await store.phone_code_send_retry_after(login_id), 42)

        redis_client.expire_key(key)

        self.assertEqual(await store.acquire_phone_code_send(login_id, "owner-2", ttl_seconds=60), 0)


class PhoneCodeRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_send_persists_telegram_delivery_wait(self):
        lease_store = _StatefulLeaseStore()
        login_manager = SimpleNamespace(update_status=AsyncMock())
        client = _RecordingClient(
            sent_code=_sent_code("SentCodeTypeApp", next_type_name="SentCodeTypeSms", timeout=28)
        )

        delivery = await request_phone_code(
            login_manager=login_manager,
            phone_code_lease_store=lease_store,
            login_id="login_first_send",
            phone_number="+15550001111",
            client=client,
            save_pending_session=lambda: "encrypted-session",
            code_input_status=LoginStatus.CODE_INPUT_REQUIRED,
            fallback_resend_cooldown_seconds=60,
            inflight_lease_ttl_seconds=INFLIGHT_LEASE_TTL_SECONDS,
            log=MagicMock(),
        )

        self.assertEqual(delivery.resend_after_seconds, 28)
        client.send_code_request.assert_awaited_once()
        persisted = login_manager.update_status.await_args.kwargs
        self.assertEqual(persisted["delivery_method"], DELIVERY_METHOD_TELEGRAM_APP)
        self.assertEqual(persisted["next_delivery_method"], DELIVERY_METHOD_SMS)
        self.assertEqual(persisted["code_length"], 5)
        self.assertEqual(lease_store.acquire_ttl_seconds, INFLIGHT_LEASE_TTL_SECONDS)
        self.assertEqual(lease_store.refresh_ttl_seconds, 28)
        self.assertEqual(lease_store.retry_after_seconds, 28)

    async def test_cooldown_does_not_contact_telegram(self):
        lease_store = _StatefulLeaseStore(retry_after_seconds=19)
        client = _RecordingClient(sent_code=_sent_code("SentCodeTypeSms"))

        with self.assertRaises(PhoneCodeResendCooldownError) as ctx:
            await request_phone_code(
                login_manager=SimpleNamespace(update_status=AsyncMock()),
                phone_code_lease_store=lease_store,
                login_id="login_blocked",
                phone_number="+15550001111",
                client=client,
                save_pending_session=lambda: "encrypted-session",
                code_input_status=LoginStatus.CODE_INPUT_REQUIRED,
                fallback_resend_cooldown_seconds=60,
                inflight_lease_ttl_seconds=INFLIGHT_LEASE_TTL_SECONDS,
                log=MagicMock(),
            )

        self.assertEqual(ctx.exception.retry_after_seconds, 19)
        client.connect.assert_not_awaited()
        client.send_code_request.assert_not_awaited()

    async def test_failed_send_releases_lease_for_immediate_retry(self):
        lease_store = _StatefulLeaseStore()
        manager = SimpleNamespace(update_status=AsyncMock())
        failed_client = _RecordingClient(error=RuntimeError("transport failed"))

        with self.assertRaises(RuntimeError):
            await request_phone_code(
                login_manager=manager,
                phone_code_lease_store=lease_store,
                login_id="login_retry",
                phone_number="+15550001111",
                client=failed_client,
                save_pending_session=lambda: "encrypted-session",
                code_input_status=LoginStatus.CODE_INPUT_REQUIRED,
                fallback_resend_cooldown_seconds=60,
                inflight_lease_ttl_seconds=INFLIGHT_LEASE_TTL_SECONDS,
                log=MagicMock(),
            )

        self.assertFalse(lease_store.active)
        retry_client = _RecordingClient(sent_code=_sent_code("SentCodeTypeSms", timeout=12))
        await request_phone_code(
            login_manager=manager,
            phone_code_lease_store=lease_store,
            login_id="login_retry",
            phone_number="+15550001111",
            client=retry_client,
            save_pending_session=lambda: "encrypted-session",
            code_input_status=LoginStatus.CODE_INPUT_REQUIRED,
            fallback_resend_cooldown_seconds=60,
            inflight_lease_ttl_seconds=INFLIGHT_LEASE_TTL_SECONDS,
            log=MagicMock(),
        )
        retry_client.send_code_request.assert_awaited_once()


class PhoneCodeEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_code_response_includes_safe_delivery_fields(self):
        service = LoginService()
        session = SimpleNamespace(
            login_mode="phone_code",
            status=LoginStatus.PHONE_INPUT_REQUIRED,
            developer_app_id=3,
            target_account_id="",
        )
        manager = SimpleNamespace(cooldowns=object(), update_status=AsyncMock())
        delivery = PhoneCodeDelivery(DELIVERY_METHOD_SMS, None, 5, 60)

        request_phone_code_mock = AsyncMock(return_value=delivery)
        with patch.object(service, "_load_session_for_user", AsyncMock(return_value=session)), patch.object(
            service,
            "_resolve_login_credentials",
            AsyncMock(return_value=SimpleNamespace(api_id=1, api_hash="app-hash")),
        ), patch.object(service, "_resolve_login_proxy_config", AsyncMock(return_value=None)), patch(
            "backend.h5_backend.services.login.service.get_redis_login_manager",
            return_value=manager,
        ), patch("backend.h5_backend.services.login.service.TelegramClient"), patch(
            "backend.h5_backend.services.login.service.request_phone_code",
            new=request_phone_code_mock,
        ):
            response = await service.submit_phone_number_data(
                login_id="login_response",
                user_id=9,
                phone_number="+15550001111",
            )

        self.assertEqual(response["delivery_method"], DELIVERY_METHOD_SMS)
        self.assertEqual(response["code_length"], 5)
        self.assertEqual(response["resend_after_seconds"], 60)
        self.assertNotIn("phone_code_hash", response)
        self.assertEqual(
            request_phone_code_mock.await_args.kwargs["inflight_lease_ttl_seconds"],
            service.LOGIN_SESSION_TTL_SECONDS,
        )

    async def test_send_code_cooldown_becomes_429_with_retry_after(self):
        service = LoginService()
        session = SimpleNamespace(
            login_mode="phone_code",
            status=LoginStatus.CODE_INPUT_REQUIRED,
            developer_app_id=3,
            target_account_id="",
        )
        manager = SimpleNamespace(cooldowns=object(), update_status=AsyncMock())

        with patch.object(service, "_load_session_for_user", AsyncMock(return_value=session)), patch.object(
            service,
            "_resolve_login_credentials",
            AsyncMock(return_value=SimpleNamespace(api_id=1, api_hash="app-hash")),
        ), patch.object(service, "_resolve_login_proxy_config", AsyncMock(return_value=None)), patch(
            "backend.h5_backend.services.login.service.get_redis_login_manager",
            return_value=manager,
        ), patch("backend.h5_backend.services.login.service.TelegramClient"), patch(
            "backend.h5_backend.services.login.service.request_phone_code",
            new=AsyncMock(side_effect=PhoneCodeResendCooldownError(23)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await service.submit_phone_number_data(
                    login_id="login_response",
                    user_id=9,
                    phone_number="+15550001111",
                )

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.headers, {"Retry-After": "23"})

    async def test_status_reports_safe_delivery_fields_and_current_wait(self):
        service = LoginService()
        session = SimpleNamespace(
            system_user_id=9,
            status=LoginStatus.CODE_INPUT_REQUIRED,
            error="",
            qr_url="",
            phone_number="+15550001111",
            delivery_method=DELIVERY_METHOD_TELEGRAM_APP,
            next_delivery_method=DELIVERY_METHOD_SMS,
            code_length="6",
        )
        manager = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            cooldowns=SimpleNamespace(phone_code_send_retry_after=AsyncMock(return_value=18)),
        )

        with patch(
            "backend.h5_backend.services.login.service.get_redis_login_manager",
            return_value=manager,
        ):
            response = await service.get_login_status("login_status", user_id=9)

        data = response["data"]
        self.assertEqual(data["delivery_method"], DELIVERY_METHOD_TELEGRAM_APP)
        self.assertEqual(data["next_delivery_method"], DELIVERY_METHOD_SMS)
        self.assertEqual(data["code_length"], 6)
        self.assertEqual(data["resend_after_seconds"], 18)
        self.assertNotIn("phone_code_hash", data)
