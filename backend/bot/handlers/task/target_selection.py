"""Task target/account selection flows for Telegram bot handlers."""
from __future__ import annotations

from typing import Optional
import uuid

from loguru import logger
from telethon import events
from sqlalchemy import select

from backend.bot.account.reauth import get_reauth_required_message, is_reauth_required_account
from backend.bot.state.fsm import FSMState, fsm_storage
from backend.bot.handlers.core.helpers import (
    apply_task_targets as _apply_task_targets,
    escape_markdown as _escape_markdown,
    filter_target_resources as _filter_target_resources,
    normalize_target_filter as _normalize_target_filter,
    normalize_task_targets as _normalize_task_targets,
    target_filter_label as _target_filter_label,
)
from backend.bot.handlers.task.selector_context import (
    clear_selector_context as _clear_selector_context,
    get_selector_context as _get_selector_context,
    set_selector_context as _set_selector_context,
)
from backend.bot.handlers.task.queries import (
    USER_MODE_ACCOUNT_SCOPED,
    get_user_task as _get_user_task,
    resolve_actor_access_context as _resolve_actor_access_context,
)
from backend.bot.handlers.task.selector_ui import (
    TARGET_PAGE_SIZE,
    build_account_picker_keyboard as _build_account_picker_keyboard,
    build_target_picker_keyboard as _build_target_picker_keyboard,
)
from backend.database.schema.models import Account, Resource, ScheduledMessageTask
from backend.database.runtime.session import get_async_session
from backend.h5_backend.services.licensing.service import require_account_task_permission
from fastapi import HTTPException


def _should_edit_event(event) -> bool:
    return isinstance(event, events.CallbackQuery.Event)


def _selector_expired_message(draft_mode: Optional[bool]) -> str:
    if draft_mode is True:
        return "当前创建流程已失效，请重新点击“新建任务”开始。"
    if draft_mode is False:
        return "当前选择流程已失效，请重新进入任务设置后再选择目标聊天。"
    return "当前选择流程已失效，请重新进入后再试。"


def _staged_targets(ctx: Optional[dict], task: Optional[ScheduledMessageTask]) -> list[dict]:
    if ctx is not None and "draft_targets" in ctx:
        return list(ctx.get("draft_targets") or [])
    return _normalize_task_targets(task)


async def start_select_task_account(event, user_id: int, task_id: str):
    ctx = _get_selector_context(user_id) or {}
    draft_mode = bool(ctx.get("draft_mode"))

    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        db_user_id = access_ctx.system_user_id
        if db_user_id is None:
            await event.answer("未找到系统用户，请先发送 /start 完成注册", alert=True)
            return

        stmt = (
            select(Account)
            .where(
                Account.user_id == db_user_id,
                Account.is_active == True,
            )
            .order_by(Account.created_at.desc())
        )
        if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED and access_ctx.scoped_account_id:
            stmt = stmt.where(Account.account_id == str(access_ctx.scoped_account_id))
        result = await session.execute(stmt)
        accounts = result.scalars().all()

        task = None if draft_mode else await _get_user_task(session, task_id, user_id)

    if not draft_mode and not task:
        logger.warning("edit selector context missing: user_id={}, task_id={}", user_id, task_id)
        await event.answer(_selector_expired_message(False), alert=True)
        return

    if not accounts:
        await event.answer("暂无可用账号，请先在 Bot 中登录 Telegram 账号", alert=True)
        return

    current_account_id = ctx.get("account_id") if ctx else None
    current_targets = _staged_targets(ctx, task)
    if not draft_mode:
        current_account_id = current_account_id or task.account_id

    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=current_account_id,
        page=0,
        peer_filter="all",
        search="",
        draft_mode=draft_mode,
        draft_targets=current_targets,
    )
    draft_tip = "任务会在选择目标聊天并点击完成后才真正创建。\n\n" if draft_mode else "\n"
    text = (
        "👥 **选择执行账号**\n\n"
        "选择后将进入目标聊天多选。若切换账号，原目标聊天将被清空。\n"
        f"{draft_tip}"
        "下一步：请选择一个用于执行任务的 Telegram 账号。"
    )
    keyboard = _build_account_picker_keyboard(
        task_id=task_id,
        accounts=accounts,
        current_account_id=current_account_id,
        back_callback="back_to_list" if draft_mode else None,
    )
    if _should_edit_event(event):
        await event.edit(text, buttons=keyboard, parse_mode="markdown")
    else:
        await event.respond(text, buttons=keyboard, parse_mode="markdown")


async def start_select_task_targets(event, user_id: int, task_id: str, page: int = 0):
    ctx = _get_selector_context(user_id) or {}
    draft_mode = bool(ctx.get("draft_mode"))
    peer_filter = _normalize_target_filter(ctx.get("peer_filter"))
    search_query = str(ctx.get("search") or "").strip()

    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        task = None if draft_mode else await _get_user_task(session, task_id, user_id)
        if not draft_mode and not task:
            logger.warning("edit selector context missing: user_id={}, task_id={}", user_id, task_id)
            await event.answer(_selector_expired_message(False), alert=True)
            return

        account_id = str(ctx.get("account_id") or "") or ("" if task is None else str(task.account_id or ""))
        if (
            access_ctx.mode == USER_MODE_ACCOUNT_SCOPED
            and access_ctx.scoped_account_id
            and account_id
            and str(account_id) != str(access_ctx.scoped_account_id)
        ):
            await event.answer("受限模式下仅可操作自己的账号目标。", alert=True)
            return
        if not account_id:
            await event.answer("请先选择执行账号", alert=True)
            await start_select_task_account(event, user_id, task_id)
            return

        resource_result = await session.execute(
            select(Resource)
            .where(
                Resource.account_id == account_id,
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

        selected_targets = _staged_targets(ctx, task)
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
        back_callback="back_to_list" if draft_mode else None,
        done_label=f"✅ 创建任务 ({len(selected_keys)})" if draft_mode else None,
    )
    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=account_id,
        page=page,
        peer_filter=peer_filter,
        search=search_query,
        draft_mode=draft_mode,
        draft_targets=selected_targets,
    )

    next_step_text = "下一步：勾选目标后点击下方「✅ 创建任务」。" if draft_mode else "下一步：勾选目标后点击下方「✅ 完成」。"
    text = (
        "📋 **选择目标聊天（支持多选）**\n\n"
        f"已选择: {len(selected_keys)} 个\n"
        f"类型筛选: {_target_filter_label(peer_filter)}\n"
        f"关键词: {_escape_markdown(search_query or '无')}\n"
        f"第 {page + 1}/{total_pages} 页，每页 {TARGET_PAGE_SIZE} 条\n\n"
        f"{next_step_text}"
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
        logger.warning("draft mode lost during callback: action=pick_acc, user_id={}", user_id)
        await event.answer(_selector_expired_message(None), alert=True)
        return

    task_id = str(ctx["task_id"])
    draft_mode = bool(ctx.get("draft_mode"))
    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        db_user_id = access_ctx.system_user_id
        task = None if draft_mode else await _get_user_task(session, task_id, user_id)
        if (not draft_mode and not task) or db_user_id is None:
            logger.warning(
                "{} selector context missing: action=pick_acc, user_id={}, task_id={}",
                "draft" if draft_mode else "edit",
                user_id,
                task_id,
            )
            await event.answer(
                _selector_expired_message(True if draft_mode else False),
                alert=True,
            )
            return

        if (
            access_ctx.mode == USER_MODE_ACCOUNT_SCOPED
            and access_ctx.scoped_account_id
            and str(account_id) != str(access_ctx.scoped_account_id)
        ):
            await event.answer("受限模式下仅可选择自己的账号。", alert=True)
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
        if is_reauth_required_account(account):
            await event.answer(get_reauth_required_message(), alert=True)
            return

        previous_account_id = str(ctx.get("account_id") or "") if ctx else ""
        account_changed = previous_account_id != account_id

        await event.answer("✅ 已选择执行账号")
    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=account_id,
        page=0,
        peer_filter="all",
        search="",
        draft_mode=draft_mode,
        draft_targets=[] if account_changed else list(ctx.get("draft_targets") or []),
    )
    await start_select_task_targets(event, user_id, task_id, page=0)


async def _handle_pick_resource(event, user_id: int, resource_id: int):
    ctx = _get_selector_context(user_id)
    if not ctx:
        logger.warning("draft mode lost during callback: action=pick_res, user_id={}", user_id)
        await event.answer(_selector_expired_message(None), alert=True)
        return

    task_id = str(ctx["task_id"])
    page = int(ctx.get("page") or 0)
    draft_mode = bool(ctx.get("draft_mode"))

    async with get_async_session() as session:
        task = None if draft_mode else await _get_user_task(session, task_id, user_id)
        account_id = str(ctx.get("account_id") or "") or ("" if task is None else str(task.account_id or ""))
        if not draft_mode and not task:
            logger.warning("edit selector context missing: action=pick_res, user_id={}, task_id={}", user_id, task_id)
            await event.answer(_selector_expired_message(False), alert=True)
            return
        if not account_id:
            await event.answer("请先选择执行账号", alert=True)
            return

        resource_result = await session.execute(
            select(Resource).where(
                Resource.resource_id == resource_id,
                Resource.account_id == account_id,
                Resource.is_active == True,
            )
        )
        resource = resource_result.scalar_one_or_none()
        if not resource:
            await event.answer("目标聊天不存在或已失效", alert=True)
            return

        targets = _staged_targets(ctx, task)
        key = (str(resource.peer_type), int(resource.peer_id))
        existing_keys = {(str(t["peer_type"]), int(t["peer_id"])) for t in targets}

        if key in existing_keys:
            targets = [
                t for t in targets
                if (str(t["peer_type"]), int(t["peer_id"])) != key
            ]
            await event.answer("已取消选择该目标")
        else:
            targets.append(
                {
                    "peer_id": int(resource.peer_id),
                    "peer_type": str(resource.peer_type),
                    "access_hash": resource.access_hash,
                }
            )
            await event.answer("✅ 已加入目标")

    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=account_id,
        page=page,
        peer_filter=str(ctx.get("peer_filter") or "all"),
        search=str(ctx.get("search") or ""),
        draft_mode=draft_mode,
        draft_targets=targets,
    )

    await start_select_task_targets(event, user_id, task_id, page=page)


async def _handle_pick_clear(event, user_id: int):
    ctx = _get_selector_context(user_id)
    if not ctx:
        logger.warning("draft mode lost during callback: action=pick_clear, user_id={}", user_id)
        await event.answer(_selector_expired_message(None), alert=True)
        return

    task_id = str(ctx["task_id"])
    page = int(ctx.get("page") or 0)
    draft_mode = bool(ctx.get("draft_mode"))

    async with get_async_session() as session:
        task = None if draft_mode else await _get_user_task(session, task_id, user_id)
        if not draft_mode and not task:
            logger.warning("edit selector context missing: action=pick_clear, user_id={}, task_id={}", user_id, task_id)
            await event.answer(_selector_expired_message(False), alert=True)
            return
    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=str(ctx.get("account_id") or ""),
        page=page,
        peer_filter=str(ctx.get("peer_filter") or "all"),
        search=str(ctx.get("search") or ""),
        draft_mode=draft_mode,
        draft_targets=[],
    )

    await event.answer("✅ 已清空目标")
    await start_select_task_targets(event, user_id, task_id, page=page)


async def _handle_pick_done(event, user_id: int):
    ctx = _get_selector_context(user_id)
    if not ctx:
        logger.warning("draft mode lost during callback: action=pick_done, user_id={}", user_id)
        await event.answer(_selector_expired_message(None), alert=True)
        return

    task_id = str(ctx["task_id"])
    draft_mode = bool(ctx.get("draft_mode"))
    async with get_async_session() as session:
        task = None if draft_mode else await _get_user_task(session, task_id, user_id)
        if not draft_mode and not task:
            logger.warning("edit selector context missing: action=pick_done, user_id={}, task_id={}", user_id, task_id)
            await event.answer(_selector_expired_message(False), alert=True)
            return
        targets = _staged_targets(ctx, task)

    if not targets:
        await event.answer("请至少选择一个目标聊天", alert=True)
        return

    _clear_selector_context(user_id)
    if draft_mode:
        account_id = str(ctx.get("account_id") or "")
        if not account_id:
            await event.answer("请先选择执行账号", alert=True)
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
            try:
                await require_account_task_permission(
                    account_id,
                    session=session,
                    action_text="创建自动发送任务",
                )
            except HTTPException as exc:
                await event.answer(str(exc.detail), alert=True)
                return

            task = ScheduledMessageTask(
                task_id=str(uuid.uuid4()),
                user_id=db_user_id,
                account_id=account_id,
                chat_id=0,
                title="未命名任务",
                repeat_interval_min=60,
                day_start_hour=0,
                day_end_hour=24,
                enabled=False,
                next_run_at=None,
            )
            _apply_task_targets(task, targets)
            session.add(task)
            await session.commit()
            created_task_id = task.task_id

        await event.answer(f"✅ 已创建任务并保存 {len(targets)} 个目标")
        from backend.bot.handlers.task.management import show_task_settings
        await show_task_settings(event, user_id, created_task_id)
        return

    account_id = str(ctx.get("account_id") or "")
    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            logger.warning("edit selector context missing: action=pick_done_commit, user_id={}, task_id={}", user_id, task_id)
            await event.answer(_selector_expired_message(False), alert=True)
            return
        if (
            access_ctx.mode == USER_MODE_ACCOUNT_SCOPED
            and access_ctx.scoped_account_id
            and str(account_id or task.account_id or "") != str(access_ctx.scoped_account_id)
        ):
            await event.answer("受限模式下仅可编辑自己的账号任务。", alert=True)
            return
        try:
            await require_account_task_permission(
                account_id or task.account_id,
                session=session,
                action_text="保存自动发送任务",
            )
        except HTTPException as exc:
            await event.answer(str(exc.detail), alert=True)
            return
        task.account_id = account_id or task.account_id
        _apply_task_targets(task, targets)
        await session.commit()

    await event.answer(f"✅ 已保存 {len(targets)} 个目标")

    from backend.bot.handlers.task.management import show_task_settings
    await show_task_settings(event, user_id, task_id)


async def handle_target_search_input(event, user_id: int, text: str):
    """处理目标聊天搜索输入。"""
    ctx = _get_selector_context(user_id)
    if not ctx:
        fsm_storage.set_state(user_id, FSMState.NONE)
        logger.warning("selector context missing during search input: user_id={}", user_id)
        await event.respond("⚠️ 当前选择流程已失效。\n下一步：请重新进入任务设置或重新点击“新建任务”。")
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
            draft_mode=bool(ctx.get("draft_mode")),
            draft_targets=list(ctx.get("draft_targets") or []),
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
        await event.respond("⚠️ 搜索关键词过长，请控制在 32 个字符以内。")
        return

    fsm_storage.set_state(user_id, FSMState.NONE)
    _set_selector_context(
        user_id,
        task_id=str(ctx["task_id"]),
        account_id=ctx.get("account_id"),
        page=0,
        peer_filter=str(ctx.get("peer_filter") or "all"),
        search=keyword,
        draft_mode=bool(ctx.get("draft_mode")),
        draft_targets=list(ctx.get("draft_targets") or []),
    )
    await start_select_task_targets(event, user_id, str(ctx["task_id"]), page=0)
