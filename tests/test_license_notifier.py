import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telethon.errors import UserIsBlockedError

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

    async def test_scan_once_warns_when_user_blocked(self):
        notifier = LicenseSlotNotifier()
        reminder_items = [
            LicenseReminderItem(
                authorization_id="auth-1",
                user_id=11,
                tg_user_id=8071215277,
                days_before=7,
                end_at=datetime(2026, 4, 28, 16, 45, 0),
                account_id="acc-1",
                account_name="@demo",
            )
        ]
        me_service = SimpleNamespace(get_purchase_entry=AsyncMock(return_value={}))

        with (
            patch.object(notifier, "_collect_due_reminders", AsyncMock(return_value=reminder_items)),
            patch("backend.bot.license_notifier.ensure_manager_bot_ready", AsyncMock(return_value=True)),
            patch("backend.bot.license_notifier.get_me_service", return_value=me_service),
            patch("backend.bot.license_notifier.bot_client.send_message", AsyncMock(side_effect=UserIsBlockedError(request=None))),
            patch.object(notifier, "_record_notice", AsyncMock()) as record_mock,
            patch("backend.bot.license_notifier.logger.warning") as warning_mock,
            patch("backend.bot.license_notifier.logger.error") as error_mock,
        ):
            sent = await notifier.scan_once()

        self.assertEqual(sent, 0)
        record_mock.assert_not_awaited()
        warning_mock.assert_called_once()
        error_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
