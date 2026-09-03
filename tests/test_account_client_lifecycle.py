import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.bot.account.client_runtime import get_client


class _FailingConnectClient:
    instances = []

    def __init__(self, *_args, **_kwargs):
        self.disconnect_called = False
        self.__class__.instances.append(self)

    async def connect(self):
        raise RuntimeError("connect failed")

    async def disconnect(self):
        self.disconnect_called = True


class _CancelledConnectClient(_FailingConnectClient):
    async def connect(self):
        raise asyncio.CancelledError


class AccountClientLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_client_enforces_proxy_policy_before_returning_cached_client(self):
        cached_client = SimpleNamespace(is_connected=lambda: True)
        manager = SimpleNamespace(_clients={"acc-1": cached_client})
        ensure_proxy = AsyncMock(return_value=None)

        with patch(
            "backend.bot.account.client_runtime.ensure_account_proxy",
            ensure_proxy,
        ):
            result = await get_client(manager, "acc-1")

        self.assertIs(result, cached_client)
        ensure_proxy.assert_awaited_once_with(manager, "acc-1")

    async def test_connect_failure_disconnects_temporary_client(self):
        account = SimpleNamespace(
            account_id="acc-1",
            developer_app_id=1,
            proxy_id=None,
            string_session_encrypted="encrypted-session",
            reauth_required=False,
            reauth_reason=None,
        )
        manager = SimpleNamespace(
            _clients={},
            _locks={},
            get_account=AsyncMock(return_value=account),
            get_client_lock=AsyncMock(return_value=asyncio.Lock()),
            update_account=AsyncMock(),
            update_health_status=AsyncMock(),
        )
        developer_service = SimpleNamespace(
            resolve_credentials_for_account=AsyncMock(
                return_value=SimpleNamespace(api_id=123456, api_hash="hash", credentials_version=1)
            )
        )
        self.__class__._reset_clients()

        with (
            patch("backend.bot.account.client_runtime.decrypt_string_session", return_value="session"),
            patch("backend.bot.account.client_runtime.get_developer_app_service", return_value=developer_service),
            patch("backend.bot.account.client_runtime.StringSession", lambda value: value),
            patch("backend.bot.account.client_runtime.TelegramClient", _FailingConnectClient),
        ):
            with self.assertRaisesRegex(RuntimeError, "connect failed"):
                await get_client(manager, "acc-1")

        client = _FailingConnectClient.instances[-1]
        self.assertTrue(client.disconnect_called)
        self.assertNotIn("acc-1", manager._clients)

    async def test_connect_cancellation_disconnects_temporary_client(self):
        account = SimpleNamespace(
            developer_app_id=1,
            proxy_id=None,
            string_session_encrypted="encrypted-session",
            reauth_required=False,
            reauth_reason=None,
        )
        manager = SimpleNamespace(
            _clients={},
            get_account=AsyncMock(return_value=account),
            get_client_lock=AsyncMock(return_value=asyncio.Lock()),
            update_account=AsyncMock(),
            update_health_status=AsyncMock(),
        )
        developer_service = SimpleNamespace(
            resolve_credentials_for_account=AsyncMock(
                return_value=SimpleNamespace(api_id=123456, api_hash="hash", credentials_version=1)
            )
        )
        _CancelledConnectClient.instances = []

        with (
            patch("backend.bot.account.client_runtime.decrypt_string_session", return_value="session"),
            patch("backend.bot.account.client_runtime.get_developer_app_service", return_value=developer_service),
            patch("backend.bot.account.client_runtime.StringSession", lambda value: value),
            patch("backend.bot.account.client_runtime.TelegramClient", _CancelledConnectClient),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await get_client(manager, "acc-1")

        self.assertTrue(_CancelledConnectClient.instances[-1].disconnect_called)
        self.assertNotIn("acc-1", manager._clients)

    @staticmethod
    def _reset_clients():
        _FailingConnectClient.instances = []


if __name__ == "__main__":
    unittest.main()
