from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.bot.handlers.core.message_dispatch import _TEXT_STATE_HANDLERS
from backend.bot.handlers.task.creation import (
    PENDING_TASK_CREATE_KEY,
    begin_task_text_creation,
    handle_task_creation_text_input,
)
from backend.bot.handlers.task.selector_context import (
    clear_selector_context,
    get_selector_context,
    set_selector_context,
)
from backend.bot.handlers.task.target_selection import _handle_pick_done
from backend.bot.state.fsm import FSMState, fsm_storage
from backend.database.schema.models import TaskTriggerMode


class _SessionContext:
    async def __aenter__(self):
        return SimpleNamespace()

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@pytest.fixture(autouse=True)
def _reset_bot_state():
    user_id = 919191
    fsm_storage.reset_state(user_id)
    clear_selector_context(user_id)
    yield user_id
    fsm_storage.reset_state(user_id)
    clear_selector_context(user_id)


@pytest.mark.asyncio
async def test_target_selection_opens_text_step_before_creating(_reset_bot_state):
    user_id = _reset_bot_state
    target = {"peer_id": 123, "peer_type": "supergroup", "access_hash": 456}
    set_selector_context(
        user_id,
        task_id="__draft_new_task__",
        account_id="account-1",
        draft_mode=True,
        draft_targets=[target],
        draft_trigger_mode=TaskTriggerMode.SCHEDULED.value,
    )
    event = SimpleNamespace(answer=AsyncMock(), respond=AsyncMock())

    with patch(
        "backend.bot.handlers.task.target_selection.get_async_session",
        return_value=_SessionContext(),
    ), patch(
        "backend.bot.handlers.task.creation.begin_task_text_creation",
        AsyncMock(),
    ) as begin:
        await _handle_pick_done(event, user_id)

    begin.assert_awaited_once_with(
        event,
        user_id,
        account_id="account-1",
        targets=[target],
        trigger_mode=TaskTriggerMode.SCHEDULED.value,
    )
    assert get_selector_context(user_id) is None


@pytest.mark.asyncio
async def test_begin_creation_stores_draft_and_requests_text(_reset_bot_state):
    user_id = _reset_bot_state
    event = SimpleNamespace(answer=AsyncMock(), respond=AsyncMock())
    targets = [{"peer_id": 123, "peer_type": "user", "access_hash": None}]

    with patch(
        "backend.bot.handlers.task.creation._resolve_creation_owner",
        AsyncMock(return_value=7),
    ):
        await begin_task_text_creation(
            event,
            user_id,
            account_id="account-1",
            targets=targets,
            trigger_mode=TaskTriggerMode.SCHEDULED.value,
        )

    pending = fsm_storage.get_data(user_id)[PENDING_TASK_CREATE_KEY]
    assert fsm_storage.get_state(user_id) == FSMState.WAIT_TASK_CREATE_TEXT
    assert pending["targets"] == targets
    assert pending["targets"] is not targets
    assert "请输入任务要发送的文本内容" in event.respond.await_args.args[0]


@pytest.mark.asyncio
async def test_text_step_creates_task_with_entered_text(_reset_bot_state):
    user_id = _reset_bot_state
    event = SimpleNamespace(respond=AsyncMock())
    service = SimpleNamespace(create_task=AsyncMock(return_value="task-created"))
    pending = {
        "account_id": "account-1",
        "targets": [{"peer_id": 123, "peer_type": "user", "access_hash": None}],
        "trigger_mode": TaskTriggerMode.SCHEDULED.value,
        "shortcut_label": None,
    }
    fsm_storage.set_state(user_id, FSMState.WAIT_TASK_CREATE_TEXT)
    fsm_storage.update_data(user_id, **{PENDING_TASK_CREATE_KEY: pending})

    with patch(
        "backend.bot.handlers.task.creation._resolve_creation_owner",
        AsyncMock(return_value=7),
    ), patch(
        "backend.bot.handlers.task.creation.get_task_service",
        return_value=service,
    ), patch(
        "backend.bot.handlers.task.management.show_task_settings",
        AsyncMock(),
    ) as show_settings:
        await handle_task_creation_text_input(
            event,
            user_id,
            None,
            "<b>通知内容</b>",
        )

    payload = service.create_task.await_args.args[0]
    assert payload["text"] == "<b>通知内容</b>"
    assert payload["target_peers"] == pending["targets"]
    assert fsm_storage.get_state(user_id) == FSMState.NONE
    show_settings.assert_awaited_once_with(event, user_id, "task-created")


@pytest.mark.asyncio
async def test_empty_text_does_not_create_task(_reset_bot_state):
    user_id = _reset_bot_state
    event = SimpleNamespace(respond=AsyncMock())
    fsm_storage.set_state(user_id, FSMState.WAIT_TASK_CREATE_TEXT)

    with patch(
        "backend.bot.handlers.task.creation.get_task_service",
    ) as service_factory:
        await handle_task_creation_text_input(event, user_id, None, "   ")

    service_factory.assert_not_called()
    assert fsm_storage.get_state(user_id) == FSMState.WAIT_TASK_CREATE_TEXT
    assert "不能为空" in event.respond.await_args.args[0]


def test_creation_text_state_is_dispatched_to_creation_handler():
    assert (
        _TEXT_STATE_HANDLERS[FSMState.WAIT_TASK_CREATE_TEXT]
        is handle_task_creation_text_input
    )
