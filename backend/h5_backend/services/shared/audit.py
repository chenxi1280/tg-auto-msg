"""Shared audit logging utilities."""
from __future__ import annotations

from typing import Any, Dict, Optional

from backend.database.schema.models import AdminAuditLog


def mask_actor_name(actor: str) -> str:
    """Mask an actor string for PII protection (e.g. 'admin_name' -> 'admi***name')."""
    raw = (actor or "").strip()
    if not raw:
        return "admin"
    if "#" in raw:
        return raw
    if len(raw) <= 8:
        return "***"
    return f"{raw[:4]}***{raw[-4:]}"


def format_actor_label(username: str, account_id: int) -> str:
    """Format actor display label (e.g. 'admin#42')."""
    return f"{username}#{account_id}"


async def append_audit_log(
    session: Any,
    *,
    actor: str,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
    old_value: Optional[Dict[str, Any]] = None,
    new_value: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    developer_app_id: Optional[int] = None,
) -> None:
    """Append an audit log entry to the session (not yet committed)."""
    session.add(
        AdminAuditLog(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            old_value=old_value,
            new_value=new_value,
            ip_address=ip_address,
            developer_app_id=developer_app_id,
        )
    )
