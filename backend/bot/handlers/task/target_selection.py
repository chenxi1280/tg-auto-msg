"""Task target/account selection flows for Telegram bot handlers."""
from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from sqlalchemy import select

from backend.bot.account.reauth import get_reauth_required_message, is_reauth_required_account
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
from backend.database.schema.models import Account, Resource, ScheduledMessageTask
from backend.database.runtime.session import get_async_session
from backend.h5_backend.services.licensing.service import require_account_task_permission
from backend.h5_backend.services.task.service import get_task_service
from fastapi import HTTPException
from backend.database.schema.models import TaskTriggerMode
from backend.bot.handlers.task.target_search import handle_target_search_input
from backend.bot.handlers.task.target_views import (
    selector_expired_message as _selector_expired_message,
    staged_targets as _staged_targets,
    start_select_task_account,
    start_select_task_targets,
)


@dataclass(frozen=True)
class AccountPick:
    task_id: str
    draft_mode: bool
    account_changed: bool


@dataclass(frozen=True)
class ResourcePick:
    task_id: str
    account_id: str
    page: int
    draft_mode: bool
    targets: list[dict]
    added: bool


@dataclass(frozen=True)
class TaskUpdate:
    owner_user_id: int
    account_id: str
    expected_revision: int


async def _validate_account_pick(event, user_id: int, account_id: str, ctx: dict) -> AccountPick | None:
    task_id = str(ctx["task_id"])
    draft_mode = bool(ctx.get("draft_mode"))
    async with get_async_session() as session:
        access = await _resolve_actor_access_context(session, user_id)
        task = None if draft_mode else await _get_user_task(session, task_id, user_id)
        if (not draft_mode and not task) or access.system_user_id is None:
            logger.warning("{} selector context missing: action=pick_acc, user_id={}, task_id={}",
                           "draft" if draft_mode else "edit", user_id, task_id)
            await event.answer(_selector_expired_message(draft_mode), alert=True)
            return None
        scoped_id = str(access.scoped_account_id or "")
        if access.mode == USER_MODE_ACCOUNT_SCOPED and scoped_id and account_id != scoped_id:
            await event.answer("受限模式下仅可选择自己的账号。", alert=True)
            return None
        result = await session.execute(select(Account).where(
            Account.account_id == account_id,
            Account.user_id == access.system_user_id,
            Account.is_active == True,
        ))
        account = result.scalar_one_or_none()
        if not account:
            await event.answer("账号不存在或不可用", alert=True)
            return None
        if is_reauth_required_account(account):
            await event.answer(get_reauth_required_message(), alert=True)
            return None
    return AccountPick(task_id, draft_mode, str(ctx.get("account_id") or "") != account_id)


async def _handle_pick_account(event, user_id: int, account_id: str):
    ctx = _get_selector_context(user_id)
    if not ctx:
        logger.warning("draft mode lost during callback: action=pick_acc, user_id={}", user_id)
        await event.answer(_selector_expired_message(None), alert=True)
        return

    pick = await _validate_account_pick(event, user_id, account_id, ctx)
    if pick is None:
        return
    await event.answer("✅ 已选择执行账号")
    _set_selector_context(
        user_id,
        task_id=pick.task_id,
        account_id=account_id,
        page=0,
        peer_filter="all",
        search="",
        draft_mode=pick.draft_mode,
        draft_targets=[] if pick.account_changed else list(ctx.get("draft_targets") or []),
        draft_trigger_mode=ctx.get("draft_trigger_mode"),
    )
    await start_select_task_targets(event, user_id, pick.task_id, page=0)


async def _load_resource_pick(event, user_id: int, resource_id: int, ctx: dict) -> ResourcePick | None:
    task_id = str(ctx["task_id"])
    draft_mode = bool(ctx.get("draft_mode"))
    async with get_async_session() as session:
        task = None if draft_mode else await _get_user_task(session, task_id, user_id)
        if not draft_mode and not task:
            logger.warning("edit selector context missing: action=pick_res, user_id={}, task_id={}",
                           user_id, task_id)
            await event.answer(_selector_expired_message(False), alert=True)
            return None
        account_id = str(ctx.get("account_id") or "") or ("" if task is None else str(task.account_id or ""))
        if not account_id:
            await event.answer("请先选择执行账号", alert=True)
            return None
        result = await session.execute(select(Resource).where(
            Resource.resource_id == resource_id,
            Resource.account_id == account_id,
            Resource.is_active == True,
        ))
        resource = result.scalar_one_or_none()
        if not resource:
            await event.answer("目标聊天不存在或已失效", alert=True)
            return None
        targets, added = _toggle_resource(_staged_targets(ctx, task), resource)
    return ResourcePick(task_id, account_id, int(ctx.get("page") or 0), draft_mode, targets, added)


def _toggle_resource(targets: list[dict], resource: Resource) -> tuple[list[dict], bool]:
    key = (str(resource.peer_type), int(resource.peer_id))
    existing = {(str(item["peer_type"]), int(item["peer_id"])) for item in targets}
    if key in existing:
        remaining = [item for item in targets if (str(item["peer_type"]), int(item["peer_id"])) != key]
        return remaining, False
    updated = [*targets, {
        "peer_id": int(resource.peer_id),
        "peer_type": str(resource.peer_type),
        "access_hash": resource.access_hash,
    }]
    return updated, True


async def _handle_pick_resource(event, user_id: int, resource_id: int):
    ctx = _get_selector_context(user_id)
    if not ctx:
        logger.warning("draft mode lost during callback: action=pick_res, user_id={}", user_id)
        await event.answer(_selector_expired_message(None), alert=True)
        return

    pick = await _load_resource_pick(event, user_id, resource_id, ctx)
    if pick is None:
        return
    await event.answer("✅ 已加入目标" if pick.added else "已取消选择该目标")
    _set_selector_context(
        user_id,
        task_id=pick.task_id,
        account_id=pick.account_id,
        page=pick.page,
        peer_filter=str(ctx.get("peer_filter") or "all"),
        search=str(ctx.get("search") or ""),
        draft_mode=pick.draft_mode,
        draft_targets=pick.targets,
        draft_trigger_mode=ctx.get("draft_trigger_mode"),
    )

    await start_select_task_targets(event, user_id, pick.task_id, page=pick.page)


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
        draft_trigger_mode=ctx.get("draft_trigger_mode"),
    )

    await event.answer("✅ 已清空目标")
    await start_select_task_targets(event, user_id, task_id, page=page)


async def _begin_draft_task_creation(event, user_id: int, ctx: dict, targets: list[dict]):
    from backend.bot.handlers.task.creation import begin_task_text_creation

    account_id = str(ctx.get("account_id") or "")
    if not account_id:
        await event.answer("请先选择执行账号", alert=True)
        return
    trigger_mode = str(ctx.get("draft_trigger_mode") or TaskTriggerMode.SCHEDULED.value)
    await begin_task_text_creation(
        event,
        user_id,
        account_id=account_id,
        targets=targets,
        trigger_mode=trigger_mode,
    )


async def _load_task_update(event, user_id: int, task_id: str, account_id: str) -> TaskUpdate | None:
    async with get_async_session() as session:
        access = await _resolve_actor_access_context(session, user_id)
        task = await _get_user_task(session, task_id, user_id)
        if not task:
            logger.warning("edit selector context missing: action=pick_done_commit, user_id={}, task_id={}",
                           user_id, task_id)
            await event.answer(_selector_expired_message(False), alert=True)
            return None
        selected_account_id = account_id or str(task.account_id or "")
        scoped_id = str(access.scoped_account_id or "")
        if access.mode == USER_MODE_ACCOUNT_SCOPED and scoped_id and selected_account_id != scoped_id:
            await event.answer("受限模式下仅可编辑自己的账号任务。", alert=True)
            return None
        try:
            await require_account_task_permission(
                selected_account_id, session=session, action_text="保存自动发送任务",
            )
        except HTTPException as exc:
            await event.answer(str(exc.detail), alert=True)
            return None
        return TaskUpdate(int(task.user_id), selected_account_id, int(task.revision))


async def _commit_task_targets(event, task_id: str, targets: list[dict], update: TaskUpdate) -> bool:
    try:
        await get_task_service().update_task(
            task_id,
            {
                "account_id": update.account_id,
                "target_peers": targets,
                "expected_revision": update.expected_revision,
            },
            update.owner_user_id,
        )
    except HTTPException as exc:
        detail = exc.detail.get("message") if isinstance(exc.detail, dict) else str(exc.detail)
        await event.answer(detail, alert=True)
        return False
    return True


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
        await _begin_draft_task_creation(event, user_id, ctx, targets)
        return

    account_id = str(ctx.get("account_id") or "")
    update = await _load_task_update(event, user_id, task_id, account_id)
    if update is None or not await _commit_task_targets(event, task_id, targets, update):
        return

    await event.answer(f"✅ 已保存 {len(targets)} 个目标")

    from backend.bot.handlers.task.management import show_task_settings
    await show_task_settings(event, user_id, task_id)
