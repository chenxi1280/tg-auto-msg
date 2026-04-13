import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

import backend.bot.handlers.core.main  # noqa: F401
from backend.bot.state.fsm import FSMState, fsm_storage
from backend.database.schema.models import MediaType, ScheduledMessageTask, TaskTriggerMode, TaskTriggerSource
from backend.bot.onboarding.service import BotOnboardingService, _HOME_REPLY_KEYBOARD_SIGNATURES
from backend.bot.handlers.task.management import trigger_task_once_from_bot, try_handle_manual_shortcut_message
from backend.bot.ui.keyboards import build_reply_shortcut_keyboard
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
            "text": "马上开课",
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

    def test_validate_task_payload_requires_manual_shortcut_label(self):
        payload = {
            "repeat_interval_min": 60,
            "media_type": "none",
            "trigger_mode": "manual_shortcut",
            "text": "hello",
        }

        with self.assertRaises(HTTPException) as ctx:
            validate_task_payload(payload, current_task=None)

        self.assertIn("手动任务必须设置按钮名称", str(ctx.exception.detail))

    def test_validate_task_payload_requires_manual_shortcut_content(self):
        payload = {
            "repeat_interval_min": 60,
            "media_type": "none",
            "trigger_mode": "manual_shortcut",
            "shortcut_label": "开课通知",
            "enabled": True,
            "text": "",
            "buttons": None,
        }

        with self.assertRaises(HTTPException) as ctx:
            validate_task_payload(payload, current_task=None)

        self.assertIn("手动任务至少需要填写文本、按钮或上传媒体中的一种内容", str(ctx.exception.detail))

    def test_validate_task_payload_allows_disabled_manual_shortcut_without_content(self):
        payload = {
            "repeat_interval_min": 60,
            "media_type": "none",
            "trigger_mode": "manual_shortcut",
            "shortcut_label": "开课通知",
            "enabled": False,
            "text": "",
            "buttons": None,
        }

        validate_task_payload(payload, current_task=None)

        self.assertEqual(payload["trigger_mode"], TaskTriggerMode.MANUAL_SHORTCUT.value)


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


class TaskTitleDefaultingTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_default_task_title_increments_scheduled_names(self):
        from backend.h5_backend.services.task.service import TaskService

        service = TaskService()
        fake_session = SimpleNamespace()
        fake_result = SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: ["未命名任务", "未命名任务2", "别的任务"])
        )
        fake_session.execute = AsyncMock(return_value=fake_result)

        title = await service._build_default_task_title(
            fake_session,
            user_id=1,
            trigger_mode=TaskTriggerMode.SCHEDULED.value,
        )

        self.assertEqual(title, "未命名任务3")

    async def test_ensure_task_title_uses_shortcut_label_for_manual_task(self):
        from backend.h5_backend.services.task.service import TaskService

        service = TaskService()
        fake_session = SimpleNamespace()
        payload = {
            "trigger_mode": TaskTriggerMode.MANUAL_SHORTCUT.value,
            "title": "   ",
            "shortcut_label": "开课通知",
        }

        await service._ensure_task_title(fake_session, user_id=1, payload=payload)

        self.assertEqual(payload["title"], "开课通知")


class ManualShortcutBotBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        _HOME_REPLY_KEYBOARD_SIGNATURES.clear()

    async def test_sync_home_reply_keyboard_skips_duplicate_signatures(self):
        service = BotOnboardingService()
        sync_message = SimpleNamespace(id=321)

        with patch.object(
            service,
            "get_home_reply_keyboard_labels",
            AsyncMock(return_value=["快捷1", "快捷2"]),
        ), patch(
            "backend.bot.onboarding.service.bot_client.send_message",
            new=AsyncMock(return_value=sync_message),
        ) as send_message:
            with patch(
                "backend.bot.onboarding.service.bot_client.delete_messages",
                new=AsyncMock(),
            ) as delete_messages:
                await service.sync_home_reply_keyboard(100)
                await service.sync_home_reply_keyboard(100)

        send_message.assert_awaited_once()
        delete_messages.assert_awaited_once_with(100, [321])

    async def test_sync_home_reply_keyboard_keeps_main_menu_when_no_shortcuts(self):
        service = BotOnboardingService()
        sync_message = SimpleNamespace(id=123)

        with patch.object(
            service,
            "get_home_reply_keyboard_labels",
            AsyncMock(return_value=[]),
        ), patch(
            "backend.bot.onboarding.service.bot_client.send_message",
            new=AsyncMock(return_value=sync_message),
        ) as send_message:
            with patch(
                "backend.bot.onboarding.service.bot_client.delete_messages",
                new=AsyncMock(),
            ) as delete_messages:
                await service.sync_home_reply_keyboard(100)

        self.assertEqual(send_message.await_args.args[1], "\u2063")
        keyboard = send_message.await_args.kwargs["buttons"]
        self.assertEqual(len(keyboard), 1)
        self.assertEqual([button.button.text for button in keyboard[0]], ["🏠 主菜单"])
        delete_messages.assert_awaited_once_with(100, [123])

    async def test_reply_shortcut_keyboard_shows_only_shortcut_row_when_present(self):
        keyboard = build_reply_shortcut_keyboard(["快捷1", "快捷2", "快捷3"])

        self.assertEqual(len(keyboard), 1)
        self.assertEqual([button.button.text for button in keyboard[0]], ["快捷1", "快捷2", "快捷3"])

    async def test_show_home_syncs_reply_keyboard_on_first_visit(self):
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
        sync_keyboard.assert_awaited_once_with(100)

    async def test_show_home_skips_reply_keyboard_sync_after_signature_cached(self):
        service = BotOnboardingService()
        event = SimpleNamespace()
        _HOME_REPLY_KEYBOARD_SIGNATURES[100] = ("快捷1",)

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

    async def test_handle_manual_task_shortcut_label_create_rejects_duplicate_name(self):
        from backend.bot.handlers.task.management import handle_manual_task_shortcut_label_create

        user_id = 100
        fsm_storage.update_data(user_id, pending_manual_task_create={"account_id": "acc-1"})
        event = SimpleNamespace(respond=AsyncMock())
        fake_session = SimpleNamespace()

        class _Ctx:
            async def __aenter__(self):
                return fake_session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        fake_result = SimpleNamespace(scalar_one_or_none=lambda: "task-existing")

        with patch(
            "backend.bot.handlers.task.management.get_async_session",
            return_value=_Ctx(),
        ), patch(
            "backend.bot.handlers.task.management._resolve_actor_access_context",
            AsyncMock(return_value=SimpleNamespace(system_user_id=1)),
        ), patch.object(
            fake_session,
            "execute",
            AsyncMock(return_value=fake_result),
            create=True,
        ):
            await handle_manual_task_shortcut_label_create(event, user_id, "开课通知")

        event.respond.assert_awaited_once()
        self.assertIn("按钮名称已存在", event.respond.await_args.args[0])
        self.assertEqual(
            fsm_storage.get_data(user_id).get("pending_manual_task_create", {}).get("shortcut_label"),
            None,
        )
        fsm_storage.reset_state(user_id)

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

    async def test_trigger_task_once_from_bot_uses_readable_summary(self):
        event = SimpleNamespace(respond=AsyncMock())
        fake_session = SimpleNamespace()
        task = SimpleNamespace(
            task_id="task-readable",
            enabled=True,
            account_id="acc-1",
        )
        summary = SimpleNamespace(
            to_dict=lambda: {
                "title": "开课通知",
                "status": "success",
                "account_id": "acc-1",
                "account_display": "@teacher",
                "total_targets": 1,
                "success_count": 1,
                "failed_count": 0,
                "success_targets": ["课程频道"],
                "failed_targets": [],
                "message_preview": "今晚八点准时上课",
                "error_summary": None,
            }
        )

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
            AsyncMock(return_value=task),
        ), patch(
            "backend.bot.handlers.task.management.require_account_task_permission",
            AsyncMock(),
        ), patch(
            "backend.bot.handlers.task.management.execute_task_once",
            AsyncMock(return_value=summary),
        ):
            await trigger_task_once_from_bot(event, 100, "task-readable")

        final_text = event.respond.await_args_list[-1].args[0]
        self.assertIn("执行账号：@teacher", final_text)
        self.assertIn("发送目标：课程频道", final_text)
        self.assertIn("发送内容：今晚八点准时上课", final_text)
        self.assertNotIn("执行账号：`acc-1`", final_text)

    async def test_update_task_enabled_rejects_empty_manual_task(self):
        from backend.bot.handlers.task.management import update_task_enabled

        event = SimpleNamespace(answer=AsyncMock())
        fake_session = SimpleNamespace()
        task = ScheduledMessageTask(
            task_id="task-empty-enable",
            user_id=1,
            title="空手动任务",
            repeat_interval_min=60,
            trigger_mode=TaskTriggerMode.MANUAL_SHORTCUT.value,
            shortcut_slot=1,
            shortcut_label="空手动任务",
            enabled=False,
            text=None,
            buttons=None,
            media_type=MediaType.NONE,
            media_file_id=None,
        )

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
            AsyncMock(return_value=task),
        ), patch.object(
            fake_session,
            "commit",
            AsyncMock(),
            create=True,
        ) as commit:
            await update_task_enabled(event, 100, "task-empty-enable", True)

        self.assertFalse(task.enabled)
        commit.assert_not_awaited()
        event.answer.assert_awaited_once()

    async def test_manual_task_media_state_prefers_media_handler_when_caption_present(self):
        from backend.bot.handlers.core.message_dispatch import _MEDIA_STATE_HANDLERS, dispatch_message_by_state

        event = SimpleNamespace(
            message=SimpleNamespace(
                media=object(),
                message="这是图片说明",
            ),
            respond=AsyncMock(),
        )
        media_handler = AsyncMock()

        with patch.dict(
            _MEDIA_STATE_HANDLERS,
            {FSMState.WAIT_MANUAL_TASK_MEDIA: media_handler},
            clear=False,
        ), patch(
            "backend.bot.handlers.core.message_dispatch.handle_manual_task_media_text_input",
            new=AsyncMock(),
        ) as text_handler:
            await dispatch_message_by_state(event, 100, FSMState.WAIT_MANUAL_TASK_MEDIA, "")

        media_handler.assert_awaited_once()
        text_handler.assert_not_awaited()

    async def test_create_new_task_for_account_rejects_invalid_account_before_showing_type_picker(self):
        from backend.bot.handlers.task.management import create_new_task_for_account

        event = SimpleNamespace(answer=AsyncMock(), edit=AsyncMock(), respond=AsyncMock())
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
            "backend.bot.handlers.task.management._resolve_actor_access_context",
            AsyncMock(return_value=SimpleNamespace(system_user_id=1, mode="owner", scoped_account_id=None)),
        ), patch.object(
            fake_session,
            "execute",
            AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)),
            create=True,
        ), patch(
            "backend.bot.onboarding.get_onboarding_service",
        ) as get_service:
            get_service.return_value.ensure_registered_user = AsyncMock(return_value=1)
            await create_new_task_for_account(event, 100, "acc_missing")

        event.answer.assert_awaited()
        event.edit.assert_not_called()

    async def test_handle_manual_task_media_create_stores_telegram_media_ref(self):
        from backend.bot.handlers.task.management import handle_manual_task_media_create

        user_id = 100
        draft = {"account_id": "acc-1", "targets": [{"peer_id": 1, "peer_type": "user", "access_hash": None}]}
        fsm_storage.update_data(user_id, pending_manual_task_create=draft)
        event = SimpleNamespace(
            message=SimpleNamespace(media=object()),
            respond=AsyncMock(),
        )
        FakePhoto = type("FakePhoto", (), {})
        media = FakePhoto()
        media.photo = SimpleNamespace(id=123)

        with patch(
            "backend.bot.handlers.task.management.MessageMediaPhoto",
            FakePhoto,
        ), patch(
            "backend.bot.handlers.task.management.store_task_media_from_bot_message",
            new=AsyncMock(return_value="tgmsg://acc-1/456"),
        ) as store_media, patch(
            "backend.bot.handlers.task.management._finalize_manual_task_create",
            new=AsyncMock(),
        ) as finalize_create:
            await handle_manual_task_media_create(event, user_id, "", media)

        self.assertEqual(
            fsm_storage.get_data(user_id).get("pending_manual_task_create", {}).get("media_file_id"),
            "tgmsg://acc-1/456",
        )
        store_media.assert_awaited_once()
        finalize_create.assert_awaited_once()
        fsm_storage.reset_state(user_id)

    async def test_toggle_trigger_mode_rejects_empty_task_for_manual_mode(self):
        from backend.bot.handlers.task.editing import toggle_trigger_mode

        event = SimpleNamespace(respond=AsyncMock())
        fake_session = SimpleNamespace()
        task = ScheduledMessageTask(
            task_id="task-empty",
            user_id=1,
            title="空任务",
            repeat_interval_min=60,
            trigger_mode=TaskTriggerMode.SCHEDULED.value,
            enabled=False,
            text=None,
            buttons=None,
            media_type=MediaType.NONE,
            media_file_id=None,
        )

        class _Ctx:
            async def __aenter__(self):
                return fake_session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with patch(
            "backend.bot.handlers.task.editing.get_async_session",
            return_value=_Ctx(),
        ), patch(
            "backend.bot.handlers.task.editing._get_user_task",
            AsyncMock(return_value=task),
        ), patch.object(
            fake_session,
            "commit",
            AsyncMock(),
            create=True,
        ) as commit:
            await toggle_trigger_mode(event, 100, "task-empty")

        self.assertEqual(task.trigger_mode, TaskTriggerMode.SCHEDULED.value)
        commit.assert_not_awaited()
        event.respond.assert_awaited()

    async def test_set_shortcut_slot_rejects_empty_task_for_manual_mode(self):
        from backend.bot.handlers.task.editing import set_shortcut_slot

        event = SimpleNamespace(respond=AsyncMock())
        fake_session = SimpleNamespace()
        task = ScheduledMessageTask(
            task_id="task-empty-slot",
            user_id=1,
            title="空任务",
            repeat_interval_min=60,
            trigger_mode=TaskTriggerMode.SCHEDULED.value,
            enabled=False,
            text=None,
            buttons=None,
            media_type=MediaType.NONE,
            media_file_id=None,
        )

        class _Ctx:
            async def __aenter__(self):
                return fake_session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with patch(
            "backend.bot.handlers.task.editing.get_async_session",
            return_value=_Ctx(),
        ), patch(
            "backend.bot.handlers.task.editing._get_user_task",
            AsyncMock(return_value=task),
        ), patch.object(
            fake_session,
            "commit",
            AsyncMock(),
            create=True,
        ) as commit:
            await set_shortcut_slot(event, 100, "task-empty-slot", "1")

        self.assertEqual(task.trigger_mode, TaskTriggerMode.SCHEDULED.value)
        self.assertIsNone(task.shortcut_slot)
        commit.assert_not_awaited()
        event.respond.assert_awaited()

    async def test_set_shortcut_slot_rejects_clearing_manual_task(self):
        from backend.bot.handlers.task.editing import set_shortcut_slot

        event = SimpleNamespace(respond=AsyncMock())
        fake_session = SimpleNamespace()
        task = ScheduledMessageTask(
            task_id="task-manual",
            user_id=1,
            title="手动任务",
            repeat_interval_min=60,
            trigger_mode=TaskTriggerMode.MANUAL_SHORTCUT.value,
            shortcut_slot=1,
            shortcut_label="手动任务",
            enabled=True,
            text="hello",
            media_type=MediaType.NONE,
        )

        class _Ctx:
            async def __aenter__(self):
                return fake_session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with patch(
            "backend.bot.handlers.task.editing.get_async_session",
            return_value=_Ctx(),
        ), patch(
            "backend.bot.handlers.task.editing._get_user_task",
            AsyncMock(return_value=task),
        ), patch.object(
            fake_session,
            "commit",
            AsyncMock(),
            create=True,
        ) as commit:
            await set_shortcut_slot(event, 100, "task-manual", "clear")

        self.assertEqual(task.shortcut_slot, 1)
        commit.assert_not_awaited()
        event.respond.assert_awaited()

    async def test_create_new_manual_task_blocks_when_capacity_full(self):
        from backend.bot.handlers.task.management import create_new_manual_task

        event = SimpleNamespace(answer=AsyncMock(), respond=AsyncMock())

        with patch(
            "backend.bot.handlers.task.management._ensure_manual_task_capacity",
            AsyncMock(return_value=False),
        ) as ensure_capacity, patch(
            "backend.bot.handlers.task.management._start_task_creation",
            AsyncMock(),
        ) as start_creation:
            await create_new_manual_task(event, 100)

        ensure_capacity.assert_awaited_once()
        start_creation.assert_not_awaited()

    async def test_task_service_rejects_duplicate_manual_shortcut_label(self):
        from backend.h5_backend.services.task.service import TaskService

        service = TaskService()
        fake_session = SimpleNamespace()
        fake_session._execute_calls = 0

        class _CountResult:
            def scalar_one(self):
                return 0

        class _DuplicateResult:
            def scalar_one_or_none(self):
                return "task-existing"

        async def _execute(_stmt):
            fake_session._execute_calls += 1
            if fake_session._execute_calls == 1:
                return _CountResult()
            return _DuplicateResult()

        fake_session.execute = AsyncMock(side_effect=_execute)
        payload = {
            "trigger_mode": TaskTriggerMode.MANUAL_SHORTCUT.value,
            "shortcut_label": "开课通知",
            "shortcut_slot": None,
        }

        with self.assertRaises(HTTPException) as ctx:
            await service._validate_shortcut_constraints(fake_session, user_id=1, payload=payload)

        self.assertIn("手动任务按钮名称已存在", str(ctx.exception.detail))

    async def test_task_service_rejects_duplicate_manual_shortcut_label_case_insensitive(self):
        from backend.h5_backend.services.task.service import TaskService

        service = TaskService()
        fake_session = SimpleNamespace()
        fake_session._execute_calls = 0

        class _CountResult:
            def scalar_one(self):
                return 0

        class _DuplicateResult:
            def scalar_one_or_none(self):
                return "task-existing"

        async def _execute(_stmt):
            fake_session._execute_calls += 1
            if fake_session._execute_calls == 1:
                return _CountResult()
            return _DuplicateResult()

        fake_session.execute = AsyncMock(side_effect=_execute)
        payload = {
            "trigger_mode": TaskTriggerMode.MANUAL_SHORTCUT.value,
            "shortcut_label": "  开课通知  ",
            "shortcut_slot": None,
        }

        with self.assertRaises(HTTPException) as ctx:
            await service._validate_shortcut_constraints(fake_session, user_id=1, payload=payload)

        self.assertEqual(payload["shortcut_label"], "开课通知")
        self.assertIn("手动任务按钮名称已存在", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
