"""Query helpers for bot handler task/account ownership checks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select

from backend.h5_backend.services.licensing.service import list_user_authorizations
from backend.database.schema.models import Account, ScheduledMessageTask, User
from backend.bot.handlers.core.user_link import (
    USER_MODE_ACCOUNT_SCOPED,
    USER_MODE_OWNER,
    get_linked_system_user_id as _get_linked_system_user_id,
    normalize_operator_account_refs as _normalize_operator_account_refs,
    get_scoped_account_id as _get_scoped_account_id,
    get_user_mode as _get_user_mode,
)

PG_INT32_MAX = 2_147_483_647


@dataclass(frozen=True)
class ActorAccessContext:
    system_user_id: Optional[int]
    mode: str
    scoped_account_id: Optional[str]


async def resolve_db_user_id(session, actor_user_id: int) -> Optional[int]:
    """
    Map Telegram sender ID to system user ID.

    Priority:
    1. Explicit link via AppSetting (`tg_user_link:*`)
    2. Legacy compatibility where sender ID is system user ID
    """
    linked_user_id = await _get_linked_system_user_id(session, actor_user_id)
    if linked_user_id is not None:
        return int(linked_user_id)

    # Legacy fallback only makes sense for very old data where Telegram sender id
    # happened to equal local system user id. Guard int32 range to avoid asyncpg
    # bind errors for normal Telegram IDs.
    if 0 < int(actor_user_id) <= PG_INT32_MAX:
        legacy_user = await session.execute(select(User.id).where(User.id == int(actor_user_id)))
        legacy_user_id = legacy_user.scalar_one_or_none()
        if legacy_user_id is not None:
            return int(legacy_user_id)

    return None


async def resolve_actor_access_context(session, actor_user_id: int) -> ActorAccessContext:
    """Resolve actor mapping + access mode."""
    db_user_id = await resolve_db_user_id(session, actor_user_id)
    if db_user_id is None:
        return ActorAccessContext(system_user_id=None, mode=USER_MODE_OWNER, scoped_account_id=None)

    await list_user_authorizations(int(db_user_id), session=session)

    active_account_ids = (
        await session.execute(
            select(Account.account_id)
            .where(
                Account.user_id == int(db_user_id),
                Account.is_active.is_(True),
            )
            .order_by(Account.updated_at.desc(), Account.last_used_at.desc(), Account.created_at.desc())
        )
    ).scalars().all()
    preferred_account_id = str(active_account_ids[0]) if len(active_account_ids) == 1 else None
    ref_state = await _normalize_operator_account_refs(
        session,
        actor_user_id,
        db_user_id,
        valid_account_ids=[str(item) for item in active_account_ids],
        preferred_account_id=preferred_account_id,
    )

    mode = str(ref_state.get("mode") or await _get_user_mode(session, actor_user_id))
    if mode != USER_MODE_ACCOUNT_SCOPED:
        return ActorAccessContext(system_user_id=db_user_id, mode=USER_MODE_OWNER, scoped_account_id=None)

    scoped_account_id = str(ref_state.get("scoped_account_id") or "") or await _get_scoped_account_id(session, actor_user_id, db_user_id)
    if not scoped_account_id:
        return ActorAccessContext(system_user_id=db_user_id, mode=USER_MODE_OWNER, scoped_account_id=None)

    owned = await session.execute(
        select(Account.account_id).where(
            Account.account_id == str(scoped_account_id),
            Account.user_id == int(db_user_id),
        )
    )
    if owned.scalar_one_or_none() is None:
        return ActorAccessContext(system_user_id=db_user_id, mode=USER_MODE_OWNER, scoped_account_id=None)
    return ActorAccessContext(system_user_id=db_user_id, mode=USER_MODE_ACCOUNT_SCOPED, scoped_account_id=str(scoped_account_id))


async def get_user_task(session, task_id: str, user_id: int) -> Optional[ScheduledMessageTask]:
    """Get a task owned by current actor's mapped system user."""
    access_ctx = await resolve_actor_access_context(session, user_id)
    if access_ctx.system_user_id is None:
        return None
    result = await session.execute(
        select(ScheduledMessageTask).where(
            ScheduledMessageTask.task_id == task_id,
            ScheduledMessageTask.user_id == access_ctx.system_user_id,
        )
    )
    task = result.scalar_one_or_none()
    if task is None:
        return None
    if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED and str(task.account_id or "") != str(access_ctx.scoped_account_id or ""):
        return None
    return task
