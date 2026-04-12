"""Task editing flows for Telegram bot handlers."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from telethon import events
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

from backend.bot.state.fsm import FSMState, fsm_storage
from backend.bot.ui.keyboards import (
    get_cancel_keyboard,
    get_end_time_keyboard,
    get_hour_select_keyboard,
    get_interval_keyboard,
    get_shortcut_slot_keyboard,
    get_start_time_keyboard,
)
from backend.bot.handlers.core.helpers import (
    format_buttons as _format_buttons,
    parse_buttons,
)
from backend.bot.handlers.task.manual_helpers import (
    store_task_media_from_bot_message,
    task_has_manual_content,
)
from backend.bot.handlers.task.queries import get_user_task as _get_user_task
from backend.bot.ui.messages import *
from backend.database.schema.models import MediaType, ScheduledMessageTask, TaskTriggerMode
from backend.database.runtime.session import get_async_session


async def _show_task_settings(event, user_id: int, task_id: str):
    from backend.bot.handlers.task.management import show_task_settings
    await show_task_settings(event, user_id, task_id)


async def _notify_event(event, text: str, *, alert: bool = False):
    """Send feedback for both callback events and normal text messages."""
    if isinstance(event, events.CallbackQuery.Event):
        try:
            await event.answer(text, alert=alert)
            return
        except TypeError:
            pass
    await event.respond(text)


async def _manual_shortcut_label_exists(session, *, user_id: int, label: str, current_task_id: str) -> bool:
    """Check whether one manual shortcut label is already used by another task."""
    normalized = str(label or "").strip()
    if not normalized:
        return False
    result = await session.execute(
        select(ScheduledMessageTask.task_id).where(
            ScheduledMessageTask.user_id == user_id,
            ScheduledMessageTask.trigger_mode == TaskTriggerMode.MANUAL_SHORTCUT.value,
            ScheduledMessageTask.task_id != current_task_id,
            func.lower(ScheduledMessageTask.shortcut_label) == normalized.lower(),
        )
    )
    return result.scalar_one_or_none() is not None


def _next_midnight(base_dt: datetime) -> datetime:
    """Return next midnight based on local datetime."""
    next_day = base_dt.date() + timedelta(days=1)
    return datetime.combine(next_day, datetime.min.time())


async def _set_start_at_value(event, user_id: int, task_id: str, timestamp: int):
    """Persist selected start time."""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            if task.end_at and timestamp >= task.end_at:
                await _notify_event(event, ERROR_END_BEFORE_START, alert=True)
                return
            task.start_at = timestamp
            await session.commit()

    fsm_storage.reset_state(user_id)
    await _notify_event(event, SUCCESS_START_AT_UPDATED)
    await _show_task_settings(event, user_id, task_id)


async def _set_end_at_value(event, user_id: int, task_id: str, timestamp: int):
    """Persist selected end time."""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            if task.start_at and timestamp <= task.start_at:
                await _notify_event(event, ERROR_END_BEFORE_START, alert=True)
                return
            task.end_at = timestamp
            await session.commit()

    fsm_storage.reset_state(user_id)
    await _notify_event(event, SUCCESS_END_AT_UPDATED)
    await _show_task_settings(event, user_id, task_id)


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


async def toggle_trigger_mode(event, user_id: int, task_id: str):
    """切换任务类型。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            current_mode = str(task.trigger_mode or TaskTriggerMode.SCHEDULED.value)
            next_mode = (
                TaskTriggerMode.MANUAL_SHORTCUT.value
                if current_mode != TaskTriggerMode.MANUAL_SHORTCUT.value
                else TaskTriggerMode.SCHEDULED.value
            )
            task.trigger_mode = next_mode
            if next_mode == TaskTriggerMode.MANUAL_SHORTCUT.value:
                if not task_has_manual_content(task):
                    task.trigger_mode = current_mode
                    await _notify_event(event, "请先补充文本、按钮或媒体内容后，再切换为手动任务。", alert=True)
                    return
                existing_manual_tasks = (
                    await session.execute(
                        select(ScheduledMessageTask).where(
                            ScheduledMessageTask.user_id == task.user_id,
                            ScheduledMessageTask.trigger_mode == TaskTriggerMode.MANUAL_SHORTCUT.value,
                            ScheduledMessageTask.task_id != task.task_id,
                        )
                    )
                ).scalars().all()
                if len(existing_manual_tasks) >= 3:
                    await _notify_event(event, "当前最多只能保留 3 个手动任务，请先删除一个后再试。", alert=True)
                    return
                used_slots = {int(item.shortcut_slot) for item in existing_manual_tasks if item.shortcut_slot is not None}
                task.shortcut_slot = next((slot for slot in (1, 2, 3) if slot not in used_slots), None)
                task.shortcut_label = str(task.shortcut_label or "").strip() or str(task.title or "手动任务").strip()[:20]
                if await _manual_shortcut_label_exists(
                    session,
                    user_id=task.user_id,
                    label=task.shortcut_label,
                    current_task_id=task.task_id,
                ):
                    await _notify_event(event, "手动任务按钮名称已存在，请先修改任务名称或快捷名称。", alert=True)
                    return
                task.next_run_at = None
            else:
                task.shortcut_slot = None
                task.shortcut_label = None
                if task.enabled and task.next_run_at is None:
                    now_ts = int(datetime.now().timestamp())
                    start_at_ts = int(task.start_at or 0)
                    task.next_run_at = max(now_ts, start_at_ts) if start_at_ts > 0 else now_ts
            await session.commit()
    from backend.bot.onboarding import get_onboarding_service
    await get_onboarding_service().sync_home_reply_keyboard(user_id)
    await _notify_event(event, SUCCESS_TRIGGER_MODE_UPDATED)
    await _show_task_settings(event, user_id, task_id)


async def show_shortcut_slot_selection(event, user_id: int, task_id: str):
    """显示快捷栏位置选择。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        current_slot = task.shortcut_slot if task else None
    keyboard = get_shortcut_slot_keyboard(task_id, current_slot)
    await event.edit("📌 **选择快捷栏位置**\n\n请选择 1-3 号槽位。手动任务会固定显示在底部键盘中。", buttons=keyboard, parse_mode="markdown")


async def set_shortcut_slot(event, user_id: int, task_id: str, slot_value: Optional[str]):
    """设置快捷栏位置。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            return
        if slot_value in {None, "", "clear"}:
            await _notify_event(event, "手动任务必须保留在底部键盘中，如不需要请禁用或删除该任务。", alert=True)
            return
        else:
            if str(task.trigger_mode or TaskTriggerMode.SCHEDULED.value) != TaskTriggerMode.MANUAL_SHORTCUT.value:
                if not task_has_manual_content(task):
                    await _notify_event(event, "请先补充文本、按钮或媒体内容后，再加入手动快捷栏。", alert=True)
                    return
                task.trigger_mode = TaskTriggerMode.MANUAL_SHORTCUT.value
                task.shortcut_label = str(task.shortcut_label or "").strip() or str(task.title or "手动任务").strip()[:20]
                if await _manual_shortcut_label_exists(
                    session,
                    user_id=task.user_id,
                    label=task.shortcut_label,
                    current_task_id=task.task_id,
                ):
                    await _notify_event(event, "手动任务按钮名称已存在，请先修改任务名称或快捷名称。", alert=True)
                    return
                task.next_run_at = None
            slot = int(slot_value)
            exists = await session.execute(
                select(ScheduledMessageTask.task_id).where(
                    ScheduledMessageTask.user_id == task.user_id,
                    ScheduledMessageTask.shortcut_slot == slot,
                    ScheduledMessageTask.task_id != task.task_id,
                )
            )
            if exists.scalar_one_or_none() is not None:
                await _notify_event(event, f"快捷栏位置 {slot} 已被其他任务占用", alert=True)
                return
            task.shortcut_slot = slot
            await session.commit()
            from backend.bot.onboarding import get_onboarding_service
            await get_onboarding_service().sync_home_reply_keyboard(user_id)
            await _notify_event(event, SUCCESS_SHORTCUT_SLOT_UPDATED)
    await _show_task_settings(event, user_id, task_id)


async def start_edit_shortcut_label(event, user_id: int, task_id: str):
    """开始编辑快捷名称。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            return

    fsm_storage.set_state(user_id, FSMState.WAIT_SHORTCUT_LABEL)
    fsm_storage.update_data(user_id, task_id=task_id)
    current_label = str(task.shortcut_label or "").strip() or "（默认使用任务标题）"
    text = (
        "🏷️ **修改快捷名称**\n\n"
        "请输入底部快捷按钮显示名称，最长 20 个字符。\n"
        "发送 `clear` 可恢复为默认标题。\n\n"
        f"当前名称：`{current_label}`"
    )
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(text, buttons=keyboard, parse_mode="markdown")


async def handle_shortcut_label_input(event, user_id: int, task_id: str, text: str):
    """处理快捷名称输入。"""
    value = (text or "").strip()
    if not value or value.lower() == "clear":
        await event.respond("❌ 手动任务必须填写按钮名称。")
        return
    if len(value) > 20:
        await event.respond("❌ 快捷名称最长 20 个字符。")
        return

    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            task.shortcut_label = value
            if str(task.trigger_mode or "") != TaskTriggerMode.MANUAL_SHORTCUT.value:
                if not task_has_manual_content(task):
                    await event.respond("❌ 请先补充文本、按钮或媒体内容后，再改成手动任务。")
                    return
                existing_manual_tasks = (
                    await session.execute(
                        select(ScheduledMessageTask).where(
                            ScheduledMessageTask.user_id == task.user_id,
                            ScheduledMessageTask.trigger_mode == TaskTriggerMode.MANUAL_SHORTCUT.value,
                            ScheduledMessageTask.task_id != task.task_id,
                        )
                    )
                ).scalars().all()
                if len(existing_manual_tasks) >= 3:
                    await event.respond("❌ 当前最多只能保留 3 个手动任务，请先删除一个后再试。")
                    return
                used_slots = {int(item.shortcut_slot) for item in existing_manual_tasks if item.shortcut_slot is not None}
                task.trigger_mode = TaskTriggerMode.MANUAL_SHORTCUT.value
                task.shortcut_slot = task.shortcut_slot or next((slot for slot in (1, 2, 3) if slot not in used_slots), None)
                task.next_run_at = None
            if await _manual_shortcut_label_exists(
                session,
                user_id=task.user_id,
                label=value,
                current_task_id=task.task_id,
            ):
                await event.respond("❌ 手动任务按钮名称已存在，请换一个名称。")
                return
            await session.commit()

    fsm_storage.reset_state(user_id)
    from backend.bot.onboarding import get_onboarding_service
    await get_onboarding_service().sync_home_reply_keyboard(user_id)
    await event.respond(SUCCESS_SHORTCUT_LABEL_UPDATED)
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
            try:
                task.media_file_id = await store_task_media_from_bot_message(
                    account_id=str(task.account_id or ""),
                    event=event,
                    media=media,
                    media_type=media_type,
                )
            except HTTPException as exc:
                await event.respond(f"❌ {exc.detail}")
                return
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


async def set_hours_allday(event, user_id: int, task_id: str):
    """设置发送时段为全天。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            task.day_start_hour = 0
            # 调度判断是 start <= hour < end，全天应设置为 [0, 24)。
            task.day_end_hour = 24
            await session.commit()

    fsm_storage.reset_state(user_id)
    await event.answer(SUCCESS_TIME_RANGE_UPDATED.format(start=0, end=24))
    await _show_task_settings(event, user_id, task_id)


async def start_edit_start_at(event, user_id: int, task_id: str):
    """开始编辑开始时间。"""
    fsm_storage.set_state(user_id, FSMState.WAIT_START_AT)
    fsm_storage.update_data(user_id, task_id=task_id)
    now_dt = datetime.now().replace(second=0, microsecond=0)
    keyboard = get_start_time_keyboard(
        task_id,
        int(now_dt.timestamp()),
        int((now_dt + timedelta(minutes=10)).timestamp()),
        now_dt.strftime("%Y-%m-%d %H:%M"),
        (now_dt + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M"),
    )
    await event.edit(
        EDIT_START_AT_PROMPT.format(now=now_dt.strftime("%Y-%m-%d %H:%M")),
        buttons=keyboard,
        parse_mode="markdown",
    )


async def handle_start_at_input(event, user_id: int, task_id: str, text: str):
    """处理开始时间输入。"""
    try:
        raw_text = (text or "").strip()
        dt = datetime.strptime(raw_text, "%Y-%m-%d %H:%M")
        timestamp = int(dt.timestamp())
        await _set_start_at_value(event, user_id, task_id, timestamp)
    except ValueError:
        await event.respond(
            f"{ERROR_INVALID_TIME_FORMAT}\n"
            "示例：`2026-03-16 18:30`\n"
            "下一步：请重新输入开始时间，或点击下方按钮返回任务设置。",
            buttons=get_cancel_keyboard(task_id),
            parse_mode="markdown",
        )


async def start_edit_end_at(event, user_id: int, task_id: str):
    """开始编辑结束时间。"""
    fsm_storage.set_state(user_id, FSMState.WAIT_END_AT)
    fsm_storage.update_data(user_id, task_id=task_id)
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)

    base_dt = datetime.now().replace(second=0, microsecond=0)
    if task and task.start_at:
        base_dt = datetime.fromtimestamp(task.start_at).replace(second=0, microsecond=0)
    next_midnight = _next_midnight(base_dt)
    keyboard = get_end_time_keyboard(
        task_id,
        int(next_midnight.timestamp()),
        int((next_midnight + timedelta(days=1)).timestamp()),
        next_midnight.strftime("%Y-%m-%d %H:%M"),
        (next_midnight + timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
    )
    await event.edit(
        EDIT_END_AT_PROMPT.format(suggested_end=next_midnight.strftime("%Y-%m-%d %H:%M")),
        buttons=keyboard,
        parse_mode="markdown",
    )


async def handle_end_at_input(event, user_id: int, task_id: str, text: str):
    """处理结束时间输入。"""
    try:
        raw_text = (text or "").strip()
        dt = datetime.strptime(raw_text, "%Y-%m-%d %H:%M")
        timestamp = int(dt.timestamp())
        await _set_end_at_value(event, user_id, task_id, timestamp)
    except ValueError:
        await event.respond(
            f"{ERROR_INVALID_TIME_FORMAT}\n"
            "示例：`2026-03-17 00:00`\n"
            "下一步：请重新输入结束时间，或点击下方按钮返回任务设置。",
            buttons=get_cancel_keyboard(task_id),
            parse_mode="markdown",
        )


async def set_start_at_timestamp(event, user_id: int, task_id: str, timestamp: int):
    """通过快捷按钮设置开始时间。"""
    await _set_start_at_value(event, user_id, task_id, timestamp)


async def set_end_at_timestamp(event, user_id: int, task_id: str, timestamp: int):
    """通过快捷按钮设置结束时间。"""
    await _set_end_at_value(event, user_id, task_id, timestamp)
