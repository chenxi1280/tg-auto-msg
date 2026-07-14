import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from backend.bot.circuit.notify import resolve_notification_recipient, send_notification


def _session_ctx(session):
    @asynccontextmanager
    async def context():
        yield session

    return context


class CircuitNotifyTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_notification_recipient_uses_linked_telegram_user(self):
        with (
            patch(
                "backend.bot.circuit.notify.get_async_session",
                _session_ctx(object()),
            ),
            patch(
                "backend.bot.handlers.core.user_link.load_latest_linked_tg_user_ids",
                AsyncMock(return_value={191: 8865756381}),
            ),
        ):
            recipient = await resolve_notification_recipient(191)

        self.assertEqual(recipient, 8865756381)

    async def test_send_notification_uses_linked_telegram_user(self):
        with (
            patch(
                "backend.bot.circuit.notify.resolve_notification_recipient",
                AsyncMock(return_value=8865756381),
            ),
            patch(
                "backend.bot.client_runtime.manager.ensure_manager_bot_ready",
                AsyncMock(return_value=True),
            ),
            patch(
                "backend.bot.client_runtime.manager.bot_client.send_message",
                AsyncMock(),
            ) as send_message,
        ):
            await send_notification(191, "限流已解除")

        send_message.assert_awaited_once_with(8865756381, "限流已解除", parse_mode="html")


if __name__ == "__main__":
    unittest.main()
