"""Persistent mapping between Telegram operator and system user/account context."""
from __future__ import annotations

from typing import Iterable, Optional

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


async def normalize_operator_account_refs(
    session,
    tg_user_id: int,
    system_user_id: int,
    *,
    valid_account_ids: Iterable[str],
    preferred_account_id: Optional[str] = None,
) -> dict:
    """Repair stale active/scoped account refs for a Telegram operator."""
    normalized_ids: list[str] = []
    seen: set[str] = set()
    for account_id in valid_account_ids:
        value = str(account_id or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized_ids.append(value)

    valid_set = set(normalized_ids)
    preferred = str(preferred_account_id).strip() if preferred_account_id else None
    if preferred and preferred not in valid_set:
        preferred = None

    fallback_account_id = preferred or (normalized_ids[0] if len(normalized_ids) == 1 else None)
    active_before = await get_active_account_id(session, tg_user_id, system_user_id)
    active_after = active_before if active_before and active_before in valid_set else None
    active_changed = False
    if active_after != active_before:
        active_changed = True
    if active_after is None and fallback_account_id:
        await set_active_account_id(session, tg_user_id, system_user_id, fallback_account_id)
        active_after = fallback_account_id
        active_changed = True
    elif active_after is None and active_before is not None:
        await clear_active_account_id(session, tg_user_id, system_user_id)

    mode_before = await get_user_mode(session, tg_user_id)
    mode_after = mode_before
    scoped_before = await get_scoped_account_id(session, tg_user_id, system_user_id)
    scoped_after = scoped_before if scoped_before and scoped_before in valid_set else None
    scoped_changed = scoped_after != scoped_before

    if mode_before == USER_MODE_ACCOUNT_SCOPED:
        desired_scoped = scoped_after or fallback_account_id
        if desired_scoped:
            if desired_scoped != scoped_before:
                await set_scoped_account_id(session, tg_user_id, system_user_id, desired_scoped)
                scoped_changed = True
            scoped_after = desired_scoped
        else:
            if scoped_before is not None:
                await clear_scoped_account_id(session, tg_user_id, system_user_id)
                scoped_changed = True
            await set_user_mode(session, tg_user_id, USER_MODE_OWNER)
            mode_after = USER_MODE_OWNER
            scoped_after = None
    elif scoped_before is not None and scoped_before not in valid_set:
        await clear_scoped_account_id(session, tg_user_id, system_user_id)
        scoped_after = None
        scoped_changed = True

    return {
        "active_account_id": active_after,
        "scoped_account_id": scoped_after,
        "mode": mode_after,
        "active_changed": bool(active_changed),
        "scoped_changed": bool(scoped_changed),
        "mode_changed": mode_after != mode_before,
    }


async def cleanup_active_account_refs(session, account_id: str) -> None:
    """Delete active-account settings that point to deleted account."""
    await session.execute(
        AppSetting.__table__.delete().where(
            AppSetting.key.like(f"{ACTIVE_ACCOUNT_KEY_PREFIX}%"),
            AppSetting.value == account_id,
        )
    )


async def cleanup_scoped_account_refs(session, account_id: str) -> None:
    """Delete scoped-account settings that point to deleted account."""
    await session.execute(
        AppSetting.__table__.delete().where(
            AppSetting.key.like(f"{SCOPED_ACCOUNT_KEY_PREFIX}%"),
            AppSetting.value == account_id,
        )
    )
