import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

import backend.bot.handlers.core.main  # noqa: F401
from backend.database.schema.models import ScheduledMessageTask, TaskTriggerMode, TaskTriggerSource
from backend.bot.onboarding.service import BotOnboardingService, _HOME_REPLY_KEYBOARD_SIGNATURES
from backend.bot.handlers.task.management import trigger_task_once_from_bot, try_handle_manual_shortcut_message
from backend.h5_backend.services.task.payload import ensure_initial_next_run, validate_task_payload
from backend.h5_backend.services.task.serializers import serialize_task_logs


class ManualShortcutPayloadTests(unittest.TestCase):
    def test_validate_task_payload_accepts_manual_shortcut_slot(self):
        payload = {
            "repeat_interval_min": 60,
            "media_type": "none",
            "trigger_mode": "manual_shortcut",
            "shortcut_slot": 2,
            "shortcut_label": "开课通知",
        }

        validate_task_payload(payload, current_task=None)

        self.assertEqual(payload["trigger_mode"], TaskTriggerMode.MANUAL_SHORTCUT.value)
        self.assertEqual(payload["shortcut_slot"], 2)
        self.assertEqual(payload["shortcut_label"], "开课通知")

    def test_validate_task_payload_rejects_shortcut_slot_for_scheduled_task(self):
        payload = {
            "repeat_interval_min": 60,
            "media_type": "none",
            "trigger_mode": "scheduled",
            "shortcut_slot": 1,
        }

        with self.assertRaises(HTTPException) as ctx:
            validate_task_payload(payload, current_task=None)

        self.assertIn("仅手动快捷任务可加入快捷栏", str(ctx.exception.detail))

    def test_ensure_initial_next_run_skips_manual_shortcut(self):
        payload = {
            "enabled": True,
            "trigger_mode": "manual_shortcut",
            "repeat_interval_min": 60,
        }

        ensure_initial_next_run(payload, now_ts=1000, current_task=None)

        self.assertIsNone(payload["next_run_at"])


class ManualShortcutSerializerTests(unittest.TestCase):
    def test_serialize_task_logs_includes_trigger_source(self):
        log = type(
            "LogRow",
            (),
            {
                "id": 1,
                "send_at": None,
                "result": "success",
                "trigger_source": TaskTriggerSource.BOT_SHORTCUT.value,
                "error_code": None,
                "error_message": None,
                "message_id": 9,
            },
        )()

        serialized = serialize_task_logs([log])

        self.assertEqual(serialized[0]["trigger_source"], TaskTriggerSource.BOT_SHORTCUT.value)

    def test_manual_shortcut_task_can_clear_next_run_on_existing_task(self):
        task = ScheduledMessageTask(
            task_id="task-1",
            user_id=1,
            title="测试任务",
            repeat_interval_min=60,
            trigger_mode=TaskTriggerMode.MANUAL_SHORTCUT.value,
            enabled=True,
            next_run_at=12345,
        )

        ensure_initial_next_run(
            {"trigger_mode": TaskTriggerMode.MANUAL_SHORTCUT.value},
            now_ts=2000,
            current_task=task,
            was_enabled=True,
        )

        self.assertIsNone(task.next_run_at)


class ManualShortcutBotBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        _HOME_REPLY_KEYBOARD_SIGNATURES.clear()

    async def test_sync_home_reply_keyboard_skips_duplicate_signatures(self):
        service = BotOnboardingService()

        with patch.object(
            service,
            "get_home_reply_keyboard_labels",
            AsyncMock(return_value=["快捷1", "快捷2"]),
        ), patch(
            "backend.bot.onboarding.service.bot_client.send_message",
            new=AsyncMock(),
        ) as send_message:
            await service.sync_home_reply_keyboard(100)
            await service.sync_home_reply_keyboard(100)

        send_message.assert_awaited_once()

    async def test_sync_home_reply_keyboard_clears_keyboard_when_no_shortcuts(self):
        service = BotOnboardingService()

        with patch.object(
            service,
            "get_home_reply_keyboard_labels",
            AsyncMock(return_value=[]),
        ), patch(
            "backend.bot.onboarding.service.bot_client.send_message",
            new=AsyncMock(),
        ) as send_message:
            await service.sync_home_reply_keyboard(100)

        self.assertEqual(send_message.await_args.args[1], "\u2063")
        self.assertEqual(type(send_message.await_args.kwargs["buttons"]).__name__, "ReplyKeyboardHide")

    async def test_show_home_does_not_force_reply_keyboard_sync(self):
        service = BotOnboardingService()
        event = SimpleNamespace()

        with patch.object(
            service,
            "build_home_view",
            AsyncMock(return_value=("home", [[SimpleNamespace(text="x")]])),
        ), patch(
            "backend.bot.onboarding.service._send_or_edit",
            new=AsyncMock(),
        ) as send_or_edit, patch.object(
            service,
            "sync_home_reply_keyboard",
            AsyncMock(),
        ) as sync_keyboard:
            await service.show_home(event, 100)

        send_or_edit.assert_awaited_once()
        sync_keyboard.assert_not_awaited()

    async def test_try_handle_manual_shortcut_message_catches_http_exception(self):
        event = SimpleNamespace(respond=AsyncMock())
        task = SimpleNamespace(task_id="task-1", shortcut_label="快捷1", title="快捷1")
        fake_session = SimpleNamespace()

        class _FakeResult:
            def scalars(self):
                return self

            def all(self):
                return [task]

        class _Ctx:
            async def __aenter__(self):
                return fake_session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with patch(
            "backend.bot.handlers.task.management.get_async_session",
            return_value=_Ctx(),
        ), patch(
            "backend.bot.handlers.task.management._resolve_actor_access_context",
            AsyncMock(return_value=SimpleNamespace(system_user_id=1, mode="owner", scoped_account_id=None)),
        ), patch.object(
            fake_session,
            "execute",
            AsyncMock(return_value=_FakeResult()),
            create=True,
        ), patch(
            "backend.bot.handlers.task.management.trigger_task_once_from_bot",
            new=AsyncMock(side_effect=HTTPException(status_code=400, detail="无授权")),
        ):
            handled = await try_handle_manual_shortcut_message(event, 100, "快捷1")

        self.assertTrue(handled)
        event.respond.assert_awaited()

    async def test_trigger_task_once_from_bot_uses_respond_for_message_events(self):
        event = SimpleNamespace(respond=AsyncMock())
        fake_session = SimpleNamespace()

        class _Ctx:
            async def __aenter__(self):
                return fake_session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with patch(
            "backend.bot.handlers.task.management.get_async_session",
            return_value=_Ctx(),
        ), patch(
            "backend.bot.handlers.task.management._get_user_task",
            AsyncMock(return_value=None),
        ):
            await trigger_task_once_from_bot(event, 100, "missing-task")

        event.respond.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
