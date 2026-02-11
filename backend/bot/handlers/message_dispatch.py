"""FSM message-state dispatch for bot handlers."""
from __future__ import annotations

from backend.bot.fsm import FSMState
from backend.bot.handlers.task_target_selection import handle_target_search_input
from backend.bot.handlers.task_editing import (
    handle_buttons_input,
    handle_end_at_input,
    handle_media_input,
    handle_start_at_input,
    handle_text_input,
)

_TEXT_STATE_HANDLERS = {
    FSMState.WAIT_TEXT: handle_text_input,
    FSMState.WAIT_BUTTONS: handle_buttons_input,
    FSMState.WAIT_START_AT: handle_start_at_input,
    FSMState.WAIT_END_AT: handle_end_at_input,
}

_MEDIA_STATE_HANDLERS = {
    FSMState.WAIT_MEDIA: handle_media_input,
}


async def dispatch_message_by_state(event, user_id: int, state: FSMState, task_id: str):
    """Dispatch input message by FSM state."""
    text_handler = _TEXT_STATE_HANDLERS.get(state)
    if text_handler:
        await text_handler(event, user_id, task_id, event.message.message)
        return

    media_handler = _MEDIA_STATE_HANDLERS.get(state)
    if media_handler:
        await media_handler(event, user_id, task_id, event.message.media)
        return

    if state == FSMState.WAIT_TARGET_SEARCH:
        await handle_target_search_input(event, user_id, event.message.message or "")
