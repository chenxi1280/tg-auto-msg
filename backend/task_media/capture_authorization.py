"""Authorization checks for task-media capture creation."""

from __future__ import annotations

from fastapi import HTTPException

from backend.bot.account.reauth import is_reauth_required_account
from backend.bot.operator_link import (
    get_linked_system_user_id,
    load_latest_linked_tg_user_ids,
)
from backend.database.schema.models import Account, ScheduledMessageTask
from backend.task_media.contract import TaskMediaError, validate_message_length


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


async def resolve_capture_actor(
    *, session, user_id: int, actor_tg_user_id: int | None
) -> int:
    """Resolve the linked Bot operator without coupling it to the execution account."""
    if actor_tg_user_id is not None:
        linked_user_id = await get_linked_system_user_id(session, actor_tg_user_id)
        if linked_user_id == int(user_id):
            return int(actor_tg_user_id)
        raise _error(
            403,
            "MEDIA_CAPTURE_OPERATOR_UNAUTHORIZED",
            "当前 Telegram 用户未绑定该系统账号",
        )
    linked_actors = await load_latest_linked_tg_user_ids(session)
    linked_actor_id = linked_actors.get(int(user_id))
    if linked_actor_id is None:
        raise _error(
            409,
            "MEDIA_CAPTURE_OPERATOR_UNAVAILABLE",
            "系统账号尚未绑定 Telegram 操作用户",
        )
    return int(linked_actor_id)


def validate_capture_target(
    task: ScheduledMessageTask, account: Account | None
) -> None:
    """Validate task content and the independent execution account."""
    if task.buttons:
        raise _error(
            400,
            "TASK_BUTTONS_UNSUPPORTED_FOR_USER_ACCOUNT",
            "请先删除任务消息按钮，再设置媒体",
        )
    try:
        validate_message_length(task.text, has_media=True)
    except TaskMediaError as exc:
        raise _error(400, exc.code, str(exc)) from exc
    if not account or not account.tg_user_id or account.user_id != task.user_id:
        raise _error(
            400,
            "MEDIA_CAPTURE_ACCOUNT_UNAVAILABLE",
            "执行账号尚未正确绑定 Telegram UID",
        )
    if not account.is_active or account.is_banned or is_reauth_required_account(account):
        raise _error(
            409,
            "MEDIA_CAPTURE_ACCOUNT_UNAVAILABLE",
            "执行账号当前不可用，请先恢复账号授权",
        )
