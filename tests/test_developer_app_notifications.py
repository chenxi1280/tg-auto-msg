import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.bot.developer_apps.service import (
    DeveloperAppHealthCheckResult,
    DeveloperAppService,
)
from backend.bot.account.client_runtime import get_client


class DeveloperAppNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_notify_admins_skips_when_manager_bot_not_ready(self):
        service = DeveloperAppService()
        result = DeveloperAppHealthCheckResult(
            app_id=1,
            app_name="Test App",
            previous_status="healthy",
            probe_status="unhealthy",
            current_status="unhealthy",
            checked_at=None,
            latency_ms=None,
            error="boom",
            migrated_account_ids=[],
            stalled_account_ids=[],
            notified_recipients=[],
            probe_ok=False,
            status_changed=True,
            migration_executed=False,
            probe_failed_without_downgrade=False,
        )

        with (
            patch.object(service, "get_alert_recipient_ids", AsyncMock(return_value=[123456])),
            patch("backend.bot.client_runtime.manager.ensure_manager_bot_ready", AsyncMock(return_value=False)),
            patch("backend.bot.client_runtime.manager.bot_client.send_message", AsyncMock()) as send_mock,
        ):
            sent = await service._notify_admins_for_health_change(result)

        self.assertEqual(sent, [])
        send_mock.assert_not_awaited()


class DeveloperAppCredentialRotationTests(unittest.IsolatedAsyncioTestCase):
    async def test_account_with_rotated_api_hash_reason_is_not_blocked_before_connect(self):
        account = SimpleNamespace(
            account_id="acc-1",
            developer_app_id=1,
            developer_app_version=1,
            proxy_id=None,
            string_session_encrypted="encrypted-session",
            reauth_required=True,
            reauth_reason="api_hash_rotated",
        )
        manager = SimpleNamespace(
            _clients={},
            _locks={},
            get_account=AsyncMock(return_value=account),
            get_client_lock=AsyncMock(),
            update_health_status=AsyncMock(),
            update_account=AsyncMock(),
        )

        class _Lock:
            async def __aenter__(self):
                return None

            async def __aexit__(self, exc_type, exc, tb):
                return False

        manager.get_client_lock.return_value = _Lock()

        class _Client:
            def __init__(self, *_args, **_kwargs):
                self.connected = False

            def is_connected(self):
                return self.connected

            async def connect(self):
                self.connected = True

            async def is_user_authorized(self):
                return True

        credentials = SimpleNamespace(api_id=123456, api_hash="new-hash", credentials_version=2)
        developer_service = SimpleNamespace(
            resolve_credentials_for_account=AsyncMock(return_value=credentials)
        )

        with (
            patch("backend.bot.account.client_runtime.decrypt_string_session", return_value="session"),
            patch("backend.bot.account.client_runtime.get_developer_app_service", return_value=developer_service),
            patch("backend.bot.account.client_runtime.StringSession", lambda value: value),
            patch("backend.bot.account.client_runtime.TelegramClient", _Client),
            patch("backend.bot.account.client_runtime.mark_account_reauth_required", AsyncMock()) as mark_mock,
        ):
            client = await get_client(manager, "acc-1")

        self.assertIsNotNone(client)
        mark_mock.assert_not_awaited()
        self.assertGreaterEqual(manager.update_account.await_count, 1)
        update_kwargs = manager.update_account.await_args.kwargs
        self.assertFalse(update_kwargs["reauth_required"])
        self.assertIsNone(update_kwargs["reauth_reason"])
        self.assertEqual(update_kwargs["developer_app_version"], 2)

    async def test_account_without_developer_app_uses_environment_credentials_version(self):
        account = SimpleNamespace(
            account_id="acc-env",
            developer_app_id=None,
            developer_app_version=1,
            proxy_id=None,
            string_session_encrypted="encrypted-session",
            reauth_required=False,
            reauth_reason=None,
        )
        manager = SimpleNamespace(
            _clients={},
            _locks={},
            get_account=AsyncMock(return_value=account),
            get_client_lock=AsyncMock(),
            update_health_status=AsyncMock(),
            update_account=AsyncMock(),
        )

        class _Lock:
            async def __aenter__(self):
                return None

            async def __aexit__(self, exc_type, exc, tb):
                return False

        manager.get_client_lock.return_value = _Lock()

        class _Client:
            def __init__(self, *_args, **kwargs):
                self.api_id = kwargs["api_id"]
                self.api_hash = kwargs["api_hash"]
                self.connected = False

            def is_connected(self):
                return self.connected

            async def connect(self):
                self.connected = True

            async def is_user_authorized(self):
                return True

        developer_service = SimpleNamespace(
            resolve_credentials_for_account=AsyncMock(side_effect=RuntimeError("no developer app"))
        )

        with (
            patch("backend.bot.account.client_runtime.decrypt_string_session", return_value="session"),
            patch("backend.bot.account.client_runtime.get_developer_app_service", return_value=developer_service),
            patch("backend.bot.account.client_runtime.settings", SimpleNamespace(api_id=123456, api_hash="env-hash")),
            patch("backend.bot.account.client_runtime.StringSession", lambda value: value),
            patch("backend.bot.account.client_runtime.TelegramClient", _Client),
            patch("backend.bot.account.client_runtime.mark_account_reauth_required", AsyncMock()) as mark_mock,
        ):
            client = await get_client(manager, "acc-env")

        self.assertIsNotNone(client)
        self.assertEqual(client.api_id, 123456)
        self.assertEqual(client.api_hash, "env-hash")
        mark_mock.assert_not_awaited()
        update_kwargs = manager.update_account.await_args.kwargs
        self.assertEqual(update_kwargs["developer_app_version"], 1)
        self.assertEqual(update_kwargs["health_status"].value, "online")


if __name__ == "__main__":
    unittest.main()
