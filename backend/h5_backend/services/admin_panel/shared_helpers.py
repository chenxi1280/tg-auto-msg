"""Shared helper functions and serializers for the admin panel domain."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from fastapi import HTTPException
from sqlalchemy import select

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    ActivationCard,
    AdminAccount,
    AdminAccountRole,
    AdminAccountTgBinding,
    AdminAuditLog,
    AgentCreditLimit,
    AgentFundLedger,
    CardBatch,
    PricingPlan,
)
from backend.h5_backend.services.admin_rbac.service import get_admin_rbac_service
from backend.h5_backend.services.shared.card_utils import generate_card_code
from backend.h5_backend.services.shared.pagination import normalize_page
from backend.h5_backend.services.shared.serializers import serialize_pricing_plan

# ──────────────────────────── Constants ────────────────────────────

ROLE_SUPER_ADMIN = "super_admin"
ROLE_MASTER_AGENT = "master_agent"
ROLE_SUB_AGENT = "sub_agent"
ACCOUNT_TYPE_STAFF = "staff"
ACCOUNT_TYPE_AGENT = "agent"
BUSINESS_IDENTITY_MASTER_AGENT = "master_agent"
BUSINESS_IDENTITY_SUB_AGENT = "sub_agent"


# ──────────────────────────── Account type / identity helpers ────────────────────────────


def _account_type(account: AdminAccount) -> str:
    value = str(getattr(account, "account_type", "") or "").strip().lower()
    if value in {ACCOUNT_TYPE_STAFF, ACCOUNT_TYPE_AGENT}:
        return value
    return (
        ACCOUNT_TYPE_AGENT
        if str(getattr(account, "role_code", "") or "").strip().lower() in {ROLE_MASTER_AGENT, ROLE_SUB_AGENT}
        else ACCOUNT_TYPE_STAFF
    )


def _business_identity(account: AdminAccount) -> Optional[str]:
    value = str(getattr(account, "business_identity", "") or "").strip().lower()
    if value in {BUSINESS_IDENTITY_MASTER_AGENT, BUSINESS_IDENTITY_SUB_AGENT}:
        return value
    normalized_role = str(getattr(account, "role_code", "") or "").strip().lower()
    if normalized_role == ROLE_MASTER_AGENT:
        return BUSINESS_IDENTITY_MASTER_AGENT
    if normalized_role == ROLE_SUB_AGENT:
        return BUSINESS_IDENTITY_SUB_AGENT
    return None


def is_staff(account: AdminAccount) -> bool:
    return _account_type(account) == ACCOUNT_TYPE_STAFF


def is_agent(account: AdminAccount) -> bool:
    return _account_type(account) == ACCOUNT_TYPE_AGENT


def is_master_agent(account: AdminAccount) -> bool:
    return _business_identity(account) == BUSINESS_IDENTITY_MASTER_AGENT


def is_sub_agent(account: AdminAccount) -> bool:
    return _business_identity(account) == BUSINESS_IDENTITY_SUB_AGENT


def is_super_admin(account: AdminAccount) -> bool:
    return ROLE_SUPER_ADMIN in set(get_admin_rbac_service().get_role_keys_for_account(account))


def has_permission(account: AdminAccount, *permission_codes: str) -> bool:
    granted = set(get_admin_rbac_service().get_permission_codes_for_account(account))
    required = {str(code or "").strip() for code in permission_codes if str(code or "").strip()}
    return required.issubset(granted)


# ──────────────────────────── Audit helper ────────────────────────────


async def append_audit(
    session: Any,
    *,
    actor: AdminAccount,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
    old_value: Optional[Dict[str, Any]] = None,
    new_value: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> None:
    payload = dict(detail or {})
    payload.setdefault("actor_account_id", int(actor.id))
    payload.setdefault("province_code", actor.province_code)
    actor_label = f"{actor.username}#{actor.id}"
    session.add(
        AdminAuditLog(
            actor=actor_label,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=payload,
            old_value=old_value,
            new_value=new_value,
            ip_address=ip_address,
        )
    )


# ──────────────────────────── Serializers ────────────────────────────


def serialize_tg_binding(binding: Optional[AdminAccountTgBinding]) -> Dict[str, Any]:
    if binding is None:
        return {
            "bind_status": "unbound",
            "tg_user_id": None,
            "tg_username": None,
            "bound_at": None,
        }
    return {
        "bind_status": binding.bind_status,
        "tg_user_id": binding.tg_user_id,
        "tg_username": binding.tg_username,
        "bound_at": binding.bound_at.isoformat() if binding.bound_at else None,
    }


def serialize_admin_account(account: AdminAccount) -> Dict[str, Any]:
    binding = account.__dict__.get("tg_binding")
    rbac_service = get_admin_rbac_service()
    return {
        "id": account.id,
        "username": account.username,
        "display_name": account.display_name,
        "role_code": account.role_code,
        "account_type": _account_type(account),
        "business_identity": _business_identity(account),
        "province_code": account.province_code,
        "parent_account_id": account.parent_account_id,
        "root_master_account_id": account.root_master_account_id,
        "level_depth": account.level_depth,
        "status": account.status,
        "settlement_mode": account.settlement_mode,
        "is_credit_whitelisted": account.is_credit_whitelisted,
        "credit_limit_cents": int(account.credit_limit_cents or 0),
        "allocated_credit_limit_cents": int(account.allocated_credit_limit_cents or 0),
        "credit_used_cents": int(account.credit_used_cents or 0),
        "credit_prepay_cents": int(getattr(account, "credit_prepay_cents", 0) or 0),
        "balance_cents": int(account.balance_cents or 0),
        "force_password_change": bool(account.force_password_change),
        "contact_name": account.contact_name,
        "contact_phone": account.contact_phone,
        "last_login_at": account.last_login_at.isoformat() if account.last_login_at else None,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
        "tg_binding": serialize_tg_binding(binding),
        "assigned_roles": [
            {
                "role_id": binding.role.id,
                "role_key": binding.role.role_key,
                "display_name": binding.role.display_name,
                "is_system": bool(binding.role.is_system),
            }
            for binding in (account.__dict__.get("role_bindings") or [])
            if getattr(binding, "role", None) is not None
        ],
        "permissions": rbac_service.get_permission_codes_for_account(account),
    }


def serialize_batch(
    batch: CardBatch,
    *,
    current_counterparty_name: Optional[str] = None,
    plan_display_name: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "batch_id": batch.batch_id,
        "province_code": batch.province_code,
        "creator_account_id": batch.creator_account_id,
        "owner_account_id": batch.owner_account_id,
        "direct_parent_account_id": batch.direct_parent_account_id,
        "root_master_account_id": batch.root_master_account_id,
        "current_liability_account_id": batch.current_liability_account_id,
        "current_counterparty_account_id": batch.current_counterparty_account_id,
        "current_counterparty_name": current_counterparty_name,
        "plan_code": batch.plan_code,
        "plan_display_name": plan_display_name,
        "quantity": batch.quantity,
        "duration_days": batch.duration_days,
        "unit_price_cents": int(batch.unit_price_cents or 0),
        "total_amount_cents": int(batch.total_amount_cents or 0),
        "settlement_status": batch.settlement_status,
        "payment_status": batch.payment_status,
        "export_count": int(batch.export_count or 0),
        "used_count": int(getattr(batch, "used_count", 0) or 0),
        "total_count": int(batch.quantity or 0),
        "last_exported_at": batch.last_exported_at.isoformat() if batch.last_exported_at else None,
        "remark": batch.remark,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
    }


def serialize_operation_log(item: Dict[str, Any]) -> Dict[str, Any]:
    occurred_at = item.get("occurred_at")
    return {
        "log_type": item.get("log_type"),
        "occurred_at": occurred_at.isoformat() if isinstance(occurred_at, datetime) else occurred_at,
        "operator_account_id": item.get("operator_account_id"),
        "operator_name": item.get("operator_name"),
        "subject_account_id": item.get("subject_account_id"),
        "subject_name": item.get("subject_name"),
        "counterparty_account_id": item.get("counterparty_account_id"),
        "counterparty_name": item.get("counterparty_name"),
        "amount_cents": int(item.get("amount_cents") or 0),
        "plan_code": item.get("plan_code"),
        "plan_display_name": item.get("plan_display_name"),
        "quantity": item.get("quantity"),
        "batch_id": item.get("batch_id"),
        "funding_source": item.get("funding_source"),
        "ledger_scope": item.get("ledger_scope"),
        "remark": item.get("remark"),
    }


def serialize_card(card: ActivationCard, *, plan_display_name: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": card.id,
        "card_code": card.card_code,
        "plan_code": card.plan_code,
        "plan_display_name": plan_display_name,
        "duration_days": card.duration_days,
        "is_active": card.is_active,
        "is_used": card.is_used,
        "expires_at": card.expires_at.isoformat() if card.expires_at else None,
        "used_by_user_id": card.used_by_user_id,
        "used_at": card.used_at.isoformat() if card.used_at else None,
        "batch_id": card.batch_id,
        "owner_account_id": card.owner_account_id,
        "direct_parent_account_id": card.direct_parent_account_id,
        "root_master_account_id": card.root_master_account_id,
        "settlement_unit_price_cents": int(card.settlement_unit_price_cents or 0),
        "card_source_type": card.card_source_type,
        "copy_status": card.copy_status,
        "created_at": card.created_at.isoformat() if card.created_at else None,
    }


def serialize_fund_ledger(
    row: AgentFundLedger,
    *,
    account_name: Optional[str] = None,
    counterparty_name: Optional[str] = None,
    operator_name: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": int(row.id),
        "ledger_scope": row.ledger_scope,
        "account_id": int(row.account_id),
        "account_name": account_name,
        "counterparty_account_id": int(row.counterparty_account_id) if row.counterparty_account_id is not None else None,
        "counterparty_name": counterparty_name,
        "biz_type": row.biz_type,
        "direction": row.direction,
        "amount_cents": int(row.amount_cents or 0),
        "balance_after_cents": int(row.balance_after_cents or 0) if row.balance_after_cents is not None else None,
        "credit_used_after_cents": int(row.credit_used_after_cents or 0) if row.credit_used_after_cents is not None else None,
        "related_batch_id": row.related_batch_id,
        "related_request_id": row.related_request_id,
        "remark": row.remark,
        "operator_account_id": int(row.operator_account_id) if row.operator_account_id is not None else None,
        "operator_name": operator_name,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ──────────────────────────── Visibility helpers ────────────────────────────


async def list_descendant_ids(session: Any, account_id: int) -> List[int]:
    pending = [int(account_id)]
    visited: set[int] = set()
    while pending:
        rows = (
            await session.execute(
                select(AdminAccount.id).where(AdminAccount.parent_account_id.in_(pending))
            )
        ).scalars().all()
        pending = []
        for child_id in rows:
            child_int = int(child_id)
            if child_int not in visited:
                visited.add(child_int)
                pending.append(child_int)
    return sorted(visited)


async def visible_account_ids(session: Any, account: AdminAccount) -> List[int]:
    if is_staff(account):
        rows = (
            await session.execute(
                select(AdminAccount.id).where(AdminAccount.province_code == account.province_code)
            )
        ).scalars().all()
        return [int(item) for item in rows]
    descendants = await list_descendant_ids(session, int(account.id))
    return [int(account.id)] + descendants


async def ensure_visible_account(
    session: Any,
    account: AdminAccount,
    target_account_id: int,
) -> AdminAccount:
    target = await session.get(AdminAccount, int(target_account_id))
    if target is None:
        raise HTTPException(status_code=404, detail="后台账号不存在")
    if is_staff(account):
        if target.province_code != account.province_code:
            raise HTTPException(status_code=403, detail="不能访问其他省份后台账号")
        return target
    visible_ids = await visible_account_ids(session, account)
    if int(target.id) not in visible_ids:
        raise HTTPException(status_code=403, detail="无权访问该后台账号")
    return target


# ──────────────────────────── Utility helpers ────────────────────────────


def parse_datetime_filter(value: Optional[str], *, is_end: bool = False) -> Optional[datetime]:
    normalized = (value or "").strip()
    if not normalized:
        return None
    try:
        if len(normalized) == 10:
            parsed = datetime.fromisoformat(normalized)
            return parsed + timedelta(days=1) if is_end else parsed
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="时间筛选格式无效") from exc


async def build_plan_name_map_from_codes(session: Any, plan_codes: set[str]) -> Dict[str, str]:
    normalized_codes = {code.strip() for code in plan_codes if code and code.strip()}
    if not normalized_codes:
        return {}
    rows = (
        await session.execute(
            select(PricingPlan.plan_code, PricingPlan.display_name).where(PricingPlan.plan_code.in_(normalized_codes))
        )
    ).all()
    return {str(plan_code): str(display_name or plan_code) for plan_code, display_name in rows if plan_code}


async def build_account_name_map_from_ids(
    session: Any,
    account_ids: Iterable[int],
) -> Dict[int, str]:
    normalized_ids = sorted({int(account_id) for account_id in account_ids if int(account_id) > 0})
    if not normalized_ids:
        return {}
    accounts = (
        await session.execute(select(AdminAccount).where(AdminAccount.id.in_(normalized_ids)))
    ).scalars().all()
    return {
        int(account.id): account.display_name or account.username or f"#{account.id}"
        for account in accounts
    }


async def build_account_name_map(
    session: Any,
    rows: Sequence[AgentFundLedger],
) -> Dict[int, str]:
    account_ids: set[int] = set()
    for row in rows:
        account_ids.add(int(row.account_id))
        if row.counterparty_account_id is not None:
            account_ids.add(int(row.counterparty_account_id))
        if row.operator_account_id is not None:
            account_ids.add(int(row.operator_account_id))
    if not account_ids:
        return {}
    accounts = (
        await session.execute(select(AdminAccount).where(AdminAccount.id.in_(sorted(account_ids))))
    ).scalars().all()
    return {
        int(account.id): account.display_name or account.username or f"#{account.id}"
        for account in accounts
    }


def extract_batch_funding_source(batch: CardBatch) -> str:
    remark = (batch.remark or "").strip()
    if "funding_source=" in remark:
        funding_source = remark.split("funding_source=", 1)[1].split()[0].strip().lower()
        if funding_source in {"platform", "balance", "credit"}:
            return funding_source
    if batch.payment_status == "credit":
        return "credit"
    return "balance"
