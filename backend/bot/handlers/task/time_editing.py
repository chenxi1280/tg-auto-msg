"""Time-window editing flows for Telegram task handlers."""

from __future__ import annotations

from datetime import datetime, timedelta

from telethon import events

from backend.bot.handlers.task.queries import get_user_task
from backend.bot.state.fsm import FSMState, fsm_storage
from backend.bot.ui.keyboards import (
    get_cancel_keyboard,
    get_end_time_keyboard,
    get_hour_select_keyboard,
    get_start_time_keyboard,
)
from backend.bot.ui.messages import (
    EDIT_END_AT_PROMPT,
    EDIT_START_AT_PROMPT,
    ERROR_END_BEFORE_START,
    ERROR_INVALID_TIME_FORMAT,
    SELECT_END_HOUR,
    SELECT_START_HOUR,
    SUCCESS_END_AT_UPDATED,
    SUCCESS_START_AT_UPDATED,
    SUCCESS_TIME_RANGE_UPDATED,
)
from backend.database.runtime.session import get_async_session


async def _show_task_settings(event, user_id: int, task_id: str):
    from backend.bot.handlers.task.management import show_task_settings

    await show_task_settings(event, user_id, task_id)


async def _notify_event(event, text: str, *, alert: bool = False):
    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.answer(text, alert=alert)
            return
        except TypeError:
            pass
    await event.respond(text)


def _next_midnight(base_dt: datetime) -> datetime:
    next_day = base_dt.date() + timedelta(days=1)
    return datetime.combine(next_day, datetime.min.time())


async def _set_start_at_value(event, user_id: int, task_id: str, timestamp: int):
    async with get_async_session() as session:
        task = await get_user_task(session, task_id, user_id)
        if task and task.end_at and timestamp >= task.end_at:
            await _notify_event(event, ERROR_END_BEFORE_START, alert=True)
            return
        if task:
            task.start_at = timestamp
            task.revision = int(task.revision) + 1
            await session.commit()
    fsm_storage.reset_state(user_id)
    await _notify_event(event, SUCCESS_START_AT_UPDATED)
    await _show_task_settings(event, user_id, task_id)


async def _set_end_at_value(event, user_id: int, task_id: str, timestamp: int):
    async with get_async_session() as session:
        task = await get_user_task(session, task_id, user_id)
        if task and task.start_at and timestamp <= task.start_at:
            await _notify_event(event, ERROR_END_BEFORE_START, alert=True)
            return
        if task:
            task.end_at = timestamp
            task.revision = int(task.revision) + 1
            await session.commit()
    fsm_storage.reset_state(user_id)
    await _notify_event(event, SUCCESS_END_AT_UPDATED)
    await _show_task_settings(event, user_id, task_id)


async def start_edit_hours(event, user_id: int, task_id: str):
    fsm_storage.set_state(user_id, FSMState.WAIT_DAY_START)
    fsm_storage.update_data(user_id, task_id=task_id)
    keyboard = get_hour_select_keyboard(task_id, for_start=True)
    await event.edit(SELECT_START_HOUR, buttons=keyboard, parse_mode="markdown")


async def set_hour(event, user_id: int, task_id: str, is_start: bool, hour: int):
    data = fsm_storage.get_data(user_id)
    if is_start:
        fsm_storage.set_state(user_id, FSMState.WAIT_DAY_END)
        fsm_storage.update_data(user_id, day_start_hour=hour)
        keyboard = get_hour_select_keyboard(task_id, for_start=False)
        await event.edit(SELECT_END_HOUR, buttons=keyboard, parse_mode="markdown")
        return
    day_start_hour = data.get("day_start_hour")
    async with get_async_session() as session:
        task = await get_user_task(session, task_id, user_id)
        if task:
            task.day_start_hour = day_start_hour
            task.day_end_hour = hour
            task.revision = int(task.revision) + 1
            await session.commit()
    fsm_storage.reset_state(user_id)
    await event.answer(SUCCESS_TIME_RANGE_UPDATED.format(start=day_start_hour, end=hour))
    await _show_task_settings(event, user_id, task_id)


async def set_hours_allday(event, user_id: int, task_id: str):
    async with get_async_session() as session:
        task = await get_user_task(session, task_id, user_id)
        if task:
            task.day_start_hour = 0
            task.day_end_hour = 24
            task.revision = int(task.revision) + 1
            await session.commit()
    fsm_storage.reset_state(user_id)
    await event.answer(SUCCESS_TIME_RANGE_UPDATED.format(start=0, end=24))
    await _show_task_settings(event, user_id, task_id)


async def start_edit_start_at(event, user_id: int, task_id: str):
    fsm_storage.set_state(user_id, FSMState.WAIT_START_AT)
    fsm_storage.update_data(user_id, task_id=task_id)
    now_dt = datetime.now().replace(second=0, microsecond=0)
    later_dt = now_dt + timedelta(minutes=10)
    keyboard = get_start_time_keyboard(
        task_id,
        int(now_dt.timestamp()),
        int(later_dt.timestamp()),
        now_dt.strftime("%Y-%m-%d %H:%M"),
        later_dt.strftime("%Y-%m-%d %H:%M"),
    )
    await event.edit(
        EDIT_START_AT_PROMPT.format(now=now_dt.strftime("%Y-%m-%d %H:%M")),
        buttons=keyboard,
        parse_mode="markdown",
    )


async def handle_start_at_input(event, user_id: int, task_id: str, text: str):
    try:
        timestamp = _parse_timestamp(text)
        await _set_start_at_value(event, user_id, task_id, timestamp)
    except ValueError:
        await _respond_invalid_time(event, task_id, "2026-03-16 18:30", "开始")


async def start_edit_end_at(event, user_id: int, task_id: str):
    fsm_storage.set_state(user_id, FSMState.WAIT_END_AT)
    fsm_storage.update_data(user_id, task_id=task_id)
    async with get_async_session() as session:
        task = await get_user_task(session, task_id, user_id)
    base_dt = datetime.now().replace(second=0, microsecond=0)
    if task and task.start_at:
        base_dt = datetime.fromtimestamp(task.start_at).replace(second=0, microsecond=0)
    next_midnight = _next_midnight(base_dt)
    following_midnight = next_midnight + timedelta(days=1)
    keyboard = get_end_time_keyboard(
        task_id,
        int(next_midnight.timestamp()),
        int(following_midnight.timestamp()),
        next_midnight.strftime("%Y-%m-%d %H:%M"),
        following_midnight.strftime("%Y-%m-%d %H:%M"),
    )
    await event.edit(
        EDIT_END_AT_PROMPT.format(
            suggested_end=next_midnight.strftime("%Y-%m-%d %H:%M")
        ),
        buttons=keyboard,
        parse_mode="markdown",
    )


async def handle_end_at_input(event, user_id: int, task_id: str, text: str):
    try:
        timestamp = _parse_timestamp(text)
        await _set_end_at_value(event, user_id, task_id, timestamp)
    except ValueError:
        await _respond_invalid_time(event, task_id, "2026-03-17 00:00", "结束")


def _parse_timestamp(text: str) -> int:
    value = (text or "").strip()
    return int(datetime.strptime(value, "%Y-%m-%d %H:%M").timestamp())


async def _respond_invalid_time(event, task_id: str, example: str, label: str):
    await event.respond(
        f"{ERROR_INVALID_TIME_FORMAT}\n"
        f"示例：`{example}`\n"
        f"下一步：请重新输入{label}时间，或点击下方按钮返回任务设置。",
        buttons=get_cancel_keyboard(task_id),
        parse_mode="markdown",
    )


async def set_start_at_timestamp(event, user_id: int, task_id: str, timestamp: int):
    await _set_start_at_value(event, user_id, task_id, timestamp)


async def set_end_at_timestamp(event, user_id: int, task_id: str, timestamp: int):
    await _set_end_at_value(event, user_id, task_id, timestamp)
