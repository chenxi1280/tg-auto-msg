"""Telegram Bot task-creation content step."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from backend.bot.handlers.task.queries import (
    USER_MODE_ACCOUNT_SCOPED,
    resolve_actor_access_context,
)
from backend.bot.state.fsm import FSMState, fsm_storage
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import ScheduledMessageTask, TaskTriggerMode
from backend.h5_backend.services.licensing.service import require_account_task_permission
from backend.h5_backend.services.task.service import get_task_service
from backend.task_media.contract import TaskMediaError, validate_message_length

PENDING_TASK_CREATE_KEY = "pending_task_create"


def _http_detail_text(exc: HTTPException) -> str:
    if not isinstance(exc.detail, dict):
        return str(exc.detail)
    code = str(exc.detail.get("code") or "")
    message = str(exc.detail.get("message") or "任务创建失败")
    return f"{code}：{message}" if code else message


async def _resolve_creation_owner(event, user_id: int, account_id: str) -> int | None:
    async with get_async_session() as session:
        access_ctx = await resolve_actor_access_context(session, user_id)
        owner_user_id = access_ctx.system_user_id
        if owner_user_id is None:
            await event.respond("当前 Telegram 账号还未绑定系统账号，请先发送 /start。")
            return None
        if (
            access_ctx.mode == USER_MODE_ACCOUNT_SCOPED
            and access_ctx.scoped_account_id
            and account_id != str(access_ctx.scoped_account_id)
        ):
            await event.respond("受限模式下仅可为自己的账号创建任务。")
            return None
        try:
            await require_account_task_permission(
                account_id,
                session=session,
                action_text="创建自动发送任务",
            )
        except HTTPException as exc:
            await event.respond(_http_detail_text(exc))
            return None
    return int(owner_user_id)


async def _build_default_manual_label(owner_user_id: int) -> str:
    async with get_async_session() as session:
        rows = (
            await session.execute(
                select(ScheduledMessageTask.shortcut_label).where(
                    ScheduledMessageTask.user_id == owner_user_id,
                    ScheduledMessageTask.trigger_mode
                    == TaskTriggerMode.MANUAL_SHORTCUT.value,
                )
            )
        ).scalars().all()
    used = {str(label or "").strip().lower() for label in rows if label}
    for index in range(1, 4):
        label = "手动任务" if index == 1 else f"手动任务{index}"
        if label.lower() not in used:
            return label
    return "手动任务"


async def begin_task_text_creation(
    event,
    user_id: int,
    *,
    account_id: str,
    targets: list[dict[str, Any]],
    trigger_mode: str,
) -> None:
    """Persist the selected draft in FSM and request its required text."""
    owner_user_id = await _resolve_creation_owner(event, user_id, account_id)
    if owner_user_id is None:
        return
    shortcut_label = None
    if trigger_mode == TaskTriggerMode.MANUAL_SHORTCUT.value:
        shortcut_label = await _build_default_manual_label(owner_user_id)
    pending = {
        "account_id": account_id,
        "targets": [dict(target) for target in targets],
        "trigger_mode": trigger_mode,
        "shortcut_label": shortcut_label,
    }
    fsm_storage.set_state(user_id, FSMState.WAIT_TASK_CREATE_TEXT)
    fsm_storage.update_data(user_id, **{PENDING_TASK_CREATE_KEY: pending})
    await event.answer("✅ 已保存账号和目标，请继续填写文本")
    await event.respond(
        "📝 **设置任务文本**\n\n"
        f"已选择 {len(targets)} 个目标聊天。\n"
        "请输入任务要发送的文本内容（支持 HTML，最多 4096 字符）。\n\n"
        "发送 `/cancel` 可取消本次创建。\n"
        "下一步：文本校验通过后才会创建任务。",
        parse_mode="markdown",
    )


def _task_payload(pending: dict[str, Any], text: str) -> dict[str, Any]:
    shortcut_label = pending.get("shortcut_label")
    return {
        "account_id": str(pending["account_id"]),
        "target_peers": [dict(target) for target in pending["targets"]],
        "title": shortcut_label,
        "enabled": False,
        "trigger_mode": str(pending["trigger_mode"]),
        "shortcut_label": shortcut_label,
        "repeat_interval_min": 60,
        "text": text,
        "media_type": "none",
        "buttons": None,
        "delete_previous": False,
    }


async def _cancel_creation(event, user_id: int) -> None:
    fsm_storage.reset_state(user_id)
    from backend.bot.onboarding import get_onboarding_service

    await get_onboarding_service().show_home(event, user_id)


async def handle_task_creation_text_input(
    event,
    user_id: int,
    task_id: str | None,
    text: str,
) -> None:
    """Validate text, create the task, and open its settings page."""
    del task_id
    value = str(text or "")
    if value.strip().lower() == "/cancel":
        await _cancel_creation(event, user_id)
        return
    if not value.strip():
        await event.respond("❌ 文本内容不能为空，请重新输入。")
        return
    try:
        validate_message_length(value, has_media=False)
    except TaskMediaError as exc:
        await event.respond(f"❌ {exc.code}：{exc}")
        return
    pending = dict(
        fsm_storage.get_data(user_id).get(PENDING_TASK_CREATE_KEY) or {}
    )
    if not pending:
        fsm_storage.reset_state(user_id)
        await event.respond("⚠️ 当前任务创建流程已失效，请重新开始。")
        return
    owner_user_id = await _resolve_creation_owner(
        event,
        user_id,
        str(pending.get("account_id") or ""),
    )
    if owner_user_id is None:
        return
    try:
        created_task_id = await get_task_service().create_task(
            _task_payload(pending, value),
            owner_user_id,
        )
    except HTTPException as exc:
        await event.respond(f"❌ {_http_detail_text(exc)}")
        return
    fsm_storage.reset_state(user_id)
    await event.respond("✅ 文本已保存，任务创建成功。")
    from backend.bot.handlers.task.management import show_task_settings

    await show_task_settings(event, user_id, created_task_id)
