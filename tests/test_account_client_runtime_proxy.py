import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.bot.account.client_runtime import ensure_account_proxy


class AccountClientRuntimeProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_account_without_proxy_stays_direct(self):
        manager = SimpleNamespace(
            _clients={},
            _locks={},
            get_account=AsyncMock(return_value=SimpleNamespace(proxy_id=None)),
            update_account=AsyncMock(),
        )
        proxy_pool = SimpleNamespace(
            get_available_proxy=AsyncMock(
                return_value=SimpleNamespace(proxy_id=1)
            ),
        )

        with patch("backend.bot.proxy.pool.get_proxy_pool", return_value=proxy_pool):
            result = await ensure_account_proxy(manager, "account-1")

        self.assertIsNone(result)
        proxy_pool.get_available_proxy.assert_not_awaited()
        manager.update_account.assert_not_awaited()

    async def test_inactive_system_gateway_proxy_is_unassigned(self):
        manager = SimpleNamespace(
            _clients={},
            _locks={},
            get_account=AsyncMock(return_value=SimpleNamespace(proxy_id=1)),
            update_account=AsyncMock(),
        )
        proxy_pool = SimpleNamespace(
            get_proxy=AsyncMock(
                return_value=SimpleNamespace(
                    proxy_id=1,
                    is_system_gateway=True,
                    is_active=False,
                    is_healthy=False,
                )
            ),
            check_health=AsyncMock(),
            unassign_proxy=AsyncMock(),
            get_available_proxy=AsyncMock(return_value=None),
        )

        with patch("backend.bot.proxy.pool.get_proxy_pool", return_value=proxy_pool):
            result = await ensure_account_proxy(manager, "account-1")

        self.assertIsNone(result)
        proxy_pool.check_health.assert_not_awaited()
        proxy_pool.unassign_proxy.assert_awaited_once_with("account-1")
        manager.update_account.assert_awaited_once_with("account-1", proxy_id=None)

    async def test_unhealthy_regular_proxy_is_unassigned_without_replacement(self):
        manager = SimpleNamespace(
            _clients={},
            _locks={},
            get_account=AsyncMock(return_value=SimpleNamespace(proxy_id=2)),
            update_account=AsyncMock(),
        )
        proxy_pool = SimpleNamespace(
            get_proxy=AsyncMock(
                return_value=SimpleNamespace(
                    proxy_id=2,
                    is_system_gateway=False,
                )
            ),
            check_health=AsyncMock(
                return_value=SimpleNamespace(is_healthy=False, error="mtproto failed")
            ),
            unassign_proxy=AsyncMock(),
            get_available_proxy=AsyncMock(
                return_value=SimpleNamespace(proxy_id=1)
            ),
        )

        with patch("backend.bot.proxy.pool.get_proxy_pool", return_value=proxy_pool):
            result = await ensure_account_proxy(manager, "account-1")

        self.assertIsNone(result)
        proxy_pool.unassign_proxy.assert_awaited_once_with("account-1")
        proxy_pool.get_available_proxy.assert_not_awaited()
        manager.update_account.assert_awaited_once_with("account-1", proxy_id=None)

    async def test_healthy_flagged_system_gateway_is_unbound_when_mtproto_check_fails(self):
        cached_client = AsyncMock()
        manager = SimpleNamespace(
            _clients={"account-1": cached_client},
            _locks={},
            get_account=AsyncMock(return_value=SimpleNamespace(proxy_id=1)),
            update_account=AsyncMock(),
        )
        proxy_pool = SimpleNamespace(
            get_proxy=AsyncMock(
                return_value=SimpleNamespace(
                    proxy_id=1,
                    is_system_gateway=True,
                    is_active=True,
                    is_healthy=True,
                )
            ),
            check_health=AsyncMock(
                return_value=SimpleNamespace(
                    is_healthy=False,
                    error="IncompleteReadError",
                )
            ),
            unassign_proxy=AsyncMock(),
        )

        with patch("backend.bot.proxy.pool.get_proxy_pool", return_value=proxy_pool):
            result = await ensure_account_proxy(manager, "account-1")

        self.assertIsNone(result)
        proxy_pool.check_health.assert_awaited_once_with(1)
        proxy_pool.unassign_proxy.assert_awaited_once_with("account-1")
        manager.update_account.assert_awaited_once_with("account-1", proxy_id=None)
        cached_client.disconnect.assert_awaited_once()
