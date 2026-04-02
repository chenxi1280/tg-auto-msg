"""Persistent mapping between Telegram operator and system user/account context."""
from __future__ import annotations

from typing import Optional

from backend.database.schema.models import AppSetting

USER_LINK_KEY_PREFIX = "tg_user_link:"
ACTIVE_ACCOUNT_KEY_PREFIX = "tg_active_acc:"
USER_MODE_KEY_PREFIX = "tg_user_mode:"
SCOPED_ACCOUNT_KEY_PREFIX = "tg_user_scoped_acc:"

USER_MODE_OWNER = "owner"
USER_MODE_ACCOUNT_SCOPED = "account_scoped"


def _user_link_key(tg_user_id: int) -> str:
    return f"{USER_LINK_KEY_PREFIX}{int(tg_user_id)}"


def _active_account_key(tg_user_id: int, system_user_id: int) -> str:
    return f"{ACTIVE_ACCOUNT_KEY_PREFIX}{int(tg_user_id)}:{int(system_user_id)}"


def _user_mode_key(tg_user_id: int) -> str:
    return f"{USER_MODE_KEY_PREFIX}{int(tg_user_id)}"


def _scoped_account_key(tg_user_id: int, system_user_id: int) -> str:
    return f"{SCOPED_ACCOUNT_KEY_PREFIX}{int(tg_user_id)}:{int(system_user_id)}"


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


async def replace_linked_system_user_id(session, tg_user_id: int, system_user_id: int) -> Optional[int]:
    """Replace Telegram operator mapping and return previous system user id if changed."""
    previous_user_id = await get_linked_system_user_id(session, tg_user_id)
    await set_linked_system_user_id(session, tg_user_id, system_user_id)
    if previous_user_id is None or int(previous_user_id) == int(system_user_id):
        return None
    return int(previous_user_id)


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


async def get_user_mode(session, tg_user_id: int) -> str:
    """Read current bot access mode for Telegram operator."""
    row = await session.get(AppSetting, _user_mode_key(tg_user_id))
    if not row:
        return USER_MODE_OWNER
    value = (row.value or "").strip().lower()
    if value == USER_MODE_ACCOUNT_SCOPED:
        return USER_MODE_ACCOUNT_SCOPED
    return USER_MODE_OWNER


async def set_user_mode(session, tg_user_id: int, mode: str) -> None:
    """Persist bot access mode for Telegram operator."""
    normalized = USER_MODE_ACCOUNT_SCOPED if str(mode).strip().lower() == USER_MODE_ACCOUNT_SCOPED else USER_MODE_OWNER
    key = _user_mode_key(tg_user_id)
    row = await session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=normalized))
    else:
        row.value = normalized


async def clear_user_mode(session, tg_user_id: int) -> None:
    row = await session.get(AppSetting, _user_mode_key(tg_user_id))
    if row is not None:
        await session.delete(row)


async def get_scoped_account_id(session, tg_user_id: int, system_user_id: int) -> Optional[str]:
    """Read scoped account id when mode is account_scoped."""
    row = await session.get(AppSetting, _scoped_account_key(tg_user_id, system_user_id))
    if not row:
        return None
    value = (row.value or "").strip()
    return value or None


async def set_scoped_account_id(session, tg_user_id: int, system_user_id: int, account_id: str) -> None:
    """Persist scoped account id for account_scoped mode."""
    key = _scoped_account_key(tg_user_id, system_user_id)
    value = str(account_id).strip()
    row = await session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value


async def clear_scoped_account_id(session, tg_user_id: int, system_user_id: int) -> None:
    row = await session.get(AppSetting, _scoped_account_key(tg_user_id, system_user_id))
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
