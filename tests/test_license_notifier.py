import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from backend.bot.license_notifier import LicenseReminderItem, LicenseSlotNotifier


class LicenseSlotNotifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_scan_once_skips_when_manager_bot_not_ready(self):
        notifier = LicenseSlotNotifier()
        reminder_items = [
            LicenseReminderItem(
                authorization_id="auth-1",
                user_id=9,
                tg_user_id=987654321,
                days_before=3,
                end_at=datetime(2026, 4, 15, 12, 0, 0),
                account_id="acc-1",
            )
        ]

        with (
            patch.object(notifier, "_collect_due_reminders", AsyncMock(return_value=reminder_items)),
            patch("backend.bot.license_notifier.ensure_manager_bot_ready", AsyncMock(return_value=False)),
            patch("backend.bot.license_notifier.bot_client.send_message", AsyncMock()) as send_mock,
        ):
            sent = await notifier.scan_once()

        self.assertEqual(sent, 0)
        send_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
