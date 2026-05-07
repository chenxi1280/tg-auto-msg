"""Task management entry points for Telegram bot handlers."""
from __future__ import annotations

from datetime import datetime

from telethon import Button, events
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto
from sqlalchemy import func, select
from fastapi import HTTPException
from loguru import logger

from backend.bot.account.reauth import (
    get_reauth_required_message,
    is_reauth_required_account,
)
from backend.bot.handlers.core.helpers import (
    format_buttons as _format_buttons,
    escape_markdown as _escape_markdown,
    format_timestamp as _format_timestamp,
    generate_h5_task_logs_url,
    generate_h5_url,
    is_valid_button_url,
    normalize_task_targets as _normalize_task_targets,
    peer_meta as _peer_meta,
    truncate_text as _truncate_text,
)
from backend.bot.handlers.task.queries import (
    USER_MODE_ACCOUNT_SCOPED,
    get_user_task as _get_user_task,
    resolve_actor_access_context as _resolve_actor_access_context,
)
from backend.bot.handlers.core.user_link import (
    get_active_account_id as _get_active_account_id,
    normalize_operator_account_refs as _normalize_operator_account_refs,
)
from backend.bot.handlers.core.helpers import parse_buttons
from backend.bot.state.fsm import FSMState, fsm_storage
from backend.bot.handlers.task.manual_helpers import store_task_media_from_bot_message, task_has_manual_content
from backend.bot.ui.keyboards import (
    get_confirm_delete_keyboard,
    get_task_list_keyboard,
    get_task_settings_keyboard,
)
from backend.bot.ui.messages import *
from backend.database.schema.models import (
    Account,
    MediaType,
    Resource,
    ScheduledMessageTask,
    TaskTriggerMode,
    TaskTriggerSource,
)
from backend.database.runtime.session import get_async_session
from backend.h5_backend.services.licensing.service import require_account_task_permission
from backend.h5_backend.services.task.service import get_task_service
from backend.scheduler.core.task_runner import execute_task_once

# Selection flows (kept import-compatible for callback/message dispatch modules)
from backend.bot.handlers.task.target_selection import (
    _handle_pick_account,
    _handle_pick_clear,
    _handle_pick_done,
    _handle_pick_resource,
    handle_target_search_input,
    start_select_task_account,
    start_select_task_targets,
)

# Editing flows (kept import-compatible for callback/message dispatch modules)
from backend.bot.handlers.task.editing import (
    handle_buttons_input,
    handle_end_at_input,
    handle_media_input,
    handle_start_at_input,
    handle_text_input,
    set_hour,
    set_interval,
    show_interval_selection,
    start_edit_buttons,
    start_edit_end_at,
    start_edit_hours,
    start_edit_media,
    start_edit_start_at,
    start_edit_text,
    toggle_delete_previous,
    toggle_pin_message,
)


def _should_edit_event(event) -> bool:
    """Check if event is a callback query (can use event.edit)."""
    from backend.bot.handlers.core.helpers import should_edit_event
    return should_edit_event(event)


async def _answer_or_respond(event, text: str, *, alert: bool = False, parse_mode: str | None = None):
    """Safely reply for both callback and message events."""
    if hasattr(event, "answer"):
        try:
            await event.answer(text, alert=alert)
            return
        except TypeError:
            pass
        except Exception:
            # Fall back to message reply when callback answer is unavailable.
            pass
    await event.respond(text, parse_mode=parse_mode)


def _display_hour(hour: int | None) -> str:
    """Render hour for settings text, preserving 0."""
    return "-" if hour is None else f"{hour:02d}"


def _format_time_range(start_hour: int | None, end_hour: int | None) -> str:
    """Render task time range with all-day semantics."""
    if (start_hour is None and end_hour is None) or (start_hour == 0 and end_hour == 24):
        return "全天（24小时）"
    return f"{_display_hour(start_hour)}:00 - {_display_hour(end_hour)}:00"


def _format_run_bound(ts: int | None) -> str:
    """Render start/end bound with continuous-run hint."""
    return "未设置（一直执行）" if ts is None else _format_timestamp(ts)


def _render_shortcut_status(task: ScheduledMessageTask) -> str:
    if str(task.trigger_mode or "") != TaskTriggerMode.MANUAL_SHORTCUT.value:
        return "不适用"
    return f"槽位 {task.shortcut_slot}" if task.shortcut_slot else "未加入快捷栏"


def _render_shortcut_label(task: ScheduledMessageTask) -> str:
    label = str(task.shortcut_label or "").strip()
    if label:
        return label
    return _truncate_text(str(task.title or "快捷任务"), 20)


def _task_create_entry_keyboard(*, account_id: str | None = None) -> list:
    suffix = f":{account_id}" if account_id else ""
    return [
        [
            Button.inline("⏰ 创建定时任务", data=f"add_scheduled_task{suffix}"),
            Button.inline("🖱️ 创建手动任务", data=f"add_manual_task{suffix}"),
        ],
        [Button.inline("⬅️ 返回任务页", data="task_list")],
    ]


async def show_task_list(event, user_id: int):
    """显示任务列表。"""
    from backend.bot.onboarding import get_onboarding_service
    from backend.bot.handlers.task.selector_context import clear_selector_context
    clear_selector_context(user_id)

    if await get_onboarding_service().ensure_registered_user(event, user_id) is None:
        return

    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        db_user_id = access_ctx.system_user_id
        if db_user_id is None:
            if hasattr(event, "answer"):
                await event.answer(
                    "当前 Telegram 账号还未绑定系统账号，请先发送 /start，或回到 Web 首页点击“系统账号绑定到 TG Bot”。",
                    alert=True,
                )
            else:
                await event.respond(
                    "⚠️ 当前 Telegram 账号还未绑定系统账号。\n\n"
                    "请先发送 `/start`，或回到 Web 首页点击“系统账号绑定到 TG Bot”完成绑定。",
                    buttons=[[Button.inline("🚀 开始使用", data="bot_home")]],
                    parse_mode="markdown",
                )
            return

        stmt = (
            select(ScheduledMessageTask)
            .where(ScheduledMessageTask.user_id == db_user_id)
            .order_by(ScheduledMessageTask.created_at.desc())
        )
        if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED and access_ctx.scoped_account_id:
            stmt = stmt.where(ScheduledMessageTask.account_id == str(access_ctx.scoped_account_id))
        result = await session.execute(stmt)
        tasks = result.scalars().all()

    if not tasks:
        text = TASK_LIST_HEADER + TASK_EMPTY
        keyboard = [
            [Button.inline("⏰ 创建定时任务", data="add_scheduled_task")],
            [Button.inline("🖱️ 创建手动任务", data="add_manual_task")],
            [Button.inline("⬅️ 返回主菜单", data="bot_home")],
        ]
    else:
        task_data = []
        for task in tasks:
            task_data.append(
                (
                    task.task_id,
                    task.enabled,
                    task.repeat_interval_min,
                    task.media_type != MediaType.NONE,
                    bool(task.buttons),
                    bool(task.text),
                    task.title[:30] + "..." if len(task.title) > 30 else task.title,
                )
            )
        text = TASK_LIST_HEADER + f"📊 共 {len(tasks)} 个任务\n\n下一步：请选择一个任务查看设置，或点击下方入口继续创建任务。\n"
        keyboard = get_task_list_keyboard(task_data)

    if _should_edit_event(event):
        await event.edit(text, buttons=keyboard, parse_mode="markdown")
    else:
        await event.respond(text, buttons=keyboard, parse_mode="markdown")


async def show_task_settings(event, user_id: int, task_id: str):
    """显示任务设置页。"""
    from backend.bot.handlers.task.selector_context import clear_selector_context
    clear_selector_context(user_id)

    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        account = None
        resources_by_key: dict[tuple[str, int], Resource] = {}

        if task and task.account_id:
            account_result = await session.execute(
                select(Account).where(Account.account_id == task.account_id)
            )
            account = account_result.scalar_one_or_none()

            targets = _normalize_task_targets(task)
            peer_ids = list({int(t["peer_id"]) for t in targets})
            if peer_ids:
                resource_result = await session.execute(
                    select(Resource).where(
                        Resource.account_id == task.account_id,
                        Resource.peer_id.in_(peer_ids),
                        Resource.is_active == True,
                    )
                )
                for resource in resource_result.scalars().all():
                    resources_by_key[(str(resource.peer_type), int(resource.peer_id))] = resource

    if not task:
        await event.answer("任务不存在，请返回任务页后重试。", alert=True)
        return

    account_display = "未设置"
    if account:
        if account.username:
            account_display = f"@{account.username}"
        elif account.phone:
            account_display = account.phone
        else:
            account_display = account.account_id[:8]
    elif task.account_id:
        account_display = task.account_id[:8]

    targets = _normalize_task_targets(task)
    if targets:
        target_items: list[str] = []
        for target in targets[:3]:
            peer_type = str(target["peer_type"])
            peer_id = int(target["peer_id"])
            icon, _ = _peer_meta(peer_type)
            resource = resources_by_key.get((peer_type, peer_id))
            if resource:
                name = resource.title or (f"@{resource.username}" if resource.username else str(peer_id))
            else:
                name = str(peer_id)
            target_items.append(f"{icon}{_truncate_text(name, 16)}")
        target_display = "、".join(target_items)
        if len(targets) > 3:
            target_display += f" 等{len(targets)}个"
    else:
        target_display = "未设置"

    text = TASK_SETTINGS_TEMPLATE.format(
        title=_escape_markdown(task.title),
        enabled_status=STATUS_ENABLED if task.enabled else STATUS_DISABLED,
        trigger_mode="手动任务" if str(task.trigger_mode or "") == TaskTriggerMode.MANUAL_SHORTCUT.value else "定时任务",
        shortcut_status=_render_shortcut_status(task),
        shortcut_label=_escape_markdown(_render_shortcut_label(task)),
        interval_line=(
            f"• 重复间隔: 每 {task.repeat_interval_min} 分钟"
            if str(task.trigger_mode or "") != TaskTriggerMode.MANUAL_SHORTCUT.value
            else "• 触发方式: 仅点击底部快捷按钮时执行一次"
        ),
        account_display=_escape_markdown(account_display),
        target_display=_escape_markdown(target_display),
        time_control_block=(
            "\n".join(
                [
                    f"• 发送时段: {_format_time_range(task.day_start_hour, task.day_end_hour)}",
                    f"• 开始日期: {_format_run_bound(task.start_at)}",
                    f"• 结束日期: {_format_run_bound(task.end_at)}",
                    "• 规则说明: 未设置开始/结束时间时，任务将一直执行",
                ]
            )
            if str(task.trigger_mode or "") != TaskTriggerMode.MANUAL_SHORTCUT.value
            else "• 手动任务不参与自动调度，点击快捷按钮时立即执行"
        ),
        text_status=STATUS_HAS if task.text else STATUS_NOT_SET,
        media_status=task.media_type.value if task.media_type != MediaType.NONE else "无",
        buttons_status=STATUS_HAS if task.buttons else STATUS_NOT_SET,
        delete_status=STATUS_YES if task.delete_previous else STATUS_NO,
        pin_status=STATUS_YES if task.pin_message else STATUS_NO,
    )

    keyboard = get_task_settings_keyboard(task)

    if _should_edit_event(event):
        await event.edit(text, buttons=keyboard, parse_mode="markdown")
    else:
        await event.respond(text, buttons=keyboard, parse_mode="markdown")


async def _start_task_creation(event, user_id: int, *, trigger_mode: str, preferred_account_id: str | None = None):
    """开始任务创建流程，选择完成前不落库。"""
    from backend.bot.onboarding import get_onboarding_service
    from backend.bot.handlers.task.selector_context import set_selector_context

    if await get_onboarding_service().ensure_registered_user(event, user_id) is None:
        return

    selected_account_id: str | None = None

    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        db_user_id = access_ctx.system_user_id
        if db_user_id is None:
            await event.answer("当前 Telegram 账号还未绑定系统账号，请先发送 /start，或回到 Web 首页点击“系统账号绑定到 TG Bot”。", alert=True)
            return

        active_accounts = (
            await session.execute(
                select(Account.account_id)
                .where(
                    Account.user_id == int(db_user_id),
                    Account.is_active == True,
                )
                .order_by(Account.updated_at.desc(), Account.last_used_at.desc(), Account.created_at.desc())
            )
        ).scalars().all()
        ref_state = await _normalize_operator_account_refs(
            session,
            user_id,
            db_user_id,
            valid_account_ids=[str(item) for item in active_accounts],
            preferred_account_id=preferred_account_id or (str(active_accounts[0]) if len(active_accounts) == 1 else None),
        )
        preferred_account_id = preferred_account_id or ref_state.get("active_account_id") or await _get_active_account_id(session, user_id, db_user_id)
        if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED and access_ctx.scoped_account_id:
            preferred_account_id = str(access_ctx.scoped_account_id)
        if preferred_account_id:
            account_result = await session.execute(
                select(Account).where(
                    Account.account_id == preferred_account_id,
                    Account.user_id == db_user_id,
                    Account.is_active == True,
                )
            )
            preferred_account = account_result.scalar_one_or_none()
            if preferred_account and not is_reauth_required_account(preferred_account):
                selected_account_id = preferred_account.account_id
        if (
            access_ctx.mode == USER_MODE_ACCOUNT_SCOPED
            and access_ctx.scoped_account_id
            and selected_account_id is None
        ):
            await event.answer(get_reauth_required_message(), alert=True)
            return

    draft_task_id = "__draft_new_task__"
    set_selector_context(
        user_id,
        task_id=draft_task_id,
        account_id=selected_account_id,
        page=0,
        peer_filter="all",
        search="",
        draft_mode=True,
        draft_targets=[],
        draft_trigger_mode=trigger_mode,
    )

    if selected_account_id:
        await start_select_task_targets(event, user_id, draft_task_id, page=0)
    else:
        await start_select_task_account(event, user_id, draft_task_id)


async def create_new_task(event, user_id: int):
    """显示任务创建入口。"""
    from backend.bot.onboarding import get_onboarding_service

    if await get_onboarding_service().ensure_registered_user(event, user_id) is None:
        return

    text = (
        "🧩 **选择任务类型**\n\n"
        "• 定时任务：按计划自动发送\n"
        "• 手动任务：显示在 Bot 底部按钮，点击一次发送一次"
    )
    keyboard = _task_create_entry_keyboard()
    if _should_edit_event(event):
        await event.edit(text, buttons=keyboard, parse_mode="markdown")
    else:
        await event.respond(text, buttons=keyboard, parse_mode="markdown")


async def create_new_scheduled_task(event, user_id: int, account_id: str | None = None):
    await _start_task_creation(
        event,
        user_id,
        trigger_mode=TaskTriggerMode.SCHEDULED.value,
        preferred_account_id=account_id,
    )


async def _ensure_manual_task_capacity(event, user_id: int) -> bool:
    """Return whether current user can start creating one more manual task."""
    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        db_user_id = access_ctx.system_user_id
        if db_user_id is None:
            await _answer_or_respond(
                event,
                "当前 Telegram 账号还未绑定系统账号，请先发送 /start，或回到 Web 首页点击“系统账号绑定到 TG Bot”。",
                alert=True,
            )
            return False
        count = int(
            (
                await session.execute(
                    select(func.count()).select_from(ScheduledMessageTask).where(
                        ScheduledMessageTask.user_id == db_user_id,
                        ScheduledMessageTask.trigger_mode == TaskTriggerMode.MANUAL_SHORTCUT.value,
                    )
                )
            ).scalar_one()
            or 0
        )
    if count >= 3:
        await _answer_or_respond(event, "每个用户最多只能创建 3 个手动任务，请先删除一个后再试。", alert=True)
        return False
    return True


async def create_new_manual_task(event, user_id: int, account_id: str | None = None):
    if not await _ensure_manual_task_capacity(event, user_id):
        return
    await _start_task_creation(
        event,
        user_id,
        trigger_mode=TaskTriggerMode.MANUAL_SHORTCUT.value,
        preferred_account_id=account_id,
    )


async def create_new_task_for_account(event, user_id: int, account_id: str):
    """从账号页显示任务创建入口。"""
    from backend.bot.onboarding import get_onboarding_service

    if await get_onboarding_service().ensure_registered_user(event, user_id) is None:
        return

    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        db_user_id = access_ctx.system_user_id
        if db_user_id is None:
            await event.answer("当前 Telegram 账号还未绑定系统账号，请先发送 /start，或回到 Web 首页点击“系统账号绑定到 TG Bot”。", alert=True)
            return
        if (
            access_ctx.mode == USER_MODE_ACCOUNT_SCOPED
            and access_ctx.scoped_account_id
            and str(account_id) != str(access_ctx.scoped_account_id)
        ):
            await event.answer("受限模式下仅可为自己的账号创建任务。", alert=True)
            return

        account_result = await session.execute(
            select(Account).where(
                Account.account_id == account_id,
                Account.user_id == db_user_id,
                Account.is_active == True,
            )
        )
        account = account_result.scalar_one_or_none()
        if not account or is_reauth_required_account(account):
            await event.answer(get_reauth_required_message(), alert=True)
            return

    text = (
        "🧩 **选择任务类型**\n\n"
        "当前会为这个 Telegram 账号创建任务，请直接选择："
    )
    keyboard = _task_create_entry_keyboard(account_id=account_id)
    if _should_edit_event(event):
        await event.edit(text, buttons=keyboard, parse_mode="markdown")
    else:
        await event.respond(text, buttons=keyboard, parse_mode="markdown")


async def toggle_task(event, user_id: int, task_id: str):
    """切换任务启用状态。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            next_enabled = not task.enabled
            if (
                next_enabled
                and str(task.trigger_mode or TaskTriggerMode.SCHEDULED.value) == TaskTriggerMode.MANUAL_SHORTCUT.value
                and not task_has_manual_content(task)
            ):
                await event.answer("请先补充文本、按钮或媒体内容后，再启用手动任务。", alert=True)
                return
            task.enabled = next_enabled
            if (
                task.enabled
                and task.next_run_at is None
                and str(task.trigger_mode or TaskTriggerMode.SCHEDULED.value) == TaskTriggerMode.SCHEDULED.value
            ):
                now_ts = int(datetime.now().timestamp())
                start_at_ts = int(task.start_at or 0)
                task.next_run_at = max(now_ts, start_at_ts) if start_at_ts > 0 else now_ts
            await session.commit()
            await event.answer(f"✅ 任务已{'启用' if task.enabled else '禁用'}")
            await show_task_list(event, user_id)


async def confirm_delete_task(event, user_id: int, task_id: str):
    """确认删除任务。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            text = CONFIRM_DELETE.format(title=task.title)
            keyboard = get_confirm_delete_keyboard(task_id)
            await event.edit(text, buttons=keyboard, parse_mode="markdown")


async def delete_task(event, user_id: int, task_id: str):
    """删除任务。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            await event.answer("任务不存在或无权限", alert=True)
            return
        await session.delete(task)
        await session.commit()

    await event.answer("✅ 任务已删除")
    await show_task_list(event, user_id)


async def update_task_enabled(event, user_id: int, task_id: str, enabled: bool):
    """更新任务启用状态。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            if (
                enabled
                and str(task.trigger_mode or TaskTriggerMode.SCHEDULED.value) == TaskTriggerMode.MANUAL_SHORTCUT.value
                and not task_has_manual_content(task)
            ):
                await event.answer("请先补充文本、按钮或媒体内容后，再启用手动任务。", alert=True)
                return
            task.enabled = enabled
            if (
                enabled
                and task.next_run_at is None
                and str(task.trigger_mode or TaskTriggerMode.SCHEDULED.value) == TaskTriggerMode.SCHEDULED.value
            ):
                now_ts = int(datetime.now().timestamp())
                start_at_ts = int(task.start_at or 0)
                task.next_run_at = max(now_ts, start_at_ts) if start_at_ts > 0 else now_ts
            await session.commit()
            await event.answer(SUCCESS_TASK_ENABLED if enabled else SUCCESS_TASK_DISABLED)
            await show_task_settings(event, user_id, task_id)


async def open_h5_webapp(event, user_id: int, task_id: str):
    """打开 H5 控制台。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            await event.answer("任务不存在或无权限", alert=True)
            return

    url = generate_h5_url(task_id)
    await event.answer(f"🌐 请点击下方链接进入 H5 控制台:\n{url}", alert=True)


async def open_task_logs_page(event, user_id: int, task_id: str):
    """打开任务发送记录页面。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            await event.answer("任务不存在或无权限", alert=True)
            return

    url = generate_h5_task_logs_url(task_id)
    if is_valid_button_url(url):
        await event.respond(
            "📋 **发送记录**\n\n下一步：点击下方按钮查看该任务的发送记录。",
            buttons=[[Button.url("📋 查看记录", url)]],
        )
        return

    await event.answer(f"📊 请在浏览器打开任务发送记录:\n{url}", alert=True)


async def handle_manual_task_shortcut_label_create(event, user_id: int, text: str):
    """Handle shortcut label input for manual task creation wizard."""
    value = str(text or "").strip()
    if not value:
        await event.respond("❌ 手动任务必须填写按钮名称。")
        return
    if len(value) > 20:
        await event.respond("❌ 按钮名称最长 20 个字符。")
        return

    draft = dict(fsm_storage.get_data(user_id).get("pending_manual_task_create") or {})
    if not draft:
        fsm_storage.reset_state(user_id)
        await event.respond("⚠️ 当前手动任务创建流程已失效，请重新开始。")
        return

    account_id = str(draft.get("account_id") or "").strip()
    if not account_id:
        fsm_storage.reset_state(user_id)
        await event.respond("⚠️ 未找到执行账号，请重新开始创建手动任务。")
        return

    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        db_user_id = access_ctx.system_user_id
        if db_user_id is None:
            fsm_storage.reset_state(user_id)
            await event.respond("⚠️ 当前 Telegram 账号还未绑定系统账号，请先发送 /start。")
            return
        result = await session.execute(
            select(ScheduledMessageTask.task_id).where(
                ScheduledMessageTask.user_id == int(db_user_id),
                ScheduledMessageTask.trigger_mode == TaskTriggerMode.MANUAL_SHORTCUT.value,
                func.lower(ScheduledMessageTask.shortcut_label) == value.lower(),
            )
        )
        if result.scalar_one_or_none() is not None:
            await event.respond("❌ 手动任务按钮名称已存在，请换一个名称。")
            return

    draft["shortcut_label"] = value
    fsm_storage.update_data(user_id, pending_manual_task_create=draft)
    fsm_storage.set_state(user_id, FSMState.WAIT_MANUAL_TASK_TEXT)
    await event.respond(
        "📝 **创建手动任务**\n\n"
        f"按钮名称：`{_escape_markdown(value)}`\n\n"
        "这个名称会显示在 Bot 底部按钮中。\n\n"
        "下一步：请输入这次点击按钮后要发送的文本内容。\n"
        "如果想只发按钮或媒体，也可以发送 `skip` 跳过这一步。",
        parse_mode="markdown",
    )


async def handle_manual_task_text_create(event, user_id: int, text: str):
    """Handle text input for manual task creation wizard."""
    value = str(text or "").strip()
    if value.lower() in {"skip", "跳过"}:
        value = ""
    if len(value) > 4096:
        await event.respond(ERROR_TEXT_TOO_LONG)
        return

    draft = dict(fsm_storage.get_data(user_id).get("pending_manual_task_create") or {})
    if not draft:
        fsm_storage.reset_state(user_id)
        await event.respond("⚠️ 当前手动任务创建流程已失效，请重新开始。")
        return

    draft["text"] = value or None
    fsm_storage.update_data(user_id, pending_manual_task_create=draft)
    fsm_storage.set_state(user_id, FSMState.WAIT_MANUAL_TASK_BUTTONS)
    current_text = _escape_markdown(value) if value else "（已跳过）"
    await event.respond(
        "🔘 **创建手动任务**\n\n"
        f"文本内容：{current_text}\n\n"
        "下一步：请输入按钮内容，格式为 `文字 - 链接`，每行一组；\n"
        "如果不需要按钮，请发送 `skip`。",
        parse_mode="markdown",
    )


async def handle_manual_task_buttons_create(event, user_id: int, text: str):
    """Handle buttons input for manual task creation wizard."""
    raw = str(text or "").strip()
    buttons = None
    if raw.lower() not in {"skip", "跳过"}:
        try:
            buttons = parse_buttons(raw)
        except Exception as exc:
            await event.respond(f"{ERROR_INVALID_BUTTON_FORMAT}\n错误: {str(exc)}")
            return

    draft = dict(fsm_storage.get_data(user_id).get("pending_manual_task_create") or {})
    if not draft:
        fsm_storage.reset_state(user_id)
        await event.respond("⚠️ 当前手动任务创建流程已失效，请重新开始。")
        return

    draft["buttons"] = buttons
    fsm_storage.update_data(user_id, pending_manual_task_create=draft)
    fsm_storage.set_state(user_id, FSMState.WAIT_MANUAL_TASK_MEDIA)
    buttons_preview = _escape_markdown(_format_buttons(buttons) if buttons else "（已跳过）")
    await event.respond(
        "🖼️ **创建手动任务**\n\n"
        f"按钮配置：{buttons_preview}\n\n"
        "下一步：请发送一张图片、视频或 GIF 作为媒体；\n"
        "如果不需要媒体，请发送 `skip`。",
        parse_mode="markdown",
    )


async def handle_manual_task_media_text_input(event, user_id: int, text: str):
    """Handle textual skip/invalid input during media step."""
    value = str(text or "").strip().lower()
    if value in {"skip", "跳过"}:
        await _finalize_manual_task_create(event, user_id)
        return
    await event.respond("❌ 这一步请发送图片、视频、GIF，或者发送 `skip` 跳过。", parse_mode="markdown")


async def handle_manual_task_media_create(event, user_id: int, task_id: str, media):
    """Handle media upload for manual task creation wizard."""
    del task_id
    media_type = MediaType.NONE

    if isinstance(media, MessageMediaPhoto):
        media_type = MediaType.PHOTO
    elif isinstance(media, MessageMediaDocument):
        for attr in media.document.attributes:
            if hasattr(attr, "video"):
                media_type = MediaType.VIDEO
            elif hasattr(attr, "animated"):
                media_type = MediaType.ANIMATION

    if media_type == MediaType.NONE:
        await event.respond(ERROR_INVALID_MEDIA)
        return

    draft = dict(fsm_storage.get_data(user_id).get("pending_manual_task_create") or {})
    if not draft:
        fsm_storage.reset_state(user_id)
        await event.respond("⚠️ 当前手动任务创建流程已失效，请重新开始。")
        return

    draft["media_type"] = media_type.value
    account_id = str(draft.get("account_id") or "").strip()
    if not account_id:
        fsm_storage.reset_state(user_id)
        await event.respond("⚠️ 未找到执行账号，请重新开始创建手动任务。")
        return
    try:
        draft["media_file_id"] = await store_task_media_from_bot_message(
            account_id=account_id,
            event=event,
            media=media,
            media_type=media_type,
        )
    except HTTPException as exc:
        await event.respond(f"❌ {exc.detail}")
        return
    fsm_storage.update_data(user_id, pending_manual_task_create=draft)
    await _finalize_manual_task_create(event, user_id)


async def _finalize_manual_task_create(event, user_id: int):
    """Persist pending manual task draft."""
    draft = dict(fsm_storage.get_data(user_id).get("pending_manual_task_create") or {})
    if not draft:
        fsm_storage.reset_state(user_id)
        await event.respond("⚠️ 当前手动任务创建流程已失效，请重新开始。")
        return

    text_value = str(draft.get("text") or "").strip() or None
    buttons = draft.get("buttons")
    media_type = str(draft.get("media_type") or MediaType.NONE.value)
    media_file_id = str(draft.get("media_file_id") or "").strip() or None

    payload = {
        "account_id": draft.get("account_id"),
        "target_peers": list(draft.get("targets") or []),
        "title": str(draft.get("shortcut_label") or "手动任务"),
        "enabled": True,
        "trigger_mode": TaskTriggerMode.MANUAL_SHORTCUT.value,
        "shortcut_label": str(draft.get("shortcut_label") or "").strip(),
        "repeat_interval_min": 60,
        "text": text_value,
        "media_type": media_type,
        "media_file_id": media_file_id,
        "buttons": buttons,
        "delete_previous": False,
    }
    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        db_user_id = access_ctx.system_user_id
    if db_user_id is None:
        fsm_storage.reset_state(user_id)
        await event.respond("⚠️ 当前 Telegram 账号还未绑定系统账号，请先发送 /start。")
        return

    try:
        created_task_id = await get_task_service().create_task(payload, int(db_user_id))
    except HTTPException as exc:
        await event.respond(f"❌ {exc.detail}")
        return

    fsm_storage.reset_state(user_id)
    await event.respond("✅ 手动任务已创建，底部按钮已同步。")
    await show_task_settings(event, user_id, created_task_id)


async def trigger_task_once_from_bot(event, user_id: int, task_id: str):
    """从 Bot 立即执行一次任务。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            await _answer_or_respond(event, "任务不存在或无权限", alert=True)
            return
        if not task.enabled:
            await _answer_or_respond(event, "任务已禁用，请启用后再执行", alert=True)
            return
        if task.account_id:
            await require_account_task_permission(
                task.account_id,
                session=session,
                action_text="手动执行任务",
            )
    await event.respond("⏳ 任务处理中，请稍候...")
    summary = (await execute_task_once(
        task_id,
        trigger_source=TaskTriggerSource.BOT_SHORTCUT.value,
        advance_schedule=False,
        respect_schedule_constraints=False,
    )).to_dict()
    status_map = {
        "success": "发送成功",
        "partial_success": "部分成功",
        "failed": "发送失败",
        "skipped": "已跳过",
    }
    success_targets = [str(item) for item in (summary.get("success_targets") or []) if str(item).strip()]
    failed_targets = [str(item) for item in (summary.get("failed_targets") or []) if str(item).strip()]
    target_preview = "、".join(_escape_markdown(item) for item in success_targets[:3])
    if not target_preview and failed_targets:
        target_preview = "、".join(_escape_markdown(item) for item in failed_targets[:3])
    if not target_preview:
        target_preview = f"{summary.get('total_targets') or 0} 个目标"
    if len(success_targets) > 3:
        target_preview += f" 等 {len(success_targets)} 个目标"

    message_preview = str(summary.get("message_preview") or "").strip()
    if not message_preview:
        message_preview = "无内容摘要"
    text = (
        "🚀 **任务执行完成**\n\n"
        f"任务：{_escape_markdown(summary['title'])}\n"
        f"状态：{status_map.get(summary.get('status'), summary.get('status') or '已处理')}\n"
        f"执行账号：{_escape_markdown(str(summary.get('account_display') or summary.get('account_id') or '默认账号'))}\n"
        f"发送目标：{target_preview}\n"
        f"发送内容：{_escape_markdown(_truncate_text(message_preview, 80))}\n"
        f"结果：成功 {summary['success_count']} / 失败 {summary['failed_count']}"
    )
    if failed_targets:
        failed_preview = "、".join(_escape_markdown(item) for item in failed_targets[:2])
        text += f"\n失败目标：{failed_preview}"
    if summary.get("error_summary"):
        text += f"\n失败摘要：{_escape_markdown(_truncate_text(summary['error_summary'], 80))}"
    await event.respond(text, parse_mode="markdown")


async def try_handle_manual_shortcut_message(event, user_id: int, text: str) -> bool:
    """Handle manual shortcut reply-keyboard text."""
    normalized = (text or "").strip()
    if not normalized:
        return False
    if normalized == "🏠 主菜单":
        from backend.bot.onboarding import get_onboarding_service
        await get_onboarding_service().show_home(event, user_id)
        return True

    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        db_user_id = access_ctx.system_user_id
        if db_user_id is None:
            return False
        stmt = (
            select(ScheduledMessageTask)
            .where(
                ScheduledMessageTask.user_id == db_user_id,
                ScheduledMessageTask.enabled == True,
                ScheduledMessageTask.trigger_mode == TaskTriggerMode.MANUAL_SHORTCUT.value,
                ScheduledMessageTask.shortcut_slot.is_not(None),
            )
            .order_by(ScheduledMessageTask.shortcut_slot.asc(), ScheduledMessageTask.created_at.asc())
        )
        if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED and access_ctx.scoped_account_id:
            stmt = stmt.where(ScheduledMessageTask.account_id == str(access_ctx.scoped_account_id))
        tasks = list((await session.execute(stmt)).scalars().all())

    matched_tasks = [
        task for task in tasks
        if _render_shortcut_label(task) == normalized
    ]
    if not matched_tasks:
        return False
    if len(matched_tasks) > 1:
        await event.respond("⚠️ 当前快捷任务名称冲突，请先在任务设置里修改快捷名称后再试。")
        return True

    try:
        await trigger_task_once_from_bot(event, user_id, matched_tasks[0].task_id)
    except HTTPException as exc:
        await _answer_or_respond(event, str(exc.detail or "执行失败，请稍后重试"), alert=True)
    except Exception as exc:
        logger.exception("手动任务执行失败: user_id={}, task_id={}, error={!r}", user_id, matched_tasks[0].task_id, exc)
        await event.respond("⚠️ 快捷任务执行失败，请稍后重试。")
    return True
