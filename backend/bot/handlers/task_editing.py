"""Task editing flows for Telegram bot handlers."""
from __future__ import annotations

from datetime import datetime

from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

from backend.bot.fsm import FSMState, fsm_storage
from backend.bot.keyboards import (
    get_cancel_keyboard,
    get_hour_select_keyboard,
    get_interval_keyboard,
)
from backend.bot.handlers.helpers import (
    format_buttons as _format_buttons,
    parse_buttons,
)
from backend.bot.handlers.task_queries import get_user_task as _get_user_task
from backend.bot.messages import *
from backend.database.models import MediaType
from backend.database.session import get_async_session


async def _show_task_settings(event, user_id: int, task_id: str):
    from backend.bot.handlers.task_management import show_task_settings
    await show_task_settings(event, user_id, task_id)


async def toggle_delete_previous(event, user_id: int, task_id: str):
    """切换删除上一条设置。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            task.delete_previous = not task.delete_previous
            await session.commit()
            await _show_task_settings(event, user_id, task_id)


async def toggle_pin_message(event, user_id: int, task_id: str):
    """切换置顶设置。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            task.pin_message = not task.pin_message
            await session.commit()
            await _show_task_settings(event, user_id, task_id)


async def start_edit_text(event, user_id: int, task_id: str):
    """开始编辑文本。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            return

    fsm_storage.set_state(user_id, FSMState.WAIT_TEXT)
    fsm_storage.update_data(user_id, task_id=task_id)
    text = EDIT_TEXT_PROMPT.format(text=task.text or "（无）")
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(text, buttons=keyboard, parse_mode="markdown")


async def handle_text_input(event, user_id: int, task_id: str, text: str):
    """处理文本输入。"""
    if len(text) > 4096:
        await event.respond(ERROR_TEXT_TOO_LONG)
        return

    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            task.text = text
            await session.commit()

    fsm_storage.reset_state(user_id)
    await event.respond(SUCCESS_TEXT_UPDATED)
    await _show_task_settings(event, user_id, task_id)


async def start_edit_media(event, user_id: int, task_id: str):
    """开始编辑媒体。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            return

    fsm_storage.set_state(user_id, FSMState.WAIT_MEDIA)
    fsm_storage.update_data(user_id, task_id=task_id)
    media_status = task.media_type.value if task.media_type != MediaType.NONE else "无"
    text = EDIT_MEDIA_PROMPT.format(current_media=media_status)
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(text, buttons=keyboard, parse_mode="markdown")


async def handle_media_input(event, user_id: int, task_id: str, media):
    """处理媒体输入。"""
    media_type = MediaType.NONE
    file_id = None

    if isinstance(media, MessageMediaPhoto):
        media_type = MediaType.PHOTO
        file_id = media.photo.id
    elif isinstance(media, MessageMediaDocument):
        for attr in media.document.attributes:
            if hasattr(attr, "video"):
                media_type = MediaType.VIDEO
            elif hasattr(attr, "animated"):
                media_type = MediaType.ANIMATION
        file_id = media.document.id

    if media_type == MediaType.NONE:
        await event.respond(ERROR_INVALID_MEDIA)
        return

    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            task.media_type = media_type
            task.media_file_id = str(file_id)
            await session.commit()

    fsm_storage.reset_state(user_id)
    await event.respond(SUCCESS_MEDIA_UPDATED)
    await _show_task_settings(event, user_id, task_id)


async def start_edit_buttons(event, user_id: int, task_id: str):
    """开始编辑按钮。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            return

    fsm_storage.set_state(user_id, FSMState.WAIT_BUTTONS)
    fsm_storage.update_data(user_id, task_id=task_id)
    current_buttons = _format_buttons(task.buttons) if task.buttons else "无"
    text = EDIT_BUTTONS_PROMPT.format(current_buttons=current_buttons)
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(text, buttons=keyboard, parse_mode="markdown")


async def handle_buttons_input(event, user_id: int, task_id: str, text: str):
    """处理按钮输入。"""
    try:
        buttons = parse_buttons(text)
        async with get_async_session() as session:
            task = await _get_user_task(session, task_id, user_id)
            if task:
                task.buttons = buttons
                await session.commit()

        fsm_storage.reset_state(user_id)
        await event.respond(SUCCESS_BUTTONS_UPDATED)
        await _show_task_settings(event, user_id, task_id)
    except Exception as e:
        await event.respond(f"{ERROR_INVALID_BUTTON_FORMAT}\n错误: {str(e)}")


async def show_interval_selection(event, user_id: int, task_id: str):
    """显示间隔时间选择。"""
    del user_id
    keyboard = get_interval_keyboard(task_id)
    await event.edit(SELECT_INTERVAL, buttons=keyboard, parse_mode="markdown")


async def set_interval(event, user_id: int, task_id: str, interval: int):
    """设置重复间隔。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            task.repeat_interval_min = interval
            if task.enabled:
                now_ts = int(datetime.now().timestamp())
                start_at_ts = int(task.start_at or 0)
                if start_at_ts > 0:
                    task.next_run_at = max(now_ts + interval * 60, start_at_ts)
                else:
                    task.next_run_at = now_ts + interval * 60
            await session.commit()
            await event.answer(SUCCESS_INTERVAL_UPDATED.format(interval=interval))
            await _show_task_settings(event, user_id, task_id)


async def start_edit_hours(event, user_id: int, task_id: str):
    """开始编辑时段。"""
    fsm_storage.set_state(user_id, FSMState.WAIT_DAY_START)
    fsm_storage.update_data(user_id, task_id=task_id)
    keyboard = get_hour_select_keyboard(task_id, for_start=True)
    await event.edit(SELECT_START_HOUR, buttons=keyboard, parse_mode="markdown")


async def set_hour(event, user_id: int, task_id: str, is_start: bool, hour: int):
    """设置小时。"""
    data = fsm_storage.get_data(user_id)

    if is_start:
        fsm_storage.set_state(user_id, FSMState.WAIT_DAY_END)
        fsm_storage.update_data(user_id, day_start_hour=hour)
        keyboard = get_hour_select_keyboard(task_id, for_start=False)
        await event.edit(SELECT_END_HOUR, buttons=keyboard, parse_mode="markdown")
        return

    day_start_hour = data.get("day_start_hour")
    day_end_hour = hour
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            task.day_start_hour = day_start_hour
            task.day_end_hour = day_end_hour
            await session.commit()

    fsm_storage.reset_state(user_id)
    await event.answer(
        SUCCESS_TIME_RANGE_UPDATED.format(start=day_start_hour, end=day_end_hour)
    )
    await _show_task_settings(event, user_id, task_id)


async def start_edit_start_at(event, user_id: int, task_id: str):
    """开始编辑开始时间。"""
    fsm_storage.set_state(user_id, FSMState.WAIT_START_AT)
    fsm_storage.update_data(user_id, task_id=task_id)
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(EDIT_START_AT_PROMPT, buttons=keyboard, parse_mode="markdown")


async def handle_start_at_input(event, user_id: int, task_id: str, text: str):
    """处理开始时间输入。"""
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        timestamp = int(dt.timestamp())

        async with get_async_session() as session:
            task = await _get_user_task(session, task_id, user_id)
            if task:
                if task.end_at and timestamp >= task.end_at:
                    await event.respond(ERROR_END_BEFORE_START)
                    return
                task.start_at = timestamp
                await session.commit()

        fsm_storage.reset_state(user_id)
        await event.respond(SUCCESS_START_AT_UPDATED)
        await _show_task_settings(event, user_id, task_id)
    except ValueError:
        await event.respond(ERROR_INVALID_TIME_FORMAT)


async def start_edit_end_at(event, user_id: int, task_id: str):
    """开始编辑结束时间。"""
    fsm_storage.set_state(user_id, FSMState.WAIT_END_AT)
    fsm_storage.update_data(user_id, task_id=task_id)
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(EDIT_END_AT_PROMPT, buttons=keyboard, parse_mode="markdown")


async def handle_end_at_input(event, user_id: int, task_id: str, text: str):
    """处理结束时间输入。"""
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        timestamp = int(dt.timestamp())

        async with get_async_session() as session:
            task = await _get_user_task(session, task_id, user_id)
            if task:
                if task.start_at and timestamp <= task.start_at:
                    await event.respond(ERROR_END_BEFORE_START)
                    return
                task.end_at = timestamp
                await session.commit()

        fsm_storage.reset_state(user_id)
        await event.respond(SUCCESS_END_AT_UPDATED)
        await _show_task_settings(event, user_id, task_id)
    except ValueError:
        await event.respond(ERROR_INVALID_TIME_FORMAT)
