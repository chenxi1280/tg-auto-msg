"""FSM message-state dispatch for bot handlers."""
from __future__ import annotations

from backend.bot.state.fsm import FSMState
from backend.bot.handlers.task.target_selection import handle_target_search_input
from backend.bot.handlers.task.editing import (
    handle_buttons_input,
    handle_end_at_input,
    handle_media_input,
    handle_start_at_input,
    handle_text_input,
)
from backend.bot.onboarding import get_onboarding_service

_SENSITIVE_INPUT_STATES = {
    FSMState.WAIT_REGISTER_PASSWORD,
    FSMState.WAIT_LOGIN_CODE,
    FSMState.WAIT_LOGIN_PASSWORD,
}

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
    onboarding_service = get_onboarding_service()
    if state in _SENSITIVE_INPUT_STATES:
        await onboarding_service.delete_sensitive_input_message(event, state)

    if state == FSMState.WAIT_REGISTER_USERNAME:
        await onboarding_service.handle_register_username(event, user_id, event.message.message or "")
        return
    if state == FSMState.WAIT_REGISTER_PASSWORD:
        await onboarding_service.handle_register_password(event, user_id, event.message.message or "")
        return
    if state == FSMState.WAIT_REGISTER_EMAIL:
        await onboarding_service.handle_register_email(event, user_id, event.message.message or "")
        return
    if state == FSMState.WAIT_ACTIVATION_CODE:
        await onboarding_service.handle_activation_code(event, user_id, event.message.message or "")
        return
    if state == FSMState.WAIT_LOGIN_PHONE:
        await onboarding_service.handle_login_phone(event, user_id, event.message.message or "")
        return
    if state == FSMState.WAIT_LOGIN_CODE:
        await onboarding_service.handle_login_code(event, user_id, event.message.message or "")
        return
    if state == FSMState.WAIT_LOGIN_PASSWORD:
        await onboarding_service.handle_login_password(event, user_id, event.message.message or "")
        return

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
