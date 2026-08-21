"""Read-only Telegram operator to system-user link queries."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from backend.database.schema.models import AppSetting

USER_LINK_KEY_PREFIX = "tg_user_link:"


def user_link_key(tg_user_id: int) -> str:
    return f"{USER_LINK_KEY_PREFIX}{int(tg_user_id)}"


async def get_linked_system_user_id(session, tg_user_id: int) -> Optional[int]:
    """Read mapped system user id for a Telegram operator."""
    row = await session.get(AppSetting, user_link_key(tg_user_id))
    if not row:
        return None
    try:
        return int((row.value or "").strip())
    except (TypeError, ValueError):
        return None


async def load_latest_linked_tg_user_ids(session) -> dict[int, int]:
    """Load the latest Telegram operator binding per system user."""
    rows = (
        await session.execute(
            select(
                AppSetting.key,
                AppSetting.value,
                AppSetting.updated_at,
                AppSetting.created_at,
            )
            .where(AppSetting.key.like(f"{USER_LINK_KEY_PREFIX}%"))
            .order_by(
                AppSetting.updated_at.desc(),
                AppSetting.created_at.desc(),
                AppSetting.key.desc(),
            )
        )
    ).all()
    user_links: dict[int, int] = {}
    for key, value, _updated_at, _created_at in rows:
        try:
            tg_user_id = int(str(key).split(USER_LINK_KEY_PREFIX, 1)[1])
            user_id = int(str(value).strip())
        except (IndexError, TypeError, ValueError):
            continue
        user_links.setdefault(user_id, tg_user_id)
    return user_links
