import unittest
from unittest.mock import AsyncMock, patch

from backend.bot.developer_apps.service import (
    DeveloperAppHealthCheckResult,
    DeveloperAppService,
)


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


if __name__ == "__main__":
    unittest.main()
