import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.bot.proxy.health import check_health
from backend.bot.proxy.pool import HealthStatus


def proxy_manager_fixture():
    return SimpleNamespace(
        _health_cache={},
        _health_cache_checked_at={},
        _cache_ttl=60,
        get_proxy=AsyncMock(
            return_value=SimpleNamespace(
                proxy_id=1,
                proxy_type="socks5",
                host="sing-box",
                port=10801,
                username=None,
                password_encrypted=None,
            )
        ),
        update_proxy=AsyncMock(),
    )


class ProxyHealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_mtproto_failure_marks_proxy_unhealthy(self):
        manager = proxy_manager_fixture()

        with patch(
            "backend.bot.proxy.health.probe_telegram_proxy",
            AsyncMock(side_effect=asyncio.IncompleteReadError(b"", 8)),
        ):
            result = await check_health(
                manager,
                proxy_id=1,
                timeout=10,
                status_factory=HealthStatus,
                api_id=1,
                api_hash="hash",
            )

        self.assertFalse(result.is_healthy)
        self.assertIn("IncompleteReadError", result.error)
        manager.update_proxy.assert_awaited_once()

    async def test_expired_healthy_cache_reprobes_mtproto(self):
        manager = proxy_manager_fixture()

        with patch(
            "backend.bot.proxy.health.probe_telegram_proxy",
            AsyncMock(return_value=12),
        ) as probe:
            await check_health(
                manager,
                proxy_id=1,
                timeout=10,
                status_factory=HealthStatus,
                api_id=1,
                api_hash="hash",
            )
            manager._health_cache_checked_at[1] = 0
            with patch("backend.bot.proxy.health.time.monotonic", return_value=61):
                await check_health(
                    manager,
                    proxy_id=1,
                    timeout=10,
                    status_factory=HealthStatus,
                    api_id=1,
                    api_hash="hash",
                )

        self.assertEqual(probe.await_count, 2)
