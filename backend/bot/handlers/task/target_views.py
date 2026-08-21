"""Account and target picker views used by Telegram task flows."""
from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from sqlalchemy import select

from backend.bot.handlers.core.helpers import (
    escape_markdown,
    filter_target_resources,
    normalize_target_filter,
    normalize_task_targets,
    should_edit_event,
    target_filter_label,
)
from backend.bot.handlers.task.queries import (
    USER_MODE_ACCOUNT_SCOPED,
    get_user_task,
    resolve_actor_access_context,
)
from backend.bot.handlers.task.selector_context import get_selector_context, set_selector_context
from backend.bot.handlers.task.selector_ui import (
    TARGET_PAGE_SIZE,
    build_account_picker_keyboard,
    build_target_picker_keyboard,
)
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account, Resource, ScheduledMessageTask


@dataclass(frozen=True)
class TargetPickerData:
    account_id: str
    resources: list[Resource]
    targets: list[dict]


def selector_expired_message(draft_mode: bool | None) -> str:
    if draft_mode is True:
        return "当前创建流程已失效，请重新点击任务创建入口开始。"
    if draft_mode is False:
        return "当前选择流程已失效，请重新进入任务设置后再选择目标聊天。"
    return "当前选择流程已失效，请重新进入后再试。"


def staged_targets(ctx: dict | None, task: ScheduledMessageTask | None) -> list[dict]:
    if ctx is not None and "draft_targets" in ctx:
        return list(ctx.get("draft_targets") or [])
    return normalize_task_targets(task)


async def _load_account_picker(user_id: int, task_id: str, draft_mode: bool):
    async with get_async_session() as session:
        access = await resolve_actor_access_context(session, user_id)
        if access.system_user_id is None:
            return None, [], None
        stmt = select(Account).where(
            Account.user_id == access.system_user_id,
            Account.is_active == True,
        ).order_by(Account.created_at.desc())
        if access.mode == USER_MODE_ACCOUNT_SCOPED and access.scoped_account_id:
            stmt = stmt.where(Account.account_id == str(access.scoped_account_id))
        accounts = (await session.execute(stmt)).scalars().all()
        task = None if draft_mode else await get_user_task(session, task_id, user_id)
    return access, accounts, task


async def start_select_task_account(event, user_id: int, task_id: str):
    ctx = get_selector_context(user_id) or {}
    draft_mode = bool(ctx.get("draft_mode"))
    access, accounts, task = await _load_account_picker(user_id, task_id, draft_mode)
    if access is None:
        await event.answer("未找到系统用户，请先发送 /start 完成注册", alert=True)
        return
    if not draft_mode and not task:
        logger.warning("edit selector context missing: user_id={}, task_id={}", user_id, task_id)
        await event.answer(selector_expired_message(False), alert=True)
        return
    if not accounts:
        await event.answer("暂无可用账号，请先在 Bot 中登录 Telegram 账号", alert=True)
        return
    current_account_id = ctx.get("account_id") or (None if task is None else task.account_id)
    targets = staged_targets(ctx, task)
    set_selector_context(
        user_id, task_id=task_id, account_id=current_account_id, page=0,
        peer_filter="all", search="", draft_mode=draft_mode,
        draft_targets=targets, draft_trigger_mode=ctx.get("draft_trigger_mode"),
    )
    tip = "任务会在选择目标聊天并填写文本后才真正创建。\n\n" if draft_mode else "\n"
    text = "👥 **选择执行账号**\n\n选择后将进入目标聊天多选。若切换账号，原目标聊天将被清空。\n" + tip
    text += "下一步：请选择一个用于执行任务的 Telegram 账号。"
    keyboard = build_account_picker_keyboard(
        task_id=task_id, accounts=accounts, current_account_id=current_account_id,
        back_callback="back_to_list" if draft_mode else None,
    )
    sender = event.edit if should_edit_event(event) else event.respond
    await sender(text, buttons=keyboard, parse_mode="markdown")


async def _load_target_picker(user_id: int, task_id: str, ctx: dict) -> TargetPickerData | None:
    draft_mode = bool(ctx.get("draft_mode"))
    peer_filter = normalize_target_filter(ctx.get("peer_filter"))
    search_query = str(ctx.get("search") or "").strip()
    async with get_async_session() as session:
        access = await resolve_actor_access_context(session, user_id)
        task = None if draft_mode else await get_user_task(session, task_id, user_id)
        if not draft_mode and not task:
            return None
        account_id = str(ctx.get("account_id") or "") or ("" if task is None else str(task.account_id or ""))
        scoped_id = str(access.scoped_account_id or "")
        if access.mode == USER_MODE_ACCOUNT_SCOPED and scoped_id and account_id != scoped_id:
            return TargetPickerData("__forbidden__", [], [])
        if not account_id:
            return TargetPickerData("", [], [])
        result = await session.execute(
            select(Resource).where(
                Resource.account_id == account_id, Resource.is_active == True,
            ).order_by(Resource.title.asc().nullslast(), Resource.resource_id.asc())
        )
        resources = filter_target_resources(
            result.scalars().all(), peer_filter=peer_filter, search_query=search_query,
        )
        return TargetPickerData(account_id, resources, staged_targets(ctx, task))


def _target_picker_text(selected_count: int, page: int, pages: int, ctx: dict, has_resources: bool) -> str:
    peer_filter = normalize_target_filter(ctx.get("peer_filter"))
    search_query = str(ctx.get("search") or "").strip()
    next_step = (
        "下一步：勾选目标后点击下方「➡️ 下一步：填写文本」。"
        if ctx.get("draft_mode") else "下一步：勾选目标后点击下方「✅ 完成」。"
    )
    text = (
        "📋 **选择目标聊天（支持多选）**\n\n"
        f"已选择: {selected_count} 个\n类型筛选: {target_filter_label(peer_filter)}\n"
        f"关键词: {escape_markdown(search_query or '无')}\n"
        f"第 {page + 1}/{pages} 页，每页 {TARGET_PAGE_SIZE} 条\n\n{next_step}"
    )
    if not has_resources:
        text += "\n\n⚠️ 当前筛选条件下没有可选聊天，请调整筛选或搜索词。"
    return text


async def start_select_task_targets(event, user_id: int, task_id: str, page: int = 0):
    ctx = get_selector_context(user_id) or {}
    data = await _load_target_picker(user_id, task_id, ctx)
    if data is None:
        logger.warning("edit selector context missing: user_id={}, task_id={}", user_id, task_id)
        await event.answer(selector_expired_message(False), alert=True)
        return
    if data.account_id == "__forbidden__":
        await event.answer("受限模式下仅可操作自己的账号目标。", alert=True)
        return
    if not data.account_id:
        await event.answer("请先选择执行账号", alert=True)
        await start_select_task_account(event, user_id, task_id)
        return
    selected_keys = {(str(item["peer_type"]), int(item["peer_id"])) for item in data.targets}
    peer_filter = normalize_target_filter(ctx.get("peer_filter"))
    search_query = str(ctx.get("search") or "").strip()
    keyboard, page, pages = build_target_picker_keyboard(
        task_id=task_id, resources=data.resources, selected_keys=selected_keys, page=page,
        peer_filter=peer_filter, search_query=search_query,
        back_callback="back_to_list" if ctx.get("draft_mode") else None,
        done_label=f"➡️ 下一步：填写文本 ({len(selected_keys)})" if ctx.get("draft_mode") else None,
    )
    set_selector_context(
        user_id, task_id=task_id, account_id=data.account_id, page=page,
        peer_filter=peer_filter, search=search_query, draft_mode=bool(ctx.get("draft_mode")),
        draft_targets=data.targets, draft_trigger_mode=ctx.get("draft_trigger_mode"),
    )
    text = _target_picker_text(len(selected_keys), page, pages, ctx, bool(data.resources))
    sender = event.edit if should_edit_event(event) else event.respond
    await sender(text, buttons=keyboard, parse_mode="markdown")
