import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.database.schema.models import DeveloperAppHealthStatus, HealthStatus
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


class DeveloperAppRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovered_app_probes_stalled_accounts_before_marking_recovered(self):
        service = DeveloperAppService()

        class _Rows:
            def scalars(self):
                return self

            def all(self):
                return ["acc-ok", "acc-still-offline"]

        class _Session:
            async def execute(self, _statement):
                return _Rows()

        @asynccontextmanager
        async def fake_session_ctx():
            yield _Session()

        manager = SimpleNamespace(
            health_check=AsyncMock(
                side_effect=[HealthStatus.ONLINE, HealthStatus.OFFLINE]
            )
        )

        with (
            patch("backend.bot.developer_apps.service.get_async_session", fake_session_ctx),
            patch("backend.bot.account.manager.get_account_manager", return_value=manager),
        ):
            recovered, unrecovered = await service._recover_stalled_accounts_from_recovered_app(3)

        self.assertEqual(recovered, ["acc-ok"])
        self.assertEqual(unrecovered, ["acc-still-offline"])
        manager.health_check.assert_any_await("acc-ok")
        manager.health_check.assert_any_await("acc-still-offline")

    async def test_health_recovery_returns_account_recovery_results(self):
        service = DeveloperAppService()
        row = SimpleNamespace(
            id=3,
            app_name="app",
            api_id=123,
            api_hash_encrypted="encrypted",
            is_active=True,
            max_accounts=0,
            selection_weight=100,
            health_status=DeveloperAppHealthStatus.UNHEALTHY.value,
            last_health_check_at=None,
            last_health_error="boom",
            last_health_latency_ms=None,
            health_fail_count=2,
            credentials_version=1,
            last_rotated_at=None,
            notes=None,
        )

        class _Session:
            def __init__(self):
                self.added = []
                self.commits = 0

            async def get(self, _model, _id):
                return row

            def add(self, item):
                self.added.append(item)

            async def commit(self):
                self.commits += 1

        session = _Session()

        @asynccontextmanager
        async def fake_session_ctx():
            yield session

        with (
            patch("backend.bot.developer_apps.service.get_async_session", fake_session_ctx),
            patch.object(
                service,
                "_probe_app",
                AsyncMock(return_value=(DeveloperAppHealthStatus.HEALTHY.value, None, 50)),
            ),
            patch.object(
                service,
                "_recover_stalled_accounts_from_recovered_app",
                AsyncMock(return_value=(["acc-ok"], ["acc-still-offline"])),
            ) as recover_mock,
        ):
            result = await service.check_app_health(3, notify_admins=False)

        recover_mock.assert_awaited_once_with(3)
        self.assertEqual(result["current_status"], DeveloperAppHealthStatus.HEALTHY.value)
        self.assertEqual(result["recovered_account_ids"], ["acc-ok"])
        self.assertEqual(result["unrecovered_account_ids"], ["acc-still-offline"])


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
