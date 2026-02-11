"""Task target/account selection flows for Telegram bot handlers."""
from __future__ import annotations

from typing import Optional

from loguru import logger
from telethon import events
from sqlalchemy import select

from backend.bot.fsm import FSMState, fsm_storage
from backend.bot.handlers.helpers import (
    apply_task_targets as _apply_task_targets,
    escape_markdown as _escape_markdown,
    filter_target_resources as _filter_target_resources,
    normalize_target_filter as _normalize_target_filter,
    normalize_task_targets as _normalize_task_targets,
    target_filter_label as _target_filter_label,
)
from backend.bot.handlers.selector_context import (
    clear_selector_context as _clear_selector_context,
    get_selector_context as _get_selector_context,
    set_selector_context as _set_selector_context,
)
from backend.bot.handlers.task_queries import (
    get_user_task as _get_user_task,
    resolve_db_user_id as _resolve_db_user_id,
)
from backend.bot.handlers.task_selector_ui import (
    TARGET_PAGE_SIZE,
    build_account_picker_keyboard as _build_account_picker_keyboard,
    build_target_picker_keyboard as _build_target_picker_keyboard,
)
from backend.database.models import Account, Resource
from backend.database.session import get_async_session


def _should_edit_event(event) -> bool:
    return isinstance(event, events.CallbackQuery.Event)


async def start_select_task_account(event, user_id: int, task_id: str):
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        db_user_id = await _resolve_db_user_id(session, user_id)
        if db_user_id is None:
            await event.answer("未找到系统用户，请先绑定", alert=True)
            return

        result = await session.execute(
            select(Account)
            .where(
                Account.user_id == db_user_id,
                Account.is_active == True,
            )
            .order_by(Account.created_at.desc())
        )
        accounts = result.scalars().all()

    if not task:
        await event.answer("任务不存在", alert=True)
        return

    if not accounts:
        await event.answer("暂无可用账号，请先在 H5 绑定并启用账号", alert=True)
        return

    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=task.account_id,
        page=0,
        peer_filter="all",
        search="",
    )
    text = (
        "👤 **请选择执行账号**\n\n"
        "选择后将进入目标聊天多选。若切换账号，原目标聊天将被清空。"
    )
    keyboard = _build_account_picker_keyboard(
        task_id=task_id,
        accounts=accounts,
        current_account_id=task.account_id,
    )
    if _should_edit_event(event):
        await event.edit(text, buttons=keyboard, parse_mode="markdown")
    else:
        await event.respond(text, buttons=keyboard, parse_mode="markdown")


async def start_select_task_targets(event, user_id: int, task_id: str, page: int = 0):
    ctx = _get_selector_context(user_id) or {}
    peer_filter = _normalize_target_filter(ctx.get("peer_filter"))
    search_query = str(ctx.get("search") or "").strip()

    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            await event.answer("任务不存在", alert=True)
            return

        if not task.account_id:
            await event.answer("请先选择执行账号", alert=True)
            await start_select_task_account(event, user_id, task_id)
            return

        resource_result = await session.execute(
            select(Resource)
            .where(
                Resource.account_id == task.account_id,
                Resource.is_active == True,
            )
            .order_by(Resource.title.asc().nullslast(), Resource.resource_id.asc())
        )
        all_resources = resource_result.scalars().all()
        resources = _filter_target_resources(
            all_resources,
            peer_filter=peer_filter,
            search_query=search_query,
        )

        selected_targets = _normalize_task_targets(task)
        selected_keys = {
            (str(item["peer_type"]), int(item["peer_id"]))
            for item in selected_targets
        }

    keyboard, page, total_pages = _build_target_picker_keyboard(
        task_id=task_id,
        resources=resources,
        selected_keys=selected_keys,
        page=page,
        peer_filter=peer_filter,
        search_query=search_query,
    )
    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=task.account_id,
        page=page,
        peer_filter=peer_filter,
        search=search_query,
    )

    text = (
        "🎯 **选择目标聊天（支持多选）**\n\n"
        f"已选择: {len(selected_keys)} 个\n"
        f"类型筛选: {_target_filter_label(peer_filter)}\n"
        f"关键词: {_escape_markdown(search_query or '无')}\n"
        f"第 {page + 1}/{total_pages} 页，每页 {TARGET_PAGE_SIZE} 条"
    )
    if not resources:
        text += "\n\n⚠️ 当前筛选条件下没有可选聊天，请调整筛选或搜索词。"
    if _should_edit_event(event):
        await event.edit(text, buttons=keyboard, parse_mode="markdown")
    else:
        await event.respond(text, buttons=keyboard, parse_mode="markdown")


async def _handle_pick_account(event, user_id: int, account_id: str):
    ctx = _get_selector_context(user_id)
    if not ctx:
        await event.answer("会话已过期，请重新进入任务设置", alert=True)
        return

    task_id = str(ctx["task_id"])
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        db_user_id = await _resolve_db_user_id(session, user_id)
        if not task or db_user_id is None:
            await event.answer("任务不存在或无权限", alert=True)
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
            await event.answer("账号不存在或不可用", alert=True)
            return

        account_changed = task.account_id != account_id
        task.account_id = account_id
        if account_changed:
            _apply_task_targets(task, [])
        await session.commit()

    await event.answer("已选择执行账号")
    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=account_id,
        page=0,
        peer_filter="all",
        search="",
    )
    await start_select_task_targets(event, user_id, task_id, page=0)


async def _handle_pick_resource(event, user_id: int, resource_id: int):
    ctx = _get_selector_context(user_id)
    if not ctx:
        await event.answer("会话已过期，请重新进入任务设置", alert=True)
        return

    task_id = str(ctx["task_id"])
    page = int(ctx.get("page") or 0)

    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task or not task.account_id:
            await event.answer("请先选择执行账号", alert=True)
            return

        resource_result = await session.execute(
            select(Resource).where(
                Resource.resource_id == resource_id,
                Resource.account_id == task.account_id,
                Resource.is_active == True,
            )
        )
        resource = resource_result.scalar_one_or_none()
        if not resource:
            await event.answer("目标聊天不存在或已失效", alert=True)
            return

        targets = _normalize_task_targets(task)
        key = (str(resource.peer_type), int(resource.peer_id))
        existing_keys = {(str(t["peer_type"]), int(t["peer_id"])) for t in targets}

        if key in existing_keys:
            targets = [
                t for t in targets
                if (str(t["peer_type"]), int(t["peer_id"])) != key
            ]
            await event.answer("已取消选择")
        else:
            targets.append(
                {
                    "peer_id": int(resource.peer_id),
                    "peer_type": str(resource.peer_type),
                    "access_hash": resource.access_hash,
                }
            )
            await event.answer("已加入目标")

        _apply_task_targets(task, targets)
        await session.commit()

    await start_select_task_targets(event, user_id, task_id, page=page)


async def _handle_pick_clear(event, user_id: int):
    ctx = _get_selector_context(user_id)
    if not ctx:
        await event.answer("会话已过期，请重新进入任务设置", alert=True)
        return

    task_id = str(ctx["task_id"])
    page = int(ctx.get("page") or 0)

    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            await event.answer("任务不存在", alert=True)
            return
        _apply_task_targets(task, [])
        await session.commit()

    await event.answer("已清空目标")
    await start_select_task_targets(event, user_id, task_id, page=page)


async def _handle_pick_done(event, user_id: int):
    ctx = _get_selector_context(user_id)
    if not ctx:
        await event.answer("会话已过期，请重新进入任务设置", alert=True)
        return

    task_id = str(ctx["task_id"])
    async with get_async_session() as session:
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            await event.answer("任务不存在", alert=True)
            return
        targets = _normalize_task_targets(task)

    if not targets:
        await event.answer("请至少选择一个目标聊天", alert=True)
        return

    _clear_selector_context(user_id)
    await event.answer(f"已保存 {len(targets)} 个目标")

    from backend.bot.handlers.task_management import show_task_settings
    await show_task_settings(event, user_id, task_id)


async def handle_target_search_input(event, user_id: int, text: str):
    """处理目标聊天搜索输入。"""
    ctx = _get_selector_context(user_id)
    if not ctx:
        fsm_storage.set_state(user_id, FSMState.NONE)
        await event.respond("⚠️ 选择会话已过期，请重新进入任务设置")
        return

    keyword = (text or "").strip()
    logger.info(
        f"目标搜索输入: user_id={user_id}, state={fsm_storage.get_state(user_id)}, raw={keyword!r}"
    )
    if keyword.lower() in {"cancel", "/cancel"}:
        fsm_storage.set_state(user_id, FSMState.NONE)
        _set_selector_context(
            user_id,
            task_id=str(ctx["task_id"]),
            account_id=ctx.get("account_id"),
            page=int(ctx.get("page") or 0),
            peer_filter=str(ctx.get("peer_filter") or "all"),
            search=str(ctx.get("search") or ""),
            expect_search=False,
        )
        await start_select_task_targets(
            event,
            user_id,
            str(ctx["task_id"]),
            page=int(ctx.get("page") or 0),
        )
        return

    if keyword.startswith("/"):
        keyword = keyword.lstrip("/")

    if keyword.lower() in {"clear", "清空"}:
        keyword = ""

    if len(keyword) > 32:
        await event.respond("关键词过长，请控制在 32 个字符以内")
        return

    fsm_storage.set_state(user_id, FSMState.NONE)
    _set_selector_context(
        user_id,
        task_id=str(ctx["task_id"]),
        account_id=ctx.get("account_id"),
        page=0,
        peer_filter=str(ctx.get("peer_filter") or "all"),
        search=keyword,
    )
    await start_select_task_targets(event, user_id, str(ctx["task_id"]), page=0)
