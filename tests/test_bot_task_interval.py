import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.bot.handlers.task.editing import handle_interval_input, set_interval
from backend.bot.handlers.core.callback_dispatch import _handle_set_hour_callback, _handle_set_interval_callback
from backend.bot.state.fsm import FSMState, fsm_storage
from backend.bot.ui.keyboards import INTERVAL_OPTIONS, get_interval_keyboard


class BotTaskIntervalTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        fsm_storage.reset_state(100)

    def test_interval_keyboard_starts_at_one_hour_and_keeps_custom_entry(self):
        keyboard = get_interval_keyboard("task_1")
        labels = [button.text for row in keyboard for button in row]
        data_values = [button.data.decode() for row in keyboard for button in row]

        self.assertEqual(min(INTERVAL_OPTIONS), 60)
        self.assertNotIn("5分钟", labels)
        self.assertNotIn("30分钟", labels)
        self.assertIn("1小时", labels)
        self.assertIn("✏️ 自定义分钟", labels)
        self.assertIn("edit_interval_custom:task_1", data_values)

    async def test_custom_interval_input_accepts_sixty_minutes(self):
        event = SimpleNamespace(respond=AsyncMock())
        fsm_storage.set_state(100, FSMState.WAIT_INTERVAL)
        fsm_storage.update_data(100, task_id="task_1")

        with patch("backend.bot.handlers.task.editing.set_interval", AsyncMock(return_value=True)) as set_interval_mock:
            await handle_interval_input(event, 100, "task_1", "60")

        set_interval_mock.assert_awaited_once_with(event, 100, "task_1", 60)
        event.respond.assert_not_awaited()
        self.assertEqual(fsm_storage.get_state(100), FSMState.NONE)

    async def test_custom_interval_input_accepts_more_than_sixty_minutes(self):
        event = SimpleNamespace(respond=AsyncMock())
        fsm_storage.set_state(100, FSMState.WAIT_INTERVAL)
        fsm_storage.update_data(100, task_id="task_1")

        with patch("backend.bot.handlers.task.editing.set_interval", AsyncMock(return_value=True)) as set_interval_mock:
            await handle_interval_input(event, 100, "task_1", "90")

        set_interval_mock.assert_awaited_once_with(event, 100, "task_1", 90)
        self.assertEqual(fsm_storage.get_state(100), FSMState.NONE)

    async def test_set_interval_rejects_legacy_sub_hour_callback(self):
        event = SimpleNamespace(respond=AsyncMock())

        with patch("backend.bot.handlers.task.editing.get_async_session") as session_factory:
            await set_interval(event, 100, "task_1", 30)

        session_factory.assert_not_called()
        event.respond.assert_awaited_once()

    async def test_custom_interval_input_rejects_above_max_and_keeps_state(self):
        event = SimpleNamespace(respond=AsyncMock())
        fsm_storage.set_state(100, FSMState.WAIT_INTERVAL)
        fsm_storage.update_data(100, task_id="task_1")

        with patch("backend.bot.handlers.task.editing.set_interval", AsyncMock()) as set_interval_mock:
            await handle_interval_input(event, 100, "task_1", "43201")

        set_interval_mock.assert_not_awaited()
        event.respond.assert_awaited_once()
        self.assertEqual(fsm_storage.get_state(100), FSMState.WAIT_INTERVAL)

    async def test_custom_interval_input_keeps_state_when_set_interval_fails(self):
        event = SimpleNamespace(respond=AsyncMock())
        fsm_storage.set_state(100, FSMState.WAIT_INTERVAL)
        fsm_storage.update_data(100, task_id="task_1")

        with patch("backend.bot.handlers.task.editing.set_interval", AsyncMock(return_value=False)):
            await handle_interval_input(event, 100, "task_1", "90")

        self.assertEqual(fsm_storage.get_state(100), FSMState.WAIT_INTERVAL)

    async def test_malformed_interval_callback_returns_parameter_error(self):
        event = SimpleNamespace(answer=AsyncMock())

        with patch("backend.bot.handlers.core.callback_dispatch.set_interval", AsyncMock()) as set_interval_mock:
            await _handle_set_interval_callback(event, 100, ["set_interval", "task_1", "bad"])

        set_interval_mock.assert_not_awaited()
        event.answer.assert_awaited_once_with("参数错误", alert=True)

    async def test_malformed_hour_callback_returns_parameter_error(self):
        event = SimpleNamespace(answer=AsyncMock())

        with patch("backend.bot.handlers.core.callback_dispatch.set_hour", AsyncMock()) as set_hour_mock:
            await _handle_set_hour_callback(event, 100, ["set_hour", "task_1", "True", "bad"])

        set_hour_mock.assert_not_awaited()
        event.answer.assert_awaited_once_with("参数错误", alert=True)


if __name__ == "__main__":
    unittest.main()
