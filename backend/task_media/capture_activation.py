"""Authorize one media capture and anchor its Telegram reply prompt."""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from telethon import Button

from backend.bot.account.reauth import is_reauth_required_account
from backend.bot.operator_link import get_linked_system_user_id
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account, ScheduledMessageTask
from backend.database.schema.task_media_models import TaskMediaCaptureSession
from backend.task_media.capture_authorization import UNCLAIMED_CAPTURE_ACTOR_ID
from backend.task_media.contract import TaskMediaError, utc_now


def hash_capture_token(token: str) -> str:
    """Hash an opaque deep-link token before persistence or lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def activate_capture_from_start(event, token: str) -> bool:
    """Activate a capture reached through an H5 Telegram deep link."""
    return await _activate_capture(event, token_hash=hash_capture_token(token))


async def activate_capture_for_actor(event, capture_id: str) -> bool:
    """Activate a Bot-created capture directly, without parsing a deep link."""
    return await _activate_capture(event, capture_id=capture_id)


async def _activate_capture(
    event, *, token_hash: str | None = None, capture_id: str | None = None
) -> bool:
    async with get_async_session() as session:
        capture = await _load_capture(
            session,
            token_hash=token_hash,
            capture_id=capture_id,
        )
        if not capture:
            await event.respond("❌ MEDIA_CAPTURE_NOT_FOUND：媒体设置入口无效。")
            return True
        error = await _activation_error(session, capture, int(event.sender_id))
        if error:
            await event.respond(f"❌ {error.code}：{error}")
            return True
        prompt = await event.respond(
            "请直接回复本条消息，并发送一张图片、一个视频或一个动图。\n"
            "系统会自动识别媒体类型；普通文件、贴纸、语音和相册不支持。",
            buttons=Button.force_reply(single_use=True, selective=True),
        )
        capture.prompt_message_id = int(prompt.id)
    return True


async def _load_capture(
    session, *, token_hash: str | None, capture_id: str | None
):
    if bool(token_hash) == bool(capture_id):
        return None
    criterion = (
        TaskMediaCaptureSession.token_hash == token_hash
        if token_hash
        else TaskMediaCaptureSession.capture_id == capture_id
    )
    return await session.scalar(
        select(TaskMediaCaptureSession).where(criterion).with_for_update()
    )


async def _activation_error(session, capture, actor_tg_user_id: int):
    linked_user_id = await get_linked_system_user_id(session, actor_tg_user_id)
    error = validate_activation(
        capture,
        actor_tg_user_id,
        linked_user_id=linked_user_id,
    )
    if error:
        return error
    task = await session.get(ScheduledMessageTask, capture.task_id)
    account = await session.get(Account, capture.account_id)
    error = validate_activation_context(
        capture,
        task,
        account,
        linked_user_id=linked_user_id,
    )
    if error:
        capture.state = "failed"
        capture.error_code = error.code
    return error


def validate_activation(
    capture: TaskMediaCaptureSession,
    actor_tg_user_id: int,
    *,
    linked_user_id: int | None,
):
    if linked_user_id != capture.user_id:
        return TaskMediaError(
            "MEDIA_CAPTURE_OPERATOR_MISMATCH",
            "请使用当前系统账号绑定的 Telegram 用户打开此入口",
        )
    if capture.actor_tg_user_id not in (
        UNCLAIMED_CAPTURE_ACTOR_ID,
        actor_tg_user_id,
    ):
        return TaskMediaError(
            "MEDIA_CAPTURE_OPERATOR_MISMATCH",
            "该媒体设置入口已由另一个 Telegram 用户使用",
        )
    if capture.expires_at <= utc_now():
        capture.state = "expired"
        capture.error_code = "MEDIA_CAPTURE_EXPIRED"
        return TaskMediaError("MEDIA_CAPTURE_EXPIRED", "媒体设置入口已过期")
    if capture.state != "waiting" or capture.prompt_message_id is not None:
        return TaskMediaError("MEDIA_CAPTURE_ALREADY_CONSUMED", "媒体设置入口已使用")
    capture.actor_tg_user_id = actor_tg_user_id
    return None


def validate_activation_context(
    capture, task, account, *, linked_user_id: int | None
) -> TaskMediaError | None:
    if not task:
        return TaskMediaError(
            "TASK_REVISION_CONFLICT", "任务配置已经变化，请重新打开媒体设置"
        )
    if not account:
        return TaskMediaError("MEDIA_CAPTURE_ACCOUNT_UNAVAILABLE", "执行账号已不存在")
    if not account.is_active or account.is_banned or is_reauth_required_account(account):
        return TaskMediaError(
            "MEDIA_CAPTURE_ACCOUNT_UNAVAILABLE", "执行账号当前不可用，请先恢复账号授权"
        )
    if account.user_id != capture.user_id or not account.tg_user_id:
        return TaskMediaError(
            "MEDIA_CAPTURE_ACCOUNT_UNAVAILABLE", "执行账号绑定关系已经变化"
        )
    if linked_user_id != capture.user_id:
        return TaskMediaError(
            "MEDIA_CAPTURE_OPERATOR_MISMATCH", "Telegram 用户与系统账号的绑定已经变化"
        )
    task_matches = (
        task.user_id == capture.user_id
        and task.account_id == capture.account_id
        and task.revision == capture.expected_task_revision
    )
    if not task_matches:
        return TaskMediaError(
            "TASK_REVISION_CONFLICT", "任务配置已经变化，请重新打开媒体设置"
        )
    return None
