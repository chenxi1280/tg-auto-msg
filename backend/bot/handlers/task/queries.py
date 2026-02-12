"""Query helpers for bot handler task/account ownership checks."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from backend.database.schema.models import Account, ScheduledMessageTask, User
from backend.bot.handlers.core.user_link import get_linked_system_user_id as _get_linked_system_user_id


async def resolve_db_user_id(session, actor_user_id: int) -> Optional[int]:
    """
    Map Telegram sender ID to system user ID.

    Priority:
    1. Explicit link via AppSetting (`tg_user_link:*`)
    2. Bound account owner via `accounts.tg_user_id`
    3. Legacy compatibility where sender ID is system user ID
    """
    linked_user_id = await _get_linked_system_user_id(session, actor_user_id)
    if linked_user_id is not None:
        return int(linked_user_id)

    account_result = await session.execute(
        select(Account.user_id)
        .where(Account.tg_user_id == actor_user_id)
        .order_by(Account.created_at.desc())
        .limit(1)
    )
    mapped_user_id = account_result.scalar_one_or_none()
    if mapped_user_id is not None:
        return int(mapped_user_id)

    legacy_user = await session.execute(select(User.id).where(User.id == actor_user_id))
    legacy_user_id = legacy_user.scalar_one_or_none()
    if legacy_user_id is not None:
        return int(legacy_user_id)

    return None


async def get_user_task(session, task_id: str, user_id: int) -> Optional[ScheduledMessageTask]:
    """Get a task owned by current actor's mapped system user."""
    db_user_id = await resolve_db_user_id(session, user_id)
    if db_user_id is None:
        return None
    result = await session.execute(
        select(ScheduledMessageTask).where(
            ScheduledMessageTask.task_id == task_id,
            ScheduledMessageTask.user_id == db_user_id,
        )
    )
    return result.scalar_one_or_none()
