"""Persistent mapping between Telegram operator and system user/account context."""
from __future__ import annotations

from typing import Optional

from backend.database.schema.models import AppSetting

USER_LINK_KEY_PREFIX = "tg_user_link:"
ACTIVE_ACCOUNT_KEY_PREFIX = "tg_active_acc:"


def _user_link_key(tg_user_id: int) -> str:
    return f"{USER_LINK_KEY_PREFIX}{int(tg_user_id)}"


def _active_account_key(tg_user_id: int, system_user_id: int) -> str:
    return f"{ACTIVE_ACCOUNT_KEY_PREFIX}{int(tg_user_id)}:{int(system_user_id)}"


async def get_linked_system_user_id(session, tg_user_id: int) -> Optional[int]:
    """Read mapped system user id for Telegram operator."""
    key = _user_link_key(tg_user_id)
    row = await session.get(AppSetting, key)
    if not row:
        return None
    try:
        return int((row.value or "").strip())
    except Exception:
        return None


async def set_linked_system_user_id(session, tg_user_id: int, system_user_id: int) -> None:
    """Persist mapping Telegram operator -> system user id."""
    key = _user_link_key(tg_user_id)
    value = str(int(system_user_id))
    row = await session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value


async def get_active_account_id(session, tg_user_id: int, system_user_id: int) -> Optional[str]:
    """Read per-operator active account id."""
    key = _active_account_key(tg_user_id, system_user_id)
    row = await session.get(AppSetting, key)
    if not row:
        return None
    value = (row.value or "").strip()
    return value or None


async def set_active_account_id(session, tg_user_id: int, system_user_id: int, account_id: str) -> None:
    """Persist per-operator active account id."""
    key = _active_account_key(tg_user_id, system_user_id)
    value = str(account_id).strip()
    row = await session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value


async def clear_active_account_id(session, tg_user_id: int, system_user_id: int) -> None:
    """Clear per-operator active account id."""
    key = _active_account_key(tg_user_id, system_user_id)
    row = await session.get(AppSetting, key)
    if row is not None:
        await session.delete(row)


async def cleanup_active_account_refs(session, account_id: str) -> None:
    """Delete active-account settings that point to deleted account."""
    await session.execute(
        AppSetting.__table__.delete().where(
            AppSetting.key.like(f"{ACTIVE_ACCOUNT_KEY_PREFIX}%"),
            AppSetting.value == account_id,
        )
    )
