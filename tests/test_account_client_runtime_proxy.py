import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.bot.account.client_runtime import ensure_account_proxy


class AccountClientRuntimeProxyTests(unittest.IsolatedAsyncioTestCase):
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

