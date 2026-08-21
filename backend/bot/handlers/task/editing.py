"""Task editing flows for Telegram bot handlers."""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from telethon import events

from backend.bot.state.fsm import FSMState, fsm_storage
from backend.bot.ui.keyboards import (
    get_cancel_keyboard,
    get_interval_keyboard,
    get_shortcut_slot_keyboard,
)
from backend.bot.handlers.core.helpers import (
    format_buttons as _format_buttons,
    parse_buttons,
)
from backend.bot.handlers.task.manual_helpers import task_has_content
from backend.bot.handlers.task.queries import get_user_task as _get_user_task
from backend.bot.ui.messages import *
from backend.database.schema.models import MediaType, ScheduledMessageTask, TaskTriggerMode
from backend.database.runtime.session import get_async_session
from backend.task_media.capture_activation import activate_capture_for_actor
from backend.task_media.capture_service import create_capture
from backend.task_media.contract import TaskMediaError, validate_message_length

MIN_REPEAT_INTERVAL_MINUTES = 60
MAX_REPEAT_INTERVAL_MINUTES = 43200
MAX_MANUAL_TASKS = 3
SHORTCUT_SLOTS = (1, 2, 3)


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


async def toggle_delete_previous(event, user_id: int, task_id: str):
    """切换删除上一条设置。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            task.delete_previous = not task.delete_previous
            task.revision = int(task.revision) + 1
            await session.commit()
            await _show_task_settings(event, user_id, task_id)


async def toggle_pin_message(event, user_id: int, task_id: str):
    """切换置顶设置。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            task.pin_message = not task.pin_message
            task.revision = int(task.revision) + 1
            await session.commit()
            await _show_task_settings(event, user_id, task_id)


async def toggle_trigger_mode(event, user_id: int, task_id: str):
    """切换任务类型。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            current_mode = str(task.trigger_mode or TaskTriggerMode.SCHEDULED.value)
            next_mode = _opposite_trigger_mode(current_mode)
            task.trigger_mode = next_mode
            if next_mode == TaskTriggerMode.MANUAL_SHORTCUT.value:
                configured = await _configure_manual_trigger(
                    session=session,
                    task=task,
                    previous_mode=current_mode,
                    event=event,
                )
                if not configured:
                    return
            else:
                _configure_scheduled_trigger(task)
            task.revision = int(task.revision) + 1
            await session.commit()
    from backend.bot.onboarding import get_onboarding_service
    await get_onboarding_service().sync_home_reply_keyboard(user_id)
    await _notify_event(event, SUCCESS_TRIGGER_MODE_UPDATED)
    await _show_task_settings(event, user_id, task_id)


def _opposite_trigger_mode(current_mode: str) -> str:
    if current_mode == TaskTriggerMode.MANUAL_SHORTCUT.value:
        return TaskTriggerMode.SCHEDULED.value
    return TaskTriggerMode.MANUAL_SHORTCUT.value


async def _configure_manual_trigger(*, session, task, previous_mode: str, event) -> bool:
    if not task_has_content(task):
        task.trigger_mode = previous_mode
        await _notify_event(event, "请先补充文本或媒体内容后，再切换为手动任务。", alert=True)
        return False
    manual_tasks = (
        await session.execute(
            select(ScheduledMessageTask).where(
                ScheduledMessageTask.user_id == task.user_id,
                ScheduledMessageTask.trigger_mode == TaskTriggerMode.MANUAL_SHORTCUT.value,
                ScheduledMessageTask.task_id != task.task_id,
            )
        )
    ).scalars().all()
    if len(manual_tasks) >= MAX_MANUAL_TASKS:
        await _notify_event(event, "当前最多只能保留 3 个手动任务，请先删除一个后再试。", alert=True)
        return False
    used_slots = {
        int(item.shortcut_slot)
        for item in manual_tasks
        if item.shortcut_slot is not None
    }
    task.shortcut_slot = next(
        (slot for slot in SHORTCUT_SLOTS if slot not in used_slots), None
    )
    current_label = str(task.shortcut_label or "").strip()
    task.shortcut_label = current_label or str(task.title or "手动任务").strip()[:20]
    if await _manual_shortcut_label_exists(
        session,
        user_id=task.user_id,
        label=task.shortcut_label,
        current_task_id=task.task_id,
    ):
        await _notify_event(event, "手动任务按钮名称已存在，请先修改任务名称或快捷名称。", alert=True)
        return False
    task.next_run_at = None
    return True


def _configure_scheduled_trigger(task) -> None:
    task.shortcut_slot = None
    task.shortcut_label = None
    if not task.enabled or task.next_run_at is not None:
        return
    now_ts = int(datetime.now().timestamp())
    start_at_ts = int(task.start_at or 0)
    task.next_run_at = max(now_ts, start_at_ts) if start_at_ts > 0 else now_ts


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
                if not task_has_content(task):
                    await _notify_event(event, "请先补充文本或媒体内容后，再加入手动快捷栏。", alert=True)
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
            task.revision = int(task.revision) + 1
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
        "这个名称会直接显示在 Bot 底部按钮中。\n"
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
                if not task_has_content(task):
                    await event.respond("❌ 请先补充文本或媒体内容后，再改成手动任务。")
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
            task.revision = int(task.revision) + 1
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
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            try:
                validate_message_length(text, has_media=task.media_type != MediaType.NONE)
            except TaskMediaError as exc:
                await event.respond(f"❌ {exc.code}：{exc}")
                return
            task.text = text
            task.revision = int(task.revision) + 1
            await session.commit()

    fsm_storage.reset_state(user_id)
    await event.respond(SUCCESS_TEXT_UPDATED)
    await _show_task_settings(event, user_id, task_id)


async def start_edit_media(event, user_id: int, task_id: str):
    """Start a persistent Telegram-native media capture."""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            return
        owner_user_id = int(task.user_id)
        revision = int(task.revision)
    try:
        capture = await create_capture(
            task_id=task_id,
            user_id=owner_user_id,
            expected_revision=revision,
            actor_tg_user_id=int(event.sender_id),
        )
        fsm_storage.reset_state(user_id)
        await activate_capture_for_actor(event, capture.capture_id)
    except HTTPException as exc:
        await _notify_event(event, _http_detail_text(exc), alert=True)


def _http_detail_text(exc: HTTPException) -> str:
    if not isinstance(exc.detail, dict):
        return str(exc.detail)
    code = str(exc.detail.get("code") or "")
    message = str(exc.detail.get("message") or "媒体设置失败")
    return f"{code}：{message}" if code else message


async def start_edit_buttons(event, user_id: int, task_id: str):
    """Clear legacy message buttons; Userbot tasks cannot create new ones."""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            return
        if task.buttons:
            task.buttons = None
            task.revision = int(task.revision) + 1
    await _notify_event(event, "已清除旧消息按钮；执行账号不是 Bot，V2 任务不支持消息按钮。")
    await _show_task_settings(event, user_id, task_id)


async def show_interval_selection(event, user_id: int, task_id: str):
    """显示间隔时间选择。"""
    del user_id
    keyboard = get_interval_keyboard(task_id)
    await event.edit(SELECT_INTERVAL, buttons=keyboard, parse_mode="markdown")


async def start_custom_interval_input(event, user_id: int, task_id: str):
    """开始输入自定义重复间隔。"""
    fsm_storage.set_state(user_id, FSMState.WAIT_INTERVAL)
    fsm_storage.update_data(user_id, task_id=task_id)
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(CUSTOM_INTERVAL_PROMPT, buttons=keyboard, parse_mode="markdown")


async def set_interval(event, user_id: int, task_id: str, interval: int):
    """设置重复间隔。"""
    if interval < MIN_REPEAT_INTERVAL_MINUTES:
        await _notify_event(event, ERROR_INTERVAL_TOO_SHORT, alert=True)
        return False
    if interval > MAX_REPEAT_INTERVAL_MINUTES:
        await _notify_event(event, ERROR_INTERVAL_TOO_LONG, alert=True)
        return False

    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            await _notify_event(event, "任务不存在或无权限", alert=True)
            return False
        task.repeat_interval_min = interval
        if task.enabled:
            now_ts = int(datetime.now().timestamp())
            start_at_ts = int(task.start_at or 0)
            if start_at_ts > 0:
                task.next_run_at = max(now_ts + interval * 60, start_at_ts)
            else:
                task.next_run_at = now_ts + interval * 60
        task.revision = int(task.revision) + 1
        await session.commit()
        await _notify_event(event, SUCCESS_INTERVAL_UPDATED.format(interval=interval))
        await _show_task_settings(event, user_id, task_id)
        return True


async def handle_interval_input(event, user_id: int, task_id: str, text: str):
    """处理自定义重复间隔输入。"""
    raw_value = (text or "").strip()
    try:
        interval = int(raw_value)
    except (TypeError, ValueError):
        await event.respond(ERROR_INTERVAL_INVALID)
        return

    if interval < MIN_REPEAT_INTERVAL_MINUTES:
        await event.respond(ERROR_INTERVAL_TOO_SHORT)
        return
    if interval > MAX_REPEAT_INTERVAL_MINUTES:
        await event.respond(ERROR_INTERVAL_TOO_LONG)
        return

    updated = await set_interval(event, user_id, task_id, interval)
    if updated:
        fsm_storage.reset_state(user_id)
