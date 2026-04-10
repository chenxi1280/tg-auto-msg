import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.bot.notice_manager import BotNoticeManager


class BotNoticeManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_notice_without_target_url_is_still_ready(self):
        manager = BotNoticeManager()

        with patch(
            "backend.bot.notice_manager.get_me_service",
            return_value=SimpleNamespace(
                get_public_notice_entry=AsyncMock(
                    return_value={
                        "enabled": True,
                        "entry_button_text": "公告栏",
                        "message_text": "test",
                        "target_url": "",
                        "updated_at": None,
                    }
                )
            ),
        ):
            result = await manager.get_notice_entry()

        self.assertTrue(result["is_ready"])
        self.assertEqual(result["target_url"], "")

    async def test_ensure_notice_attempts_pin_after_send(self):
        manager = BotNoticeManager()

        with (
            patch.object(
                manager,
                "get_notice_entry",
                AsyncMock(
                    return_value={
                        "enabled": True,
                        "entry_button_text": "公告栏",
                        "message_text": "test",
                        "target_url": "https://example.com",
                        "notice_version": "v1",
                        "is_ready": True,
                    }
                ),
            ),
            patch.object(manager, "_load_notice_state", AsyncMock(return_value=None)),
            patch.object(manager, "_send_notice_message", AsyncMock(return_value=SimpleNamespace(id=1001))),
            patch.object(manager, "_pin_notice_message", AsyncMock(return_value=True)) as pin_mock,
            patch.object(manager, "_save_notice_state", AsyncMock()),
        ):
            result = await manager.ensure_notice_for_user(123456)

        self.assertEqual(result["status"], "sent")
        self.assertTrue(result["pin_attempted"])
        self.assertTrue(result["pin_succeeded"])
        pin_mock.assert_awaited_once_with(123456, 1001)


if __name__ == "__main__":
    unittest.main()
