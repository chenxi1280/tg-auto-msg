"""Persistent Bot deep-link media capture workflow."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import secrets

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import select, update
from telethon import Button

from backend.bot.account.reauth import is_reauth_required_account
from backend.bot.operator_link import get_linked_system_user_id
from backend.config.core.settings import settings
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account, ScheduledMessageTask, SystemSession
from backend.database.schema.task_media_models import TaskMediaCaptureSession
from backend.task_media.capture_authorization import (
    resolve_capture_actor as _resolve_capture_actor,
    validate_capture_target as _validate_capture_target,
)
from backend.task_media.contract import (
    CaptureStart,
    SavedMediaCopy,
    TaskMediaError,
    utc_now,
    validate_message_length,
)
from backend.task_media.mutation_service import fail_capture, update_task_from_capture
from backend.task_media.telegram_gateway import copy_bot_message_to_saved

MEDIA_CAPTURE_TTL_SECONDS = 600
ACTIVE_CAPTURE_STATES = ("waiting", "processing")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


async def _resolve_bot_username(session) -> str:
    username = str(settings.bot_username or "").strip().lstrip("@")
    if username:
        return username
    row = await session.get(SystemSession, "manager_bot")
    meta = row.session_meta if row and isinstance(row.session_meta, dict) else {}
    return str(meta.get("username") or "").strip().lstrip("@")


async def create_capture(
    *,
    task_id: str,
    user_id: int,
    expected_revision: int,
    actor_tg_user_id: int | None = None,
) -> CaptureStart:
    """Create one single-use persistent capture and return its token exactly once."""
    token = secrets.token_urlsafe(24)
    expires_at = utc_now() + timedelta(seconds=MEDIA_CAPTURE_TTL_SECONDS)
    async with get_async_session() as session:
        task = await _lock_capture_task(
            session=session, task_id=task_id, user_id=user_id
        )
        if not task:
            raise _error(404, "TASK_NOT_FOUND", "任务不存在")
        if int(task.revision) != int(expected_revision):
            raise _error(
                409, "TASK_REVISION_CONFLICT", "任务已被其他操作修改，请刷新后重试"
            )
        account = await session.get(Account, task.account_id)
        _validate_capture_target(task, account)
        capture_actor_id = await _resolve_capture_actor(
            session=session,
            user_id=user_id,
            actor_tg_user_id=actor_tg_user_id,
        )
        username = await _resolve_bot_username(session)
        if not username:
            raise _error(503, "MEDIA_CAPTURE_BOT_UNAVAILABLE", "系统 Bot 用户名未配置")

        await _replace_waiting_capture(session, task_id)
        capture = TaskMediaCaptureSession(
            token_hash=_token_hash(token),
            task_id=task_id,
            user_id=user_id,
            account_id=str(task.account_id),
            actor_tg_user_id=capture_actor_id,
            expected_task_revision=int(task.revision),
            state="waiting",
            expires_at=expires_at,
        )
        session.add(capture)
        await session.flush()
        capture_id = capture.capture_id

    logger.info(
        "task media capture created: capture_id={}, task_id={}, account_id={}, revision={}",
        capture_id,
        task_id,
        task.account_id,
        expected_revision,
    )
    return CaptureStart(
        capture_id=capture_id,
        state="waiting",
        expires_at=expires_at,
        bot_deep_link=f"https://t.me/{username}?start=media_{token}",
    )


async def _replace_waiting_capture(session, task_id: str) -> None:
    now = utc_now()
    active = (
        await session.scalars(
            select(TaskMediaCaptureSession)
            .where(
                TaskMediaCaptureSession.task_id == task_id,
                TaskMediaCaptureSession.state.in_(ACTIVE_CAPTURE_STATES),
            )
            .with_for_update()
        )
    ).all()
    for capture in active:
        if capture.expires_at <= now:
            capture.state = "expired"
            capture.error_code = "MEDIA_CAPTURE_EXPIRED"
            continue
        if capture.state == "processing":
            raise _error(
                409, "MEDIA_CAPTURE_PROCESSING", "已有媒体正在处理，请稍后检查结果"
            )
        capture.state = "cancelled"
        capture.error_code = "MEDIA_CAPTURE_REPLACED"


async def _lock_capture_task(*, session, task_id: str, user_id: int):
    return await session.scalar(
        select(ScheduledMessageTask)
        .where(
            ScheduledMessageTask.task_id == task_id,
            ScheduledMessageTask.user_id == user_id,
        )
        .with_for_update()
    )


async def get_capture_status(*, task_id: str, capture_id: str, user_id: int) -> dict:
    """Read durable capture status without exposing its token hash."""
    async with get_async_session() as session:
        capture = await session.scalar(
            select(TaskMediaCaptureSession).where(
                TaskMediaCaptureSession.capture_id == capture_id,
                TaskMediaCaptureSession.task_id == task_id,
                TaskMediaCaptureSession.user_id == user_id,
            )
        )
        if not capture:
            raise _error(404, "MEDIA_CAPTURE_NOT_FOUND", "媒体捕获会话不存在")
        if capture.state in ACTIVE_CAPTURE_STATES and capture.expires_at <= utc_now():
            capture.state = "expired"
            capture.error_code = "MEDIA_CAPTURE_EXPIRED"
        return _serialize_capture(capture)


def _serialize_capture(capture: TaskMediaCaptureSession) -> dict:
    return {
        "capture_id": capture.capture_id,
        "state": capture.state,
        "error_code": capture.error_code,
        "expires_at": capture.expires_at.isoformat(),
        "completed_revision": (
            int(capture.expected_task_revision) + 1
            if capture.state == "completed"
            else None
        ),
    }


async def activate_capture_from_start(event, token: str) -> bool:
    """Validate a deep-link token and send the anchored reply prompt."""
    async with get_async_session() as session:
        capture = await session.scalar(
            select(TaskMediaCaptureSession)
            .where(TaskMediaCaptureSession.token_hash == _token_hash(token))
            .with_for_update()
        )
        if not capture:
            await event.respond("❌ MEDIA_CAPTURE_NOT_FOUND：媒体设置链接无效。")
            return True
        actor_tg_user_id = int(event.sender_id)
        linked_user_id = await get_linked_system_user_id(session, actor_tg_user_id)
        error = _validate_activation(capture, actor_tg_user_id)
        if error is None:
            task = await session.get(ScheduledMessageTask, capture.task_id)
            account = await session.get(Account, capture.account_id)
            error = _validate_activation_context(
                capture, task, account, linked_user_id=linked_user_id
            )
            if error:
                capture.state = "failed"
                capture.error_code = error.code
        if error:
            await event.respond(f"❌ {error.code}：{error}")
            return True
        prompt = await event.respond(
            "请直接回复本条消息，并发送一张图片、一个视频或一个动图。\n"
            "普通文件、贴纸、语音和相册不支持。",
            buttons=Button.force_reply(single_use=True, selective=True),
        )
        capture.prompt_message_id = int(prompt.id)
    return True


def _validate_activation(capture: TaskMediaCaptureSession, actor_tg_user_id: int):
    if capture.actor_tg_user_id != actor_tg_user_id:
        return TaskMediaError(
            "MEDIA_CAPTURE_OPERATOR_MISMATCH", "请使用当前系统账号绑定的 Telegram 用户打开此链接"
        )
    if capture.expires_at <= utc_now():
        capture.state = "expired"
        capture.error_code = "MEDIA_CAPTURE_EXPIRED"
        return TaskMediaError("MEDIA_CAPTURE_EXPIRED", "媒体设置链接已过期")
    if capture.state != "waiting" or capture.prompt_message_id is not None:
        return TaskMediaError("MEDIA_CAPTURE_ALREADY_CONSUMED", "媒体设置链接已使用")
    return None


def _validate_activation_context(
    capture, task, account, *, linked_user_id: int | None
) -> TaskMediaError | None:
    if not task:
        return TaskMediaError(
            "TASK_REVISION_CONFLICT", "任务配置已经变化，请重新创建媒体设置链接"
        )
    if not account:
        return TaskMediaError("MEDIA_CAPTURE_ACCOUNT_UNAVAILABLE", "执行账号已不存在")
    if (
        not account.is_active
        or account.is_banned
        or is_reauth_required_account(account)
    ):
        return TaskMediaError(
            "MEDIA_CAPTURE_ACCOUNT_UNAVAILABLE", "执行账号当前不可用，请先恢复账号授权"
        )
    identity_matches = bool(
        account.user_id == capture.user_id and account.tg_user_id
    )
    if not identity_matches:
        return TaskMediaError(
            "MEDIA_CAPTURE_ACCOUNT_UNAVAILABLE", "执行账号绑定关系已经变化"
        )
    if linked_user_id != capture.user_id:
        return TaskMediaError(
            "MEDIA_CAPTURE_OPERATOR_MISMATCH", "当前 Telegram 用户与系统账号的绑定已经变化"
        )
    task_matches = (
        task.user_id == capture.user_id
        and task.account_id == capture.account_id
        and task.revision == capture.expected_task_revision
    )
    if not task_matches:
        return TaskMediaError(
            "TASK_REVISION_CONFLICT", "任务配置已经变化，请重新创建媒体设置链接"
        )
    return None


async def try_consume_capture_reply(event) -> bool:
    """Consume a reply to a persisted capture prompt before normal FSM routing."""
    reply_to = getattr(event.message, "reply_to_msg_id", None)
    if reply_to is None:
        if getattr(event.message, "media", None) and await _has_waiting_capture(
            int(event.sender_id)
        ):
            await event.respond(
                "❌ MEDIA_CAPTURE_REPLY_REQUIRED：请使用 Telegram 的回复功能，回复媒体设置提示消息。"
            )
            return True
        return False
    capture = await _claim_capture(
        int(event.sender_id), int(reply_to), int(event.message.id)
    )
    if capture is None:
        return False
    if isinstance(capture, TaskMediaError):
        await event.respond(f"❌ {capture.code}：{capture}")
        return True

    try:
        copied = await copy_bot_message_to_saved(
            account_id=capture.account_id,
            bot_message=event.message,
        )
        await _complete_capture(capture.capture_id, copied)
    except TaskMediaError as exc:
        await fail_capture(capture.capture_id, exc.code)
        logger.warning(
            "task media capture failed: capture_id={}, account_id={}, error_code={}",
            capture.capture_id,
            capture.account_id,
            exc.code,
        )
        await event.respond(f"❌ {exc.code}：{exc}")
        return True
    await event.respond("✅ 媒体已保存到执行账号的 Telegram 收藏夹，并已更新任务。")
    return True


async def _has_waiting_capture(actor_tg_user_id: int) -> bool:
    async with get_async_session() as session:
        capture_id = await session.scalar(
            select(TaskMediaCaptureSession.capture_id).where(
                TaskMediaCaptureSession.actor_tg_user_id == actor_tg_user_id,
                TaskMediaCaptureSession.state == "waiting",
                TaskMediaCaptureSession.prompt_message_id.is_not(None),
                TaskMediaCaptureSession.expires_at > utc_now(),
            )
        )
        return capture_id is not None


async def _claim_capture(
    actor_tg_user_id: int, prompt_message_id: int, source_message_id: int
):
    async with get_async_session() as session:
        task_id = await session.scalar(
            select(TaskMediaCaptureSession.task_id).where(
                TaskMediaCaptureSession.actor_tg_user_id == actor_tg_user_id,
                TaskMediaCaptureSession.prompt_message_id == prompt_message_id,
            )
        )
        if not task_id:
            return None
        task = await session.scalar(
            select(ScheduledMessageTask)
            .where(ScheduledMessageTask.task_id == task_id)
            .with_for_update()
        )
        capture = await session.scalar(
            select(TaskMediaCaptureSession)
            .where(
                TaskMediaCaptureSession.actor_tg_user_id == actor_tg_user_id,
                TaskMediaCaptureSession.prompt_message_id == prompt_message_id,
            )
            .with_for_update()
        )
        if not capture or not task:
            return None
        if capture.state != "waiting":
            return TaskMediaError(
                "MEDIA_CAPTURE_ALREADY_CONSUMED", "媒体捕获会话已处理"
            )
        if capture.expires_at <= utc_now():
            capture.state = "expired"
            capture.error_code = "MEDIA_CAPTURE_EXPIRED"
            return TaskMediaError("MEDIA_CAPTURE_EXPIRED", "媒体捕获会话已过期")
        account = await session.get(Account, capture.account_id)
        linked_user_id = await get_linked_system_user_id(session, actor_tg_user_id)
        context_error = _validate_activation_context(
            capture, task, account, linked_user_id=linked_user_id
        )
        if context_error:
            capture.state = "failed"
            capture.error_code = context_error.code
            return context_error
        capture.state = "processing"
        capture.source_message_id = source_message_id
        await session.flush()
        session.expunge(capture)
        return capture


async def _complete_capture(capture_id: str, copied: SavedMediaCopy) -> None:
    now = utc_now()
    failure: TaskMediaError | None = None
    async with get_async_session() as session:
        task_id = await session.scalar(
            select(TaskMediaCaptureSession.task_id).where(
                TaskMediaCaptureSession.capture_id == capture_id
            )
        )
        task = (
            await session.scalar(
                select(ScheduledMessageTask)
                .where(ScheduledMessageTask.task_id == task_id)
                .with_for_update()
            )
            if task_id
            else None
        )
        capture = await session.scalar(
            select(TaskMediaCaptureSession)
            .where(TaskMediaCaptureSession.capture_id == capture_id)
            .with_for_update()
        )
        if not capture:
            failure = TaskMediaError(
                "MEDIA_CAPTURE_ALREADY_CONSUMED", "媒体捕获会话不存在"
            )
        elif capture.state != "processing":
            _record_orphan_copy(capture, copied, now)
            failure = TaskMediaError(
                "MEDIA_CAPTURE_ALREADY_CONSUMED", "媒体捕获会话状态已变化"
            )
        elif capture.expires_at <= now:
            _fail_completed_copy(capture, copied, now, "MEDIA_CAPTURE_EXPIRED")
            failure = TaskMediaError("MEDIA_CAPTURE_EXPIRED", "媒体捕获会话已过期")
        else:
            failure = await _apply_completed_copy(
                session=session,
                capture=capture,
                copied=copied,
                now=now,
                task=task,
            )
    if failure:
        logger.warning(
            "task media capture completion rejected: capture_id={}, saved_message_id={}, error_code={}",
            capture_id,
            copied.saved_message_id,
            failure.code,
        )
        raise failure
    logger.info(
        "task media capture completed: capture_id={}, saved_message_id={}",
        capture_id,
        copied.saved_message_id,
    )


def _record_orphan_copy(capture, copied: SavedMediaCopy, now: datetime) -> None:
    if capture.saved_message_id is None:
        capture.saved_message_id = copied.saved_message_id
    capture.consumed_at = capture.consumed_at or now


def _fail_completed_copy(
    capture, copied: SavedMediaCopy, now: datetime, code: str
) -> None:
    capture.saved_message_id = copied.saved_message_id
    capture.state = "failed" if code != "MEDIA_CAPTURE_EXPIRED" else "expired"
    capture.error_code = code
    capture.consumed_at = now


async def _apply_completed_copy(
    *, session, capture, copied, now, task
) -> TaskMediaError | None:
    if not task or task.buttons:
        code = (
            "TASK_REVISION_CONFLICT"
            if not task
            else "TASK_BUTTONS_UNSUPPORTED_FOR_USER_ACCOUNT"
        )
        _fail_completed_copy(capture, copied, now, code)
        return TaskMediaError(code, "媒体未覆盖当前任务配置")
    try:
        validate_message_length(task.text, has_media=True)
    except TaskMediaError as exc:
        _fail_completed_copy(capture, copied, now, exc.code)
        return exc
    result = await update_task_from_capture(
        session=session, capture=capture, copied=copied, now=now
    )
    capture.saved_message_id = copied.saved_message_id
    capture.consumed_at = now
    if result.rowcount != 1:
        capture.state = "failed"
        capture.error_code = "TASK_REVISION_CONFLICT"
        return TaskMediaError("TASK_REVISION_CONFLICT", "媒体未覆盖当前任务配置")
    capture.state = "completed"
    return None
