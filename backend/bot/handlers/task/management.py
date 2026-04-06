"""Task management entry points for Telegram bot handlers."""
from __future__ import annotations

from datetime import datetime

from telethon import Button, events
from sqlalchemy import select

from backend.bot.handlers.core.helpers import (
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
from backend.bot.ui.keyboards import (
    get_confirm_delete_keyboard,
    get_task_list_keyboard,
    get_task_settings_keyboard,
)
from backend.bot.ui.messages import *
from backend.database.schema.models import Account, MediaType, Resource, ScheduledMessageTask
from backend.database.runtime.session import get_async_session

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
    return isinstance(event, events.CallbackQuery.Event)


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
            [Button.inline("➕ 新建任务", data="add_task")],
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
        text = TASK_LIST_HEADER + f"📊 共 {len(tasks)} 个任务\n\n下一步：请选择一个任务查看设置，或点击下方按钮新建任务。\n"
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
        interval=task.repeat_interval_min,
        account_display=_escape_markdown(account_display),
        target_display=_escape_markdown(target_display),
        time_range=_format_time_range(task.day_start_hour, task.day_end_hour),
        start_date=_format_run_bound(task.start_at),
        end_date=_format_run_bound(task.end_at),
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


async def create_new_task(event, user_id: int):
    """开始新建任务流程，选择完成前不落库。"""
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
            preferred_account_id=str(active_accounts[0]) if len(active_accounts) == 1 else None,
        )
        preferred_account_id = ref_state.get("active_account_id") or await _get_active_account_id(session, user_id, db_user_id)
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
            if preferred_account:
                selected_account_id = preferred_account.account_id
        if (
            access_ctx.mode == USER_MODE_ACCOUNT_SCOPED
            and access_ctx.scoped_account_id
            and selected_account_id is None
        ):
            await event.answer("当前账号不可用，请先重新绑定你的 Telegram 账号。", alert=True)
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
    )

    if selected_account_id:
        await start_select_task_targets(event, user_id, draft_task_id, page=0)
    else:
        await start_select_task_account(event, user_id, draft_task_id)


async def create_new_task_for_account(event, user_id: int, account_id: str):
    """从账号页开始新建任务流程，选择完成前不落库。"""
    from backend.bot.onboarding import get_onboarding_service
    from backend.bot.handlers.task.selector_context import set_selector_context

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
        if not account:
            await event.answer("账号不存在或不可用，请先检查账号状态。", alert=True)
            return
    draft_task_id = "__draft_new_task__"
    set_selector_context(
        user_id,
        task_id=draft_task_id,
        account_id=account_id,
        page=0,
        peer_filter="all",
        search="",
        draft_mode=True,
        draft_targets=[],
    )

    await start_select_task_targets(event, user_id, draft_task_id, page=0)


async def toggle_task(event, user_id: int, task_id: str):
    """切换任务启用状态。"""
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if task:
            task.enabled = not task.enabled
            if task.enabled and task.next_run_at is None:
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
            task.enabled = enabled
            if enabled and task.next_run_at is None:
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
