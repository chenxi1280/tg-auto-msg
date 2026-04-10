"""RBAC admin panel and multi-agent card distribution service."""
from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
import secrets
import string
import uuid

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import Select, and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from backend.config.core.settings import settings
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    ActivationCard,
    AdminAccount,
    AdminAccountRole,
    AdminAccountTgBinding,
    AdminAuditLog,
    AgentCreditLimit,
    AgentFundLedger,
    AdminRole,
    AdminRolePermission,
    CardBatch,
    PricingPlan,
)
from backend.h5_backend.services.admin_rbac.service import get_admin_rbac_service
from backend.h5_backend.services.admin.service import get_admin_license_service
from backend.h5_backend.services.me.service import MeService

CARD_ALPHABET = string.ascii_uppercase + string.digits
ROLE_SUPER_ADMIN = "super_admin"
ROLE_MASTER_AGENT = "master_agent"
ROLE_SUB_AGENT = "sub_agent"
ACCOUNT_TYPE_STAFF = "staff"
ACCOUNT_TYPE_AGENT = "agent"
BUSINESS_IDENTITY_MASTER_AGENT = "master_agent"
BUSINESS_IDENTITY_SUB_AGENT = "sub_agent"


class AdminPanelService:
    """Backoffice RBAC and agent distribution domain service."""

    @staticmethod
    def _mask_actor(account: AdminAccount) -> str:
        return f"{account.username}#{account.id}"

    @staticmethod
    def _generate_card_code(prefix: str = "") -> str:
        normalized_prefix = (prefix or "").strip().upper()
        random_part = "".join(secrets.choice(CARD_ALPHABET) for _ in range(16))
        return f"{normalized_prefix}{random_part}"

    @staticmethod
    def _account_type(account: AdminAccount) -> str:
        value = str(getattr(account, "account_type", "") or "").strip().lower()
        if value in {ACCOUNT_TYPE_STAFF, ACCOUNT_TYPE_AGENT}:
            return value
        return ACCOUNT_TYPE_AGENT if str(account.role_code or "").strip().lower() in {ROLE_MASTER_AGENT, ROLE_SUB_AGENT} else ACCOUNT_TYPE_STAFF

    @staticmethod
    def _business_identity(account: AdminAccount) -> Optional[str]:
        value = str(getattr(account, "business_identity", "") or "").strip().lower()
        if value in {BUSINESS_IDENTITY_MASTER_AGENT, BUSINESS_IDENTITY_SUB_AGENT}:
            return value
        normalized_role = str(account.role_code or "").strip().lower()
        if normalized_role == ROLE_MASTER_AGENT:
            return BUSINESS_IDENTITY_MASTER_AGENT
        if normalized_role == ROLE_SUB_AGENT:
            return BUSINESS_IDENTITY_SUB_AGENT
        return None

    def _is_staff(self, account: AdminAccount) -> bool:
        return self._account_type(account) == ACCOUNT_TYPE_STAFF

    def _is_agent(self, account: AdminAccount) -> bool:
        return self._account_type(account) == ACCOUNT_TYPE_AGENT

    def _is_master_agent(self, account: AdminAccount) -> bool:
        return self._business_identity(account) == BUSINESS_IDENTITY_MASTER_AGENT

    def _is_sub_agent(self, account: AdminAccount) -> bool:
        return self._business_identity(account) == BUSINESS_IDENTITY_SUB_AGENT

    def _is_super_admin(self, account: AdminAccount) -> bool:
        return ROLE_SUPER_ADMIN in set(get_admin_rbac_service().get_role_keys_for_account(account))

    def _has_permission(self, account: AdminAccount, *permission_codes: str) -> bool:
        granted = set(get_admin_rbac_service().get_permission_codes_for_account(account))
        required = {str(code or "").strip() for code in permission_codes if str(code or "").strip()}
        return required.issubset(granted)

    async def _append_audit(
        self,
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
        session.add(
            AdminAuditLog(
                actor=self._mask_actor(actor),
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=payload,
                old_value=old_value,
                new_value=new_value,
                ip_address=ip_address,
            )
        )

    @staticmethod
    def _serialize_tg_binding(binding: Optional[AdminAccountTgBinding]) -> Dict[str, Any]:
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

    def _serialize_admin_account(self, account: AdminAccount) -> Dict[str, Any]:
        binding = account.__dict__.get("tg_binding")
        rbac_service = get_admin_rbac_service()
        return {
            "id": account.id,
            "username": account.username,
            "display_name": account.display_name,
            "role_code": account.role_code,
            "account_type": self._account_type(account),
            "business_identity": self._business_identity(account),
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
            "tg_binding": self._serialize_tg_binding(binding),
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

    @staticmethod
    def _serialize_pricing_plan(plan: PricingPlan) -> Dict[str, Any]:
        return {
            "plan_code": plan.plan_code,
            "display_name": plan.display_name,
            "billing_cycle": plan.billing_cycle,
            "price_cents": int(plan.price_cents or 0),
            "price_yuan": f"{int(plan.price_cents or 0) / 100:.2f}",
            "duration_days": int(plan.duration_days or 0),
            "is_active": bool(plan.is_active),
            "sort_order": int(plan.sort_order or 0),
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
        }

    def _serialize_batch(
        self,
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

    @staticmethod
    def _serialize_operation_log(item: Dict[str, Any]) -> Dict[str, Any]:
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

    def _serialize_card(self, card: ActivationCard, *, plan_display_name: Optional[str] = None) -> Dict[str, Any]:
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

    @staticmethod
    def _serialize_fund_ledger(
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

    @staticmethod
    def _normalize_page(limit: int, offset: int) -> Tuple[int, int]:
        return max(1, min(500, int(limit))), max(0, int(offset))

    @staticmethod
    async def _build_plan_name_map_from_codes(session: Any, plan_codes: set[str]) -> Dict[str, str]:
        normalized_codes = {code.strip() for code in plan_codes if code and code.strip()}
        if not normalized_codes:
            return {}
        rows = (
            await session.execute(
                select(PricingPlan.plan_code, PricingPlan.display_name).where(PricingPlan.plan_code.in_(normalized_codes))
            )
        ).all()
        return {str(plan_code): str(display_name or plan_code) for plan_code, display_name in rows if plan_code}

    @staticmethod
    def _parse_datetime_filter(value: Optional[str], *, is_end: bool = False) -> Optional[datetime]:
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

    async def _list_descendant_ids(self, session: Any, root_account_id: int) -> List[int]:
        pending = [int(root_account_id)]
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

    async def _visible_account_ids(self, session: Any, current_admin: AdminAccount) -> List[int]:
        if self._is_staff(current_admin):
            rows = (
                await session.execute(
                    select(AdminAccount.id).where(AdminAccount.province_code == current_admin.province_code)
                )
            ).scalars().all()
            return [int(item) for item in rows]
        descendants = await self._list_descendant_ids(session, int(current_admin.id))
        return [int(current_admin.id)] + descendants

    async def _ensure_visible_account(
        self,
        session: Any,
        current_admin: AdminAccount,
        target_account_id: int,
    ) -> AdminAccount:
        target = await session.get(AdminAccount, int(target_account_id))
        if target is None:
            raise HTTPException(status_code=404, detail="后台账号不存在")
        if self._is_staff(current_admin):
            if target.province_code != current_admin.province_code:
                raise HTTPException(status_code=403, detail="不能访问其他省份后台账号")
            return target
        visible_ids = await self._visible_account_ids(session, current_admin)
        if int(target.id) not in visible_ids:
            raise HTTPException(status_code=403, detail="无权访问该后台账号")
        return target

    async def _ensure_direct_parent_or_master_override(
        self,
        session: Any,
        current_admin: AdminAccount,
        target: AdminAccount,
    ) -> Tuple[AdminAccount, AgentCreditLimit]:
        if target.parent_account_id is None:
            raise HTTPException(status_code=400, detail="目标账号不是下级代理")
        parent = await session.get(AdminAccount, int(target.parent_account_id))
        if parent is None:
            raise HTTPException(status_code=404, detail="目标账号上级不存在")

        if self._is_staff(current_admin):
            allowed = True
        elif self._is_master_agent(current_admin):
            allowed = int(target.root_master_account_id or 0) == int(current_admin.id)
        else:
            allowed = int(target.parent_account_id or 0) == int(current_admin.id)
        if not allowed:
            raise HTTPException(status_code=403, detail="无权调整该代理额度")

        row = (
            await session.execute(
                select(AgentCreditLimit)
                .where(
                    AgentCreditLimit.parent_account_id == int(parent.id),
                    AgentCreditLimit.child_account_id == int(target.id),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            row = AgentCreditLimit(
                parent_account_id=int(parent.id),
                child_account_id=int(target.id),
                delegated_credit_limit_cents=0,
                delegated_credit_used_cents=int(target.credit_used_cents or 0),
                is_active=True,
            )
            session.add(row)
            await session.flush()
        return parent, row

    @staticmethod
    def _remaining_credit(account: AdminAccount) -> int:
        return max(0, int(account.credit_limit_cents or 0) - int(account.credit_used_cents or 0))

    def _ensure_credit_mode_allowed(self, account: AdminAccount) -> None:
        if account.settlement_mode not in {"credit", "hybrid"}:
            raise HTTPException(status_code=400, detail="当前账号未开启授信结算模式")
        if not account.is_credit_whitelisted:
            raise HTTPException(status_code=400, detail="当前账号未开通授信白名单")

    @staticmethod
    def _normalize_batch_inputs(
        *,
        quantity: int,
        prefix: str = "",
        valid_days: Optional[int] = None,
    ) -> Tuple[int, str, Optional[datetime]]:
        if quantity <= 0 or quantity > 500:
            raise HTTPException(status_code=400, detail="生成数量范围为 1-500")
        normalized_prefix = (prefix or "").strip().upper()
        if len(normalized_prefix) > 20:
            raise HTTPException(status_code=400, detail="前缀最长 20 位")
        expires_at = None
        if valid_days is not None:
            if int(valid_days) <= 0:
                raise HTTPException(status_code=400, detail="valid_days 必须大于 0")
            expires_at = datetime.now() + timedelta(days=int(valid_days))
        return int(quantity), normalized_prefix, expires_at

    @staticmethod
    def _ensure_balance_available(account: AdminAccount, amount_cents: int) -> None:
        if int(account.balance_cents or 0) < int(amount_cents or 0):
            raise HTTPException(status_code=400, detail="余额不足，无法生成卡密")

    async def _prepare_batch_quote(
        self,
        session: Any,
        *,
        account: AdminAccount,
        plan_code: str,
        quantity: int,
        prefix: str = "",
        valid_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        normalized_quantity, normalized_prefix, expires_at = self._normalize_batch_inputs(
            quantity=quantity,
            prefix=prefix,
            valid_days=valid_days,
        )
        plan = await session.get(PricingPlan, (plan_code or "").strip())
        if plan is None or not plan.is_active:
            raise HTTPException(status_code=404, detail="卡密规格不存在或已停用")
        direct_parent_account_id = int(account.parent_account_id) if account.parent_account_id is not None else None
        unit_price = int(plan.price_cents or 0)
        if unit_price <= 0:
            raise HTTPException(status_code=400, detail="该卡密规格尚未配置有效价格")
        root_master_account_id = int(account.root_master_account_id or account.id)
        root_master = await session.get(AdminAccount, root_master_account_id)
        if root_master is None:
            raise HTTPException(status_code=400, detail="总代账号不存在")
        return {
            "account": account,
            "plan": plan,
            "quantity": normalized_quantity,
            "prefix": normalized_prefix,
            "expires_at": expires_at,
            "valid_days": int(valid_days) if valid_days is not None else None,
            "duration_days": int(plan.duration_days or 0),
            "direct_parent_account_id": direct_parent_account_id,
            "unit_price_cents": int(unit_price or 0),
            "total_amount_cents": int(unit_price or 0) * normalized_quantity,
            "root_master": root_master,
        }

    async def _collect_credit_chain(
        self,
        session: Any,
        operator: AdminAccount,
    ) -> List[Tuple[AdminAccount, AdminAccount, AgentCreditLimit]]:
        chain: List[Tuple[AdminAccount, AdminAccount, AgentCreditLimit]] = []
        current = operator
        visited: set[int] = set()
        while current.parent_account_id is not None:
            if int(current.id) in visited:
                raise HTTPException(status_code=500, detail="检测到异常代理层级，请检查数据")
            visited.add(int(current.id))
            parent = await session.get(AdminAccount, int(current.parent_account_id))
            if parent is None:
                raise HTTPException(status_code=400, detail="代理链路上级不存在")
            row = (
                await session.execute(
                    select(AgentCreditLimit)
                    .where(
                        AgentCreditLimit.parent_account_id == int(parent.id),
                        AgentCreditLimit.child_account_id == int(current.id),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None or not row.is_active:
                raise HTTPException(status_code=400, detail="代理链路存在未配置的授信额度")
            chain.append((current, parent, row))
            current = parent
        return chain

    async def _validate_credit_generation(
        self,
        session: Any,
        *,
        operator: AdminAccount,
        root_master: AdminAccount,
        amount_cents: int,
    ) -> List[Tuple[AdminAccount, AdminAccount, AgentCreditLimit]]:
        amount = int(amount_cents or 0)
        if amount <= 0:
            raise HTTPException(status_code=400, detail="生成金额无效")
        self._ensure_credit_mode_allowed(operator)
        chain = await self._collect_credit_chain(session, operator)
        for child, _parent, row in chain:
            remaining = int(row.delegated_credit_limit_cents or 0) - int(row.delegated_credit_used_cents or 0)
            if remaining < amount:
                raise HTTPException(status_code=400, detail=f"代理 {child.display_name} 的授信额度不足")
        if self._remaining_credit(root_master) < amount:
            raise HTTPException(status_code=400, detail="总代总额度不足，无法授信生成卡密")
        return chain

    async def _create_batch_records(
        self,
        session: Any,
        *,
        operator: AdminAccount,
        root_master: AdminAccount,
        direct_parent_account_id: Optional[int],
        plan_code: str,
        duration_days: int,
        unit_price_cents: int,
        total_amount_cents: int,
        quantity: int,
        prefix: str,
        expires_at: Optional[datetime],
        settlement_status: str,
        payment_status: str,
        card_source_type: str,
        remark: Optional[str] = None,
    ) -> Tuple[CardBatch, List[ActivationCard]]:
        batch = CardBatch(
            province_code=operator.province_code or settings.province_code,
            creator_account_id=int(operator.id),
            owner_account_id=int(operator.id),
            direct_parent_account_id=direct_parent_account_id,
            root_master_account_id=int(root_master.id),
            current_liability_account_id=int(operator.id) if payment_status == "credit" else None,
            current_counterparty_account_id=direct_parent_account_id if payment_status == "credit" else None,
            plan_code=plan_code,
            quantity=int(quantity),
            duration_days=int(duration_days),
            unit_price_cents=int(unit_price_cents),
            total_amount_cents=int(total_amount_cents),
            settlement_status=settlement_status,
            payment_status=payment_status,
            remark=remark,
        )
        session.add(batch)
        await session.flush()

        generated_codes: set[str] = set()
        max_attempts = quantity * 20
        attempts = 0
        while len(generated_codes) < quantity and attempts < max_attempts:
            attempts += 1
            generated_codes.add(self._generate_card_code(prefix))
        if len(generated_codes) < quantity:
            raise HTTPException(status_code=500, detail="生成卡密失败，请重试")
        while True:
            existing = (
                await session.execute(
                    select(ActivationCard.card_code).where(ActivationCard.card_code.in_(list(generated_codes)))
                )
            ).all()
            existing_codes = {row[0] for row in existing}
            if not existing_codes:
                break
            generated_codes -= existing_codes
            while len(generated_codes) < quantity:
                generated_codes.add(self._generate_card_code(prefix))

        cards = [
            ActivationCard(
                card_code=code,
                plan_code=plan_code,
                duration_days=int(duration_days),
                is_active=True,
                is_used=False,
                expires_at=expires_at,
                batch_id=batch.batch_id,
                creator_account_id=int(operator.id),
                owner_account_id=int(operator.id),
                direct_parent_account_id=direct_parent_account_id,
                root_master_account_id=int(root_master.id),
                settlement_unit_price_cents=int(unit_price_cents),
                card_source_type=card_source_type,
            )
            for code in sorted(generated_codes)
        ]
        session.add_all(cards)
        return batch, cards

    def _apply_balance_generation(
        self,
        *,
        operator: AdminAccount,
        amount_cents: int,
    ) -> None:
        self._ensure_balance_available(operator, amount_cents)
        operator.balance_cents = int(operator.balance_cents or 0) - int(amount_cents or 0)

    def _apply_credit_generation(
        self,
        session: Any,
        *,
        chain: Sequence[Tuple[AdminAccount, AdminAccount, AgentCreditLimit]],
        root_master: AdminAccount,
        operator: AdminAccount,
        amount_cents: int,
        batch_id: str,
    ) -> None:
        amount = int(amount_cents or 0)
        for child, parent, row in chain:
            row.delegated_credit_used_cents = int(row.delegated_credit_used_cents or 0) + amount
            child.credit_used_cents = int(child.credit_used_cents or 0) + amount
            session.add(
                AgentFundLedger(
                    ledger_scope="channel",
                    account_id=int(child.id),
                    counterparty_account_id=int(parent.id),
                    biz_type="credit_generate",
                    direction="out",
                    amount_cents=amount,
                    balance_after_cents=int(child.balance_cents or 0),
                    credit_used_after_cents=int(child.credit_used_cents or 0),
                    related_batch_id=batch_id,
                    operator_account_id=int(operator.id),
                    remark="授信快速生成卡密，记入对直接上级欠款",
                )
            )
        root_master.credit_used_cents = int(root_master.credit_used_cents or 0) + amount
        session.add(
            AgentFundLedger(
                ledger_scope="platform",
                account_id=int(root_master.id),
                counterparty_account_id=int(operator.id) if int(root_master.id) != int(operator.id) else None,
                biz_type="credit_generate",
                direction="out",
                amount_cents=amount,
                balance_after_cents=int(root_master.balance_cents or 0),
                credit_used_after_cents=int(root_master.credit_used_cents or 0),
                related_batch_id=batch_id,
                operator_account_id=int(operator.id),
                remark="授信快速生成卡密，占用总代总额度",
            )
        )

    async def _apply_settlement_for_batch(
        self,
        session: Any,
        *,
        subject: AdminAccount,
        batch: CardBatch,
        operator: AdminAccount,
        request_id: str,
    ) -> None:
        amount = int(batch.total_amount_cents or 0)
        if batch.payment_status != "credit" or batch.settlement_status == "settled":
            raise HTTPException(status_code=400, detail="当前批次不是待结算的授信批次")
        if int(batch.current_liability_account_id or 0) != int(subject.id):
            raise HTTPException(status_code=400, detail="该批次当前不由此账号负责结算")
        if int(getattr(subject, "credit_prepay_cents", 0) or 0) < amount:
            raise HTTPException(status_code=400, detail="当前账号授信预抵金额不足，无法结清该批次")
        if int(subject.credit_used_cents or 0) < amount:
            raise HTTPException(status_code=400, detail="当前账号授信欠款不足，无法结清该批次")

        subject.credit_prepay_cents = int(getattr(subject, "credit_prepay_cents", 0) or 0) - amount
        subject.credit_used_cents = int(subject.credit_used_cents or 0) - amount
        if subject.parent_account_id is not None:
            row = (
                await session.execute(
                    select(AgentCreditLimit)
                    .where(
                        AgentCreditLimit.parent_account_id == int(subject.parent_account_id),
                        AgentCreditLimit.child_account_id == int(subject.id),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=400, detail="未找到该账号的直接上级授信记录")
            row.delegated_credit_used_cents = max(0, int(row.delegated_credit_used_cents or 0) - amount)
            session.add(
                AgentFundLedger(
                    ledger_scope="channel",
                    account_id=int(subject.id),
                    counterparty_account_id=int(subject.parent_account_id),
                    biz_type="credit_settlement",
                    direction="in",
                    amount_cents=amount,
                    balance_after_cents=int(subject.balance_cents or 0),
                    credit_used_after_cents=int(subject.credit_used_cents or 0),
                    related_batch_id=batch.batch_id,
                    related_request_id=request_id,
                    operator_account_id=int(operator.id),
                    remark="授信批次结算完成，冲减对直接上级欠款",
                )
            )
            next_liability = await session.get(AdminAccount, int(subject.parent_account_id))
            if next_liability is None:
                raise HTTPException(status_code=400, detail="下一层结算责任账号不存在")
            batch.current_liability_account_id = int(next_liability.id)
            batch.current_counterparty_account_id = int(next_liability.parent_account_id) if next_liability.parent_account_id is not None else None
            if next_liability.parent_account_id is None:
                batch.payment_status = "credit"
                batch.settlement_status = "pending"
            else:
                batch.payment_status = "credit"
                batch.settlement_status = "pending"
        else:
            batch.current_liability_account_id = None
            batch.current_counterparty_account_id = None
            batch.payment_status = "paid"
            batch.settlement_status = "settled"
            session.add(
                AgentFundLedger(
                    ledger_scope="platform",
                    account_id=int(subject.id),
                    counterparty_account_id=int(operator.id),
                    biz_type="credit_settlement",
                    direction="in",
                    amount_cents=amount,
                    balance_after_cents=int(subject.balance_cents or 0),
                    credit_used_after_cents=int(subject.credit_used_cents or 0),
                    related_batch_id=batch.batch_id,
                    related_request_id=request_id,
                    operator_account_id=int(operator.id),
                    remark="总代授信批次结算完成，冲减平台侧欠款",
                )
            )

    async def _auto_settle_credit_batches_for_recharge(
        self,
        session: Any,
        *,
        subject: AdminAccount,
        operator: AdminAccount,
    ) -> Tuple[int, List[str]]:
        if int(getattr(subject, "credit_prepay_cents", 0) or 0) <= 0:
            return 0, []

        pending_batches = (
            await session.execute(
                select(CardBatch)
                .where(
                    CardBatch.owner_account_id == int(subject.id),
                    CardBatch.current_liability_account_id == int(subject.id),
                    CardBatch.payment_status == "credit",
                    CardBatch.settlement_status == "pending",
                )
                .order_by(CardBatch.created_at.asc(), CardBatch.batch_id.asc())
            )
        ).scalars().all()

        settled_amount = 0
        settled_batch_ids: List[str] = []
        for batch in pending_batches:
            batch_amount = max(0, int(batch.total_amount_cents or 0))
            if batch_amount <= 0:
                continue
            if int(getattr(subject, "credit_prepay_cents", 0) or 0) < batch_amount:
                break
            request_id = f"direct-recharge-settle-{uuid.uuid4().hex[:20]}"
            await self._apply_settlement_for_batch(
                session,
                subject=subject,
                batch=batch,
                operator=operator,
                request_id=request_id,
            )
            settled_amount += batch_amount
            settled_batch_ids.append(str(batch.batch_id))

        return settled_amount, settled_batch_ids

    async def _has_pending_credit_batches(
        self,
        session: Any,
        *,
        subject_account_id: int,
    ) -> bool:
        pending_batch_id = (
            await session.execute(
                select(CardBatch.batch_id)
                .where(
                    CardBatch.current_liability_account_id == int(subject_account_id),
                    CardBatch.payment_status == "credit",
                    CardBatch.settlement_status == "pending",
                )
                .order_by(CardBatch.created_at.asc(), CardBatch.batch_id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return pending_batch_id is not None

    async def get_profile(self, current_admin: AdminAccount) -> Dict[str, Any]:
        async with get_async_session() as session:
            account = (
                await session.execute(
                    select(AdminAccount)
                    .options(selectinload(AdminAccount.tg_binding))
                    .options(
                        selectinload(AdminAccount.role_bindings)
                        .selectinload(AdminAccountRole.role)
                        .selectinload(AdminRole.permission_bindings)
                        .selectinload(AdminRolePermission.permission)
                    )
                    .where(AdminAccount.id == int(current_admin.id))
                    .limit(1)
                )
            ).scalar_one()
            visible_count = len(await self._visible_account_ids(session, account))
        rbac_service = get_admin_rbac_service()
        return {
            "account": self._serialize_admin_account(account),
            "visible_account_count": visible_count,
            "province_code": account.province_code,
            "roles": rbac_service.get_role_keys_for_account(account),
            "permissions": rbac_service.get_permission_codes_for_account(account),
        }

    async def list_plans(self) -> List[Dict[str, Any]]:
        return await get_admin_license_service().list_plans()

    async def create_master_agent(
        self,
        *,
        current_admin: AdminAccount,
        username: str,
        password: str,
        display_name: str,
        credit_limit_cents: int = 0,
        is_credit_whitelisted: bool = False,
        contact_name: Optional[str] = None,
        contact_phone: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._has_permission(current_admin, "agents.master.create"):
            raise HTTPException(status_code=403, detail="只有超管可以创建总代")
        if len(password or "") < 6:
            raise HTTPException(status_code=400, detail="密码至少 6 位")
        async with get_async_session() as session:
            existing_master = (
                await session.execute(
                    select(AdminAccount)
                    .where(
                        AdminAccount.account_type == ACCOUNT_TYPE_AGENT,
                        AdminAccount.business_identity == BUSINESS_IDENTITY_MASTER_AGENT,
                        AdminAccount.province_code == current_admin.province_code,
                        AdminAccount.status == "active",
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing_master is not None:
                raise HTTPException(status_code=409, detail="当前省份已存在总代账号")
            exists = (
                await session.execute(
                    select(AdminAccount.id).where(AdminAccount.username == (username or "").strip()).limit(1)
                )
            ).scalar_one_or_none()
            if exists is not None:
                raise HTTPException(status_code=409, detail="后台用户名已存在")

            from backend.h5_backend.services.admin_auth.service import get_admin_auth_service
            auth = get_admin_auth_service()
            account = AdminAccount(
                username=(username or "").strip(),
                password_hash=auth.get_password_hash(password),
                role_code=ROLE_MASTER_AGENT,
                account_type=ACCOUNT_TYPE_AGENT,
                business_identity=BUSINESS_IDENTITY_MASTER_AGENT,
                province_code=current_admin.province_code,
                parent_account_id=None,
                root_master_account_id=None,
                level_depth=0,
                status="active",
                settlement_mode="prepaid",
                is_credit_whitelisted=bool(is_credit_whitelisted),
                credit_limit_cents=int(credit_limit_cents or 0),
                display_name=(display_name or "").strip() or (username or "").strip(),
                contact_name=(contact_name or "").strip() or None,
                contact_phone=(contact_phone or "").strip() or None,
                force_password_change=True,
                created_by=int(current_admin.id),
            )
            session.add(account)
            await session.flush()
            account.root_master_account_id = int(account.id)
            master_role = (
                await session.execute(select(AdminRole).where(AdminRole.role_key == ROLE_MASTER_AGENT).limit(1))
            ).scalar_one_or_none()
            if master_role is not None:
                session.add(AdminAccountRole(admin_account_id=int(account.id), role_id=int(master_role.id)))
            await self._append_audit(
                session,
                actor=current_admin,
                action="admin.create_master_agent",
                target_type="admin_account",
                target_id=str(account.id),
                detail={"role_code": ROLE_MASTER_AGENT, "username": account.username},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(account)
            return self._serialize_admin_account(account)

    async def set_master_credit_limit(
        self,
        *,
        current_admin: AdminAccount,
        account_id: int,
        credit_limit_cents: int,
        is_credit_whitelisted: Optional[bool] = None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._has_permission(current_admin, "agents.credit.master.write"):
            raise HTTPException(status_code=403, detail="只有超管可以配置总代总额度")
        async with get_async_session() as session:
            target = await self._ensure_visible_account(session, current_admin, int(account_id))
            if not self._is_master_agent(target):
                raise HTTPException(status_code=400, detail="只能为总代设置总额度")
            if int(target.allocated_credit_limit_cents or 0) > int(credit_limit_cents or 0):
                raise HTTPException(status_code=400, detail="总代已分配给下级的额度超过目标总额度")
            target.credit_limit_cents = int(credit_limit_cents or 0)
            if is_credit_whitelisted is not None:
                target.is_credit_whitelisted = bool(is_credit_whitelisted)
            await self._append_audit(
                session,
                actor=current_admin,
                action="admin.set_master_credit_limit",
                target_type="admin_account",
                target_id=str(target.id),
                detail={"credit_limit_cents": int(credit_limit_cents or 0), "is_credit_whitelisted": is_credit_whitelisted},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(target)
            return self._serialize_admin_account(target)

    async def set_credit_whitelist(
        self,
        *,
        current_admin: AdminAccount,
        account_id: int,
        is_credit_whitelisted: bool,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._has_permission(current_admin, "agents.credit.master.write"):
            raise HTTPException(status_code=403, detail="只有超管可以设置授信白名单")
        async with get_async_session() as session:
            target = await self._ensure_visible_account(session, current_admin, int(account_id))
            target.is_credit_whitelisted = bool(is_credit_whitelisted)
            await self._append_audit(
                session,
                actor=current_admin,
                action="admin.set_credit_whitelist",
                target_type="admin_account",
                target_id=str(target.id),
                detail={"is_credit_whitelisted": bool(is_credit_whitelisted)},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(target)
            return self._serialize_admin_account(target)

    async def list_accounts(
        self,
        *,
        current_admin: AdminAccount,
        search: Optional[str] = None,
        role_code: Optional[str] = None,
        business_identity: Optional[str] = None,
        status: Optional[str] = None,
        parent_account_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit, offset = self._normalize_page(limit, offset)
        async with get_async_session() as session:
            visible_ids = await self._visible_account_ids(session, current_admin)
            stmt = (
                select(AdminAccount)
                .options(selectinload(AdminAccount.tg_binding))
                .options(selectinload(AdminAccount.role_bindings).selectinload(AdminAccountRole.role))
                .where(AdminAccount.id.in_(visible_ids))
                .where(AdminAccount.account_type == ACCOUNT_TYPE_AGENT)
            )
            count_stmt = (
                select(func.count(AdminAccount.id))
                .where(AdminAccount.id.in_(visible_ids))
                .where(AdminAccount.account_type == ACCOUNT_TYPE_AGENT)
            )
            normalized_search = (search or "").strip()
            if normalized_search:
                search_value = f"%{normalized_search}%"
                search_condition = (
                    AdminAccount.username.ilike(search_value)
                    | AdminAccount.display_name.ilike(search_value)
                    | AdminAccount.contact_name.ilike(search_value)
                    | AdminAccount.contact_phone.ilike(search_value)
                )
                stmt = stmt.where(search_condition)
                count_stmt = count_stmt.where(search_condition)
            normalized_role = (role_code or "").strip().lower()
            if normalized_role and normalized_role != "all":
                stmt = stmt.where(AdminAccount.business_identity == normalized_role)
                count_stmt = count_stmt.where(AdminAccount.business_identity == normalized_role)
            normalized_business_identity = (business_identity or "").strip().lower()
            if normalized_business_identity and normalized_business_identity != "all":
                stmt = stmt.where(AdminAccount.business_identity == normalized_business_identity)
                count_stmt = count_stmt.where(AdminAccount.business_identity == normalized_business_identity)
            normalized_status = (status or "").strip().lower()
            if normalized_status and normalized_status != "all":
                stmt = stmt.where(AdminAccount.status == normalized_status)
                count_stmt = count_stmt.where(AdminAccount.status == normalized_status)
            if parent_account_id is not None:
                stmt = stmt.where(AdminAccount.parent_account_id == int(parent_account_id))
                count_stmt = count_stmt.where(AdminAccount.parent_account_id == int(parent_account_id))
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (
                await session.execute(
                    stmt.order_by(AdminAccount.level_depth.asc(), AdminAccount.id.asc()).limit(limit).offset(offset)
                )
            ).scalars().all()
            return {
                "items": [self._serialize_admin_account(row) for row in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    async def create_child_agent(
        self,
        *,
        current_admin: AdminAccount,
        username: str,
        password: str,
        display_name: str,
        settlement_mode: str = "prepaid",
        credit_limit_cents: int = 0,
        contact_name: Optional[str] = None,
        contact_phone: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._is_agent(current_admin) or self._business_identity(current_admin) not in {
            BUSINESS_IDENTITY_MASTER_AGENT,
            BUSINESS_IDENTITY_SUB_AGENT,
        }:
            raise HTTPException(status_code=403, detail="当前角色不能创建下级代理")
        async with get_async_session() as session:
            parent = await session.get(AdminAccount, int(current_admin.id))
            exists = (
                await session.execute(select(AdminAccount.id).where(AdminAccount.username == (username or "").strip()).limit(1))
            ).scalar_one_or_none()
            if exists is not None:
                raise HTTPException(status_code=409, detail="后台用户名已存在")
            from backend.h5_backend.services.admin_auth.service import get_admin_auth_service
            auth = get_admin_auth_service()
            child = AdminAccount(
                username=(username or "").strip(),
                password_hash=auth.get_password_hash(password),
                role_code=ROLE_SUB_AGENT,
                account_type=ACCOUNT_TYPE_AGENT,
                business_identity=BUSINESS_IDENTITY_SUB_AGENT,
                province_code=parent.province_code,
                parent_account_id=int(parent.id),
                root_master_account_id=int(parent.root_master_account_id or parent.id),
                level_depth=int(parent.level_depth or 0) + 1,
                status="active",
                settlement_mode=(settlement_mode or "prepaid").strip() or "prepaid",
                is_credit_whitelisted=False,
                credit_limit_cents=int(credit_limit_cents or 0),
                display_name=(display_name or "").strip() or (username or "").strip(),
                contact_name=(contact_name or "").strip() or None,
                contact_phone=(contact_phone or "").strip() or None,
                force_password_change=True,
                created_by=int(parent.id),
            )
            session.add(child)
            await session.flush()
            sub_role = (
                await session.execute(select(AdminRole).where(AdminRole.role_key == ROLE_SUB_AGENT).limit(1))
            ).scalar_one_or_none()
            if sub_role is not None:
                session.add(AdminAccountRole(admin_account_id=int(child.id), role_id=int(sub_role.id)))

            credit_row = AgentCreditLimit(
                parent_account_id=int(parent.id),
                child_account_id=int(child.id),
                delegated_credit_limit_cents=int(credit_limit_cents or 0),
                delegated_credit_used_cents=0,
                is_active=True,
                last_adjusted_by=int(parent.id),
            )
            new_allocated = int(parent.allocated_credit_limit_cents or 0) + int(credit_limit_cents or 0)
            if new_allocated > int(parent.credit_limit_cents or 0):
                raise HTTPException(status_code=400, detail="分配给下级的额度超过上级可分配额度")
            parent.allocated_credit_limit_cents = new_allocated
            session.add(credit_row)

            await self._append_audit(
                session,
                actor=current_admin,
                action="agent.create_child_account",
                target_type="admin_account",
                target_id=str(child.id),
                detail={"parent_account_id": int(parent.id), "credit_limit_cents": int(credit_limit_cents or 0)},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(child)
            return self._serialize_admin_account(child)

    async def set_settlement_mode(
        self,
        *,
        current_admin: AdminAccount,
        account_id: int,
        settlement_mode: str,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if settlement_mode not in {"prepaid", "credit", "hybrid"}:
            raise HTTPException(status_code=400, detail="不支持的结算模式")
        async with get_async_session() as session:
            target = await self._ensure_visible_account(session, current_admin, int(account_id))
            if not self._is_agent(target):
                raise HTTPException(status_code=400, detail="只能调整代理账号的结算模式")
            if target.id == current_admin.id and not self._is_staff(current_admin):
                raise HTTPException(status_code=400, detail="不能修改自己的结算模式")
            if not self._is_staff(current_admin):
                if target.parent_account_id != current_admin.id and not (
                    self._is_master_agent(current_admin) and target.root_master_account_id == current_admin.id
                ):
                    raise HTTPException(status_code=403, detail="只能修改直系下级或总代链路内下级的结算模式")
            target.settlement_mode = settlement_mode
            await self._append_audit(
                session,
                actor=current_admin,
                action="agent.set_settlement_mode",
                target_type="admin_account",
                target_id=str(target.id),
                detail={"settlement_mode": settlement_mode},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(target)
            return self._serialize_admin_account(target)

    async def set_child_credit_limit(
        self,
        *,
        current_admin: AdminAccount,
        account_id: int,
        credit_limit_cents: int,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with get_async_session() as session:
            target = await self._ensure_visible_account(session, current_admin, int(account_id))
            parent, row = await self._ensure_direct_parent_or_master_override(session, current_admin, target)
            new_limit = int(credit_limit_cents or 0)
            old_limit = int(row.delegated_credit_limit_cents or 0)
            if int(row.delegated_credit_used_cents or target.credit_used_cents or 0) > new_limit:
                raise HTTPException(status_code=400, detail="目标额度不能小于该下级已使用额度")
            new_allocated = int(parent.allocated_credit_limit_cents or 0) - old_limit + new_limit
            if new_allocated > int(parent.credit_limit_cents or 0):
                raise HTTPException(status_code=400, detail="分配给下级的额度超过上级可分配额度")
            parent.allocated_credit_limit_cents = new_allocated
            row.delegated_credit_limit_cents = new_limit
            row.last_adjusted_by = int(current_admin.id)
            target.credit_limit_cents = new_limit
            await self._append_audit(
                session,
                actor=current_admin,
                action="agent.set_child_credit_limit",
                target_type="admin_account",
                target_id=str(target.id),
                detail={"parent_account_id": int(parent.id), "credit_limit_cents": new_limit},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(target)
            return self._serialize_admin_account(target)

    async def list_pricing_plans(
        self,
        *,
        current_admin: AdminAccount,
        search: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        del current_admin
        limit, offset = self._normalize_page(limit, offset)
        async with get_async_session() as session:
            stmt = select(PricingPlan)
            count_stmt = select(func.count(PricingPlan.plan_code))
            normalized_search = (search or "").strip()
            if normalized_search:
                search_value = f"%{normalized_search}%"
                search_condition = (
                    PricingPlan.plan_code.ilike(search_value)
                    | PricingPlan.display_name.ilike(search_value)
                )
                stmt = stmt.where(search_condition)
                count_stmt = count_stmt.where(search_condition)
            if is_active is not None:
                stmt = stmt.where(PricingPlan.is_active.is_(bool(is_active)))
                count_stmt = count_stmt.where(PricingPlan.is_active.is_(bool(is_active)))
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (
                await session.execute(
                    stmt.order_by(PricingPlan.sort_order.asc(), PricingPlan.plan_code.asc()).limit(limit).offset(offset)
                )
            ).scalars().all()
            return {
                "items": [self._serialize_pricing_plan(row) for row in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    async def update_pricing_plan(
        self,
        *,
        current_admin: AdminAccount,
        plan_code: str,
        price_cents: int,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if int(price_cents or 0) <= 0:
            raise HTTPException(status_code=400, detail="price_cents 必须大于 0")
        async with get_async_session() as session:
            plan = await session.get(PricingPlan, (plan_code or "").strip())
            if plan is None:
                raise HTTPException(status_code=404, detail="卡密规格不存在")
            old_price = int(plan.price_cents or 0)
            plan.price_cents = int(price_cents)
            await self._append_audit(
                session,
                actor=current_admin,
                action="admin.set_global_plan_price",
                target_type="pricing_plan",
                target_id=plan.plan_code,
                detail={"old_price_cents": old_price, "new_price_cents": int(price_cents)},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(plan)
            return self._serialize_pricing_plan(plan)

    async def generate_card_batch(
        self,
        *,
        current_admin: AdminAccount,
        plan_code: str,
        quantity: int,
        prefix: str = "",
        valid_days: Optional[int] = None,
        funding_source: str,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._has_permission(current_admin, "batches.generate"):
            raise HTTPException(status_code=403, detail="当前角色不能生成卡密")
        normalized_funding_source = (funding_source or "").strip().lower()
        if normalized_funding_source not in {"balance", "credit"}:
            raise HTTPException(status_code=400, detail="funding_source 仅支持 balance 或 credit")

        async with get_async_session() as session:
            operator = await session.get(AdminAccount, int(current_admin.id))
            quote = await self._prepare_batch_quote(
                session,
                account=operator,
                plan_code=plan_code,
                quantity=quantity,
                prefix=prefix,
                valid_days=valid_days,
            )
            total_amount = int(quote["total_amount_cents"])
            if self._is_staff(current_admin):
                payment_status = "paid"
                settlement_status = "settled"
                card_source_type = "platform"
                chain: List[Tuple[AdminAccount, AdminAccount, AgentCreditLimit]] = []
            elif normalized_funding_source == "credit":
                self._ensure_credit_mode_allowed(operator)
                chain = await self._validate_credit_generation(
                    session,
                    operator=operator,
                    root_master=quote["root_master"],
                    amount_cents=total_amount,
                )
                payment_status = "credit"
                settlement_status = "pending"
                card_source_type = "credit"
            else:
                self._apply_balance_generation(operator=operator, amount_cents=total_amount)
                payment_status = "paid"
                settlement_status = "settled"
                card_source_type = "balance"
                chain: List[Tuple[AdminAccount, AdminAccount, AgentCreditLimit]] = []

            batch, cards = await self._create_batch_records(
                session,
                operator=operator,
                root_master=quote["root_master"],
                direct_parent_account_id=quote["direct_parent_account_id"],
                plan_code=quote["plan"].plan_code,
                duration_days=quote["duration_days"],
                unit_price_cents=quote["unit_price_cents"],
                total_amount_cents=quote["total_amount_cents"],
                quantity=quote["quantity"],
                prefix=quote["prefix"],
                expires_at=quote["expires_at"],
                settlement_status=settlement_status,
                payment_status=payment_status,
                card_source_type=card_source_type,
                remark=f"funding_source={'platform' if self._is_staff(current_admin) else normalized_funding_source}",
            )

            if self._is_staff(current_admin):
                pass
            elif normalized_funding_source == "balance":
                session.add(
                    AgentFundLedger(
                        ledger_scope="platform" if operator.parent_account_id is None else "channel",
                        account_id=int(operator.id),
                        counterparty_account_id=int(operator.parent_account_id) if operator.parent_account_id is not None else None,
                        biz_type="consume_balance",
                        direction="out",
                        amount_cents=total_amount,
                        balance_after_cents=int(operator.balance_cents or 0),
                        credit_used_after_cents=int(operator.credit_used_cents or 0),
                        related_batch_id=batch.batch_id,
                        operator_account_id=int(operator.id),
                        remark="余额生成卡密批次，直接扣减已确认余额",
                    )
                )
            else:
                self._apply_credit_generation(
                    session,
                    chain=chain,
                    root_master=quote["root_master"],
                    operator=operator,
                    amount_cents=total_amount,
                    batch_id=batch.batch_id,
                )

            await self._append_audit(
                session,
                actor=operator,
                action="agent.generate_card_batch",
                target_type="card_batch",
                target_id=batch.batch_id,
                detail={
                    "plan_code": quote["plan"].plan_code,
                    "quantity": int(quote["quantity"]),
                    "total_amount_cents": int(total_amount),
                    "funding_source": "platform" if self._is_staff(current_admin) else normalized_funding_source,
                },
                ip_address=ip_address,
            )
            await session.flush()

            return {
                "batch": self._serialize_batch(batch),
                "cards": [self._serialize_card(card) for card in cards],
                "copied_text": "\n".join(card.card_code for card in cards[:10]),
            }

    async def list_card_batches(
        self,
        *,
        current_admin: AdminAccount,
        plan_code: Optional[str] = None,
        payment_status: Optional[str] = None,
        settlement_status: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit, offset = self._normalize_page(limit, offset)
        async with get_async_session() as session:
            visible_ids = await self._visible_account_ids(session, current_admin)
            stmt = select(CardBatch).where(CardBatch.owner_account_id.in_(visible_ids))
            count_stmt = select(func.count(CardBatch.batch_id)).where(CardBatch.owner_account_id.in_(visible_ids))
            normalized_plan = (plan_code or "").strip()
            if normalized_plan:
                stmt = stmt.where(CardBatch.plan_code == normalized_plan)
                count_stmt = count_stmt.where(CardBatch.plan_code == normalized_plan)
            normalized_payment = (payment_status or "").strip().lower()
            if normalized_payment and normalized_payment != "all":
                stmt = stmt.where(CardBatch.payment_status == normalized_payment)
                count_stmt = count_stmt.where(CardBatch.payment_status == normalized_payment)
            normalized_settlement = (settlement_status or "").strip().lower()
            if normalized_settlement and normalized_settlement != "all":
                stmt = stmt.where(CardBatch.settlement_status == normalized_settlement)
                count_stmt = count_stmt.where(CardBatch.settlement_status == normalized_settlement)
            normalized_keyword = (keyword or "").strip()
            if normalized_keyword:
                keyword_value = f"%{normalized_keyword}%"
                keyword_condition = CardBatch.batch_id.ilike(keyword_value) | CardBatch.plan_code.ilike(keyword_value)
                stmt = stmt.where(keyword_condition)
                count_stmt = count_stmt.where(keyword_condition)
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (
                await session.execute(
                    stmt.order_by(CardBatch.created_at.desc()).limit(limit).offset(offset)
                )
            ).scalars().all()
            batch_ids = [row.batch_id for row in rows if row.batch_id]
            used_count_map: Dict[str, int] = {}
            if batch_ids:
                used_rows = await session.execute(
                    select(ActivationCard.batch_id, func.count(ActivationCard.id))
                    .where(
                        ActivationCard.batch_id.in_(batch_ids),
                        ActivationCard.is_used.is_(True),
                    )
                    .group_by(ActivationCard.batch_id)
                )
                used_count_map = {
                    str(batch_id): int(count or 0)
                    for batch_id, count in used_rows.all()
                    if batch_id
                }
            for row in rows:
                setattr(row, "used_count", used_count_map.get(str(row.batch_id), 0))
            account_ids = {
                int(row.current_counterparty_account_id)
                for row in rows
                if row.current_counterparty_account_id is not None
            }
            counterparty_name_map = await self._build_account_name_map_from_ids(session, account_ids) if account_ids else {}
            plan_name_map = await self._build_plan_name_map_from_codes(
                session,
                {str(row.plan_code) for row in rows if row.plan_code},
            )
            items = [
                self._serialize_batch(
                    row,
                    current_counterparty_name=counterparty_name_map.get(int(row.current_counterparty_account_id))
                    if row.current_counterparty_account_id is not None
                    else None,
                    plan_display_name=plan_name_map.get(str(row.plan_code), str(row.plan_code or "")) if row.plan_code else None,
                )
                for row in rows
            ]
            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
                "stats": {
                    "page_total_amount_cents": sum(int(item["total_amount_cents"] or 0) for item in items),
                    "page_paid_count": sum(1 for item in items if item["payment_status"] == "paid"),
                    "page_credit_count": sum(1 for item in items if item["payment_status"] == "credit"),
                    "page_pending_settlement_count": sum(1 for item in items if item["settlement_status"] == "pending"),
                },
            }

    async def list_cards(
        self,
        *,
        current_admin: AdminAccount,
        plan_code: Optional[str] = None,
        batch_id: Optional[str] = None,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit, offset = self._normalize_page(limit, offset)
        async with get_async_session() as session:
            visible_ids = await self._visible_account_ids(session, current_admin)
            stmt = select(ActivationCard).where(ActivationCard.owner_account_id.in_(visible_ids))
            count_stmt = select(func.count(ActivationCard.id)).where(ActivationCard.owner_account_id.in_(visible_ids))
            normalized_plan = (plan_code or "").strip()
            if normalized_plan:
                stmt = stmt.where(ActivationCard.plan_code == normalized_plan)
                count_stmt = count_stmt.where(ActivationCard.plan_code == normalized_plan)
            normalized_batch_id = (batch_id or "").strip()
            if normalized_batch_id:
                stmt = stmt.where(ActivationCard.batch_id == normalized_batch_id)
                count_stmt = count_stmt.where(ActivationCard.batch_id == normalized_batch_id)
            normalized_status = (status or "").strip().lower()
            if normalized_status == "available":
                stmt = stmt.where(ActivationCard.is_used.is_(False))
                count_stmt = count_stmt.where(ActivationCard.is_used.is_(False))
            elif normalized_status == "used":
                stmt = stmt.where(ActivationCard.is_used.is_(True))
                count_stmt = count_stmt.where(ActivationCard.is_used.is_(True))
            normalized_source = (source_type or "").strip().lower()
            if normalized_source and normalized_source != "all":
                stmt = stmt.where(ActivationCard.card_source_type == normalized_source)
                count_stmt = count_stmt.where(ActivationCard.card_source_type == normalized_source)
            normalized_keyword = (keyword or "").strip()
            if normalized_keyword:
                keyword_value = f"%{normalized_keyword}%"
                keyword_condition = (
                    ActivationCard.card_code.ilike(keyword_value)
                    | ActivationCard.batch_id.ilike(keyword_value)
                    | ActivationCard.plan_code.ilike(keyword_value)
                )
                stmt = stmt.where(keyword_condition)
                count_stmt = count_stmt.where(keyword_condition)
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (
                await session.execute(
                    stmt.order_by(ActivationCard.created_at.desc(), ActivationCard.id.desc()).limit(limit).offset(offset)
                )
            ).scalars().all()
            plan_name_map = await self._build_plan_name_map_from_codes(
                session,
                {str(row.plan_code) for row in rows if row.plan_code},
            )
            return {
                "items": [
                    self._serialize_card(
                        row,
                        plan_display_name=plan_name_map.get(str(row.plan_code), str(row.plan_code or "")) if row.plan_code else None,
                    )
                    for row in rows
                ],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    async def list_self_fund_ledgers(
        self,
        *,
        current_admin: AdminAccount,
        biz_type: Optional[str] = None,
        direction: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit, offset = self._normalize_page(limit, offset)
        async with get_async_session() as session:
            stmt = select(AgentFundLedger).where(AgentFundLedger.account_id == int(current_admin.id))
            count_stmt = select(func.count(AgentFundLedger.id)).where(AgentFundLedger.account_id == int(current_admin.id))
            normalized_biz = (biz_type or "").strip().lower()
            if normalized_biz and normalized_biz != "all":
                stmt = stmt.where(AgentFundLedger.biz_type == normalized_biz)
                count_stmt = count_stmt.where(AgentFundLedger.biz_type == normalized_biz)
            normalized_direction = (direction or "").strip().lower()
            if normalized_direction and normalized_direction != "all":
                stmt = stmt.where(AgentFundLedger.direction == normalized_direction)
                count_stmt = count_stmt.where(AgentFundLedger.direction == normalized_direction)
            normalized_keyword = (keyword or "").strip()
            if normalized_keyword:
                keyword_value = f"%{normalized_keyword}%"
                keyword_condition = (
                    AgentFundLedger.remark.ilike(keyword_value)
                    | AgentFundLedger.related_batch_id.ilike(keyword_value)
                )
                stmt = stmt.where(keyword_condition)
                count_stmt = count_stmt.where(keyword_condition)
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (
                await session.execute(
                    stmt.order_by(AgentFundLedger.created_at.desc(), AgentFundLedger.id.desc()).limit(limit).offset(offset)
                )
            ).scalars().all()
            account_map = await self._build_account_name_map(session, rows)
            items = [
                self._serialize_fund_ledger(
                    row,
                    account_name=account_map.get(int(row.account_id)),
                    counterparty_name=account_map.get(int(row.counterparty_account_id)) if row.counterparty_account_id is not None else None,
                    operator_name=account_map.get(int(row.operator_account_id)) if row.operator_account_id is not None else None,
                )
                for row in rows
            ]
            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
                "stats": {
                    "page_in_amount_cents": sum(item["amount_cents"] for item in items if item["direction"] == "in"),
                    "page_out_amount_cents": sum(item["amount_cents"] for item in items if item["direction"] == "out"),
                },
            }

    async def list_visible_fund_ledgers(
        self,
        *,
        current_admin: AdminAccount,
        biz_type: Optional[str] = None,
        direction: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 200,
        account_id: Optional[int] = None,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit, offset = self._normalize_page(limit, offset)
        async with get_async_session() as session:
            visible_ids = await self._visible_account_ids(session, current_admin)
            if account_id is not None and int(account_id) not in set(visible_ids):
                raise HTTPException(status_code=403, detail="无权查看该账号流水")
            stmt = select(AgentFundLedger).where(AgentFundLedger.account_id.in_(visible_ids))
            count_stmt = select(func.count(AgentFundLedger.id)).where(AgentFundLedger.account_id.in_(visible_ids))
            if account_id is not None:
                stmt = stmt.where(AgentFundLedger.account_id == int(account_id))
                count_stmt = count_stmt.where(AgentFundLedger.account_id == int(account_id))
            normalized_biz = (biz_type or "").strip().lower()
            if normalized_biz and normalized_biz != "all":
                stmt = stmt.where(AgentFundLedger.biz_type == normalized_biz)
                count_stmt = count_stmt.where(AgentFundLedger.biz_type == normalized_biz)
            normalized_direction = (direction or "").strip().lower()
            if normalized_direction and normalized_direction != "all":
                stmt = stmt.where(AgentFundLedger.direction == normalized_direction)
                count_stmt = count_stmt.where(AgentFundLedger.direction == normalized_direction)
            normalized_keyword = (keyword or "").strip()
            if normalized_keyword:
                keyword_value = f"%{normalized_keyword}%"
                keyword_condition = (
                    AgentFundLedger.remark.ilike(keyword_value)
                    | AgentFundLedger.related_batch_id.ilike(keyword_value)
                )
                stmt = stmt.where(keyword_condition)
                count_stmt = count_stmt.where(keyword_condition)
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (
                await session.execute(
                    stmt.order_by(AgentFundLedger.created_at.desc(), AgentFundLedger.id.desc()).limit(limit).offset(offset)
                )
            ).scalars().all()
            account_map = await self._build_account_name_map(session, rows)
            items = [
                self._serialize_fund_ledger(
                    row,
                    account_name=account_map.get(int(row.account_id)),
                    counterparty_name=account_map.get(int(row.counterparty_account_id)) if row.counterparty_account_id is not None else None,
                    operator_name=account_map.get(int(row.operator_account_id)) if row.operator_account_id is not None else None,
                )
                for row in rows
            ]
            return {
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    async def list_operation_logs(
        self,
        *,
        current_admin: AdminAccount,
        log_type: Optional[str] = None,
        account_id: Optional[int] = None,
        keyword: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        scope_only: bool = True,
    ) -> Dict[str, Any]:
        limit, offset = self._normalize_page(limit, offset)
        normalized_type = (log_type or "").strip().lower()
        if normalized_type and normalized_type not in {"all", "recharge", "card_generate", "credit_settlement"}:
            raise HTTPException(status_code=400, detail="不支持的操作日志类型")
        normalized_keyword = (keyword or "").strip().lower()
        started_at = self._parse_datetime_filter(date_from)
        ended_at = self._parse_datetime_filter(date_to, is_end=True)
        if started_at and ended_at and started_at >= ended_at:
            raise HTTPException(status_code=400, detail="时间范围无效")

        async with get_async_session() as session:
            visible_ids = await self._visible_account_ids(session, current_admin) if scope_only else [int(current_admin.id)]
            visible_id_set = set(visible_ids)
            if account_id is not None and int(account_id) not in visible_id_set:
                raise HTTPException(status_code=403, detail="无权查看该账号操作记录")

            items: List[Dict[str, Any]] = []
            account_name_ids: set[int] = set()

            if normalized_type in {"", "all", "recharge", "credit_settlement"}:
                ledger_stmt = select(AgentFundLedger).where(
                    AgentFundLedger.account_id.in_(visible_ids),
                    AgentFundLedger.biz_type.in_(["recharge", "credit_settlement"]),
                )
                if account_id is not None:
                    ledger_stmt = ledger_stmt.where(AgentFundLedger.account_id == int(account_id))
                if started_at is not None:
                    ledger_stmt = ledger_stmt.where(AgentFundLedger.created_at >= started_at)
                if ended_at is not None:
                    ledger_stmt = ledger_stmt.where(AgentFundLedger.created_at < ended_at)
                ledger_rows = (await session.execute(ledger_stmt)).scalars().all()
                for row in ledger_rows:
                    account_name_ids.add(int(row.account_id))
                    if row.counterparty_account_id is not None:
                        account_name_ids.add(int(row.counterparty_account_id))
                    if row.operator_account_id is not None:
                        account_name_ids.add(int(row.operator_account_id))
                    items.append(
                        {
                            "log_type": "recharge" if row.biz_type == "recharge" else "credit_settlement",
                            "occurred_at": row.created_at,
                            "operator_account_id": int(row.operator_account_id) if row.operator_account_id is not None else None,
                            "subject_account_id": int(row.account_id),
                            "counterparty_account_id": int(row.counterparty_account_id) if row.counterparty_account_id is not None else None,
                            "amount_cents": int(row.amount_cents or 0),
                            "plan_code": None,
                            "quantity": None,
                            "batch_id": row.related_batch_id,
                            "funding_source": None,
                            "ledger_scope": row.ledger_scope,
                            "remark": row.remark,
                        }
                    )

            if normalized_type in {"", "all", "card_generate"}:
                batch_stmt = select(CardBatch).where(CardBatch.owner_account_id.in_(visible_ids))
                if account_id is not None:
                    batch_stmt = batch_stmt.where(CardBatch.owner_account_id == int(account_id))
                if started_at is not None:
                    batch_stmt = batch_stmt.where(CardBatch.created_at >= started_at)
                if ended_at is not None:
                    batch_stmt = batch_stmt.where(CardBatch.created_at < ended_at)
                batch_rows = (await session.execute(batch_stmt)).scalars().all()
                for row in batch_rows:
                    account_name_ids.add(int(row.creator_account_id))
                    account_name_ids.add(int(row.owner_account_id))
                    if row.direct_parent_account_id is not None:
                        account_name_ids.add(int(row.direct_parent_account_id))
                    if row.root_master_account_id is not None:
                        account_name_ids.add(int(row.root_master_account_id))
                    funding_source = self._extract_batch_funding_source(row)
                    items.append(
                        {
                            "log_type": "card_generate",
                            "occurred_at": row.created_at,
                            "operator_account_id": int(row.creator_account_id),
                            "subject_account_id": int(row.owner_account_id),
                            "counterparty_account_id": int(row.direct_parent_account_id) if row.direct_parent_account_id is not None else None,
                            "amount_cents": int(row.total_amount_cents or 0),
                            "plan_code": row.plan_code,
                            "quantity": int(row.quantity or 0),
                            "batch_id": row.batch_id,
                            "funding_source": funding_source,
                            "ledger_scope": "platform" if funding_source == "platform" else "channel",
                            "remark": row.remark,
                        }
                    )

            account_name_map = await self._build_account_name_map_from_ids(session, account_name_ids)
            for item in items:
                item["operator_name"] = account_name_map.get(int(item["operator_account_id"])) if item.get("operator_account_id") else None
                item["subject_name"] = account_name_map.get(int(item["subject_account_id"])) if item.get("subject_account_id") else None
                item["counterparty_name"] = account_name_map.get(int(item["counterparty_account_id"])) if item.get("counterparty_account_id") else None
            plan_name_map = await self._build_plan_name_map_from_codes(
                session,
                {str(item["plan_code"]) for item in items if item.get("plan_code")},
            )
            for item in items:
                item["plan_display_name"] = (
                    plan_name_map.get(str(item["plan_code"]), str(item["plan_code"]))
                    if item.get("plan_code")
                    else None
                )

            if normalized_keyword:
                items = [
                    item
                    for item in items
                    if any(
                        normalized_keyword in str(field or "").lower()
                        for field in (
                            item.get("operator_name"),
                            item.get("subject_name"),
                            item.get("counterparty_name"),
                            item.get("remark"),
                            item.get("batch_id"),
                            item.get("plan_code"),
                        )
                    )
                ]

            items.sort(
                key=lambda item: (
                    item.get("occurred_at") or datetime.min,
                    item.get("batch_id") or "",
                    item.get("subject_account_id") or 0,
                ),
                reverse=True,
            )

            total = len(items)
            paged_items = items[offset : offset + limit]
            recharge_items = [item for item in items if item["log_type"] == "recharge"]
            generate_items = [item for item in items if item["log_type"] == "card_generate"]
            settlement_items = [item for item in items if item["log_type"] == "credit_settlement"]

            return {
                "items": [self._serialize_operation_log(item) for item in paged_items],
                "total": total,
                "limit": limit,
                "offset": offset,
                "stats": {
                    "recharge_count": len(recharge_items),
                    "recharge_amount_cents": sum(int(item["amount_cents"] or 0) for item in recharge_items),
                    "card_generate_count": len(generate_items),
                    "card_generate_amount_cents": sum(int(item["amount_cents"] or 0) for item in generate_items),
                    "credit_settlement_count": len(settlement_items),
                    "credit_settlement_amount_cents": sum(int(item["amount_cents"] or 0) for item in settlement_items),
                },
            }

    async def create_recharge_entry(
        self,
        *,
        current_admin: AdminAccount,
        subject_account_id: int,
        amount_cents: int,
        remark: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        amount = int(amount_cents or 0)
        if amount <= 0:
            raise HTTPException(status_code=400, detail="充值金额必须大于 0")

        async with get_async_session() as session:
            operator = await session.get(AdminAccount, int(current_admin.id))
            subject = await self._ensure_visible_account(session, operator, int(subject_account_id))
            if not self._is_agent(subject):
                raise HTTPException(status_code=400, detail="只能为代理账号直接充值入账")
            if not self._is_staff(operator) and int(subject.parent_account_id or 0) != int(operator.id):
                raise HTTPException(status_code=403, detail="只能为直系下级直接充值入账")

            subject.credit_prepay_cents = int(getattr(subject, "credit_prepay_cents", 0) or 0) + amount
            settled_credit_amount, settled_batch_ids = await self._auto_settle_credit_batches_for_recharge(
                session,
                subject=subject,
                operator=operator,
            )
            has_pending_credit_batches = await self._has_pending_credit_batches(
                session,
                subject_account_id=int(subject.id),
            )

            prepay_carried_amount = 0
            top_up_balance_amount = 0
            if has_pending_credit_batches:
                prepay_carried_amount = int(getattr(subject, "credit_prepay_cents", 0) or 0)
            else:
                top_up_balance_amount = int(getattr(subject, "credit_prepay_cents", 0) or 0)
                if top_up_balance_amount > 0:
                    subject.balance_cents = int(subject.balance_cents or 0) + top_up_balance_amount
                    subject.credit_prepay_cents = 0

            split_remark_parts: List[str] = []
            if settled_credit_amount > 0:
                split_remark_parts.append(
                    f"先结清授信批次 {settled_credit_amount / 100:.2f}"
                    + (f"（{len(settled_batch_ids)} 批）" if settled_batch_ids else "")
                )
            if prepay_carried_amount > 0:
                split_remark_parts.append(f"授信预抵结转 {prepay_carried_amount / 100:.2f}")
            if top_up_balance_amount > 0:
                split_remark_parts.append(f"再补余额 {top_up_balance_amount / 100:.2f}")
            split_remark = "；".join(split_remark_parts)
            session.add(
                AgentFundLedger(
                    ledger_scope="platform" if self._is_staff(operator) else "channel",
                    account_id=int(subject.id),
                    counterparty_account_id=int(operator.id) if int(subject.id) != int(operator.id) else None,
                    biz_type="recharge",
                    direction="in",
                    amount_cents=amount,
                    balance_after_cents=int(subject.balance_cents or 0),
                    credit_used_after_cents=int(subject.credit_used_cents or 0),
                    operator_account_id=int(operator.id),
                    remark="；".join(
                        part
                        for part in [((remark or "").strip() or None), split_remark]
                        if part
                    ) or "后台直接充值入账",
                )
            )
            await self._append_audit(
                session,
                actor=operator,
                action="agent.direct_recharge",
                target_type="admin_account",
                target_id=str(subject.id),
                detail={
                    "amount_cents": amount,
                    "credit_repaid_cents": settled_credit_amount,
                    "settled_batch_ids": settled_batch_ids,
                    "credit_prepay_cents": prepay_carried_amount,
                    "balance_topped_up_cents": top_up_balance_amount,
                    "credit_prepay_after_cents": int(getattr(subject, "credit_prepay_cents", 0) or 0),
                    "remark": (remark or "").strip() or None,
                },
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(subject)
            return self._serialize_admin_account(subject)

    async def settle_credit_batch(
        self,
        *,
        current_admin: AdminAccount,
        batch_id: str,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_batch_id = str(batch_id or "").strip()
        if not normalized_batch_id:
            raise HTTPException(status_code=400, detail="batch_id 不能为空")

        async with get_async_session() as session:
            operator = await session.get(AdminAccount, int(current_admin.id))
            batch = await session.get(CardBatch, normalized_batch_id)
            if batch is None:
                raise HTTPException(status_code=404, detail="待结算批次不存在")
            visible_ids = await self._visible_account_ids(session, operator)
            if int(batch.owner_account_id or 0) not in set(visible_ids):
                raise HTTPException(status_code=403, detail="无权访问该授信批次")
            if int(batch.current_liability_account_id or 0) != int(operator.id):
                raise HTTPException(status_code=403, detail="该批次当前不由此账号负责结清")

            request_id = f"direct-settle-{uuid.uuid4().hex[:20]}"
            await self._apply_settlement_for_batch(
                session,
                subject=operator,
                batch=batch,
                operator=operator,
                request_id=request_id,
            )
            await self._append_audit(
                session,
                actor=operator,
                action="agent.direct_settlement",
                target_type="card_batch",
                target_id=batch.batch_id,
                detail={"batch_id": batch.batch_id, "request_id": request_id},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(batch)
            return self._serialize_batch(batch)

    async def _build_account_name_map(
        self,
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

    async def _build_account_name_map_from_ids(
        self,
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

    @staticmethod
    def _extract_batch_funding_source(batch: CardBatch) -> str:
        remark = (batch.remark or "").strip()
        if "funding_source=" in remark:
            funding_source = remark.split("funding_source=", 1)[1].split()[0].strip().lower()
            if funding_source in {"platform", "balance", "credit"}:
                return funding_source
        if batch.payment_status == "credit":
            return "credit"
        return "balance"

    async def export_cards_xlsx(
        self,
        *,
        current_admin: AdminAccount,
        plan_code: Optional[str] = None,
        batch_id: Optional[str] = None,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> Tuple[bytes, int]:
        cards_page = await self.list_cards(
            current_admin=current_admin,
            plan_code=plan_code,
            batch_id=batch_id,
            status=status,
            source_type=source_type,
            keyword=keyword,
            limit=5000,
            offset=0,
        )
        rows = cards_page["items"]
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font
        except ModuleNotFoundError as exc:
            raise HTTPException(status_code=503, detail="当前环境缺少 openpyxl，无法导出 Excel") from exc
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "卡密列表"
        headers = ["卡密", "规格", "批次", "归属账号", "上级账号", "总代", "状态", "创建时间"]
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in rows:
            status = "已使用" if row["is_used"] else ("可用" if row["is_active"] else "已停用")
            sheet.append([
                row["card_code"],
                row["plan_code"] or "",
                row["batch_id"] or "",
                row["owner_account_id"] or "",
                row["direct_parent_account_id"] or "",
                row["root_master_account_id"] or "",
                status,
                row["created_at"] or "",
            ])
        buffer = BytesIO()
        workbook.save(buffer)
        workbook.close()
        return buffer.getvalue(), len(rows)

    async def copy_cards(
        self,
        *,
        current_admin: AdminAccount,
        card_ids: Sequence[int],
        with_meta: bool = False,
    ) -> Dict[str, Any]:
        normalized_ids = [int(item) for item in card_ids if int(item) > 0]
        if not normalized_ids:
            raise HTTPException(status_code=400, detail="请选择要复制的卡密")
        if len(normalized_ids) > 10:
            raise HTTPException(status_code=400, detail="单次最多复制 10 个卡密，请改用导出 Excel")
        async with get_async_session() as session:
            visible_ids = set(await self._visible_account_ids(session, current_admin))
            rows = (
                await session.execute(
                    select(ActivationCard)
                    .where(
                        ActivationCard.id.in_(normalized_ids),
                        ActivationCard.owner_account_id.in_(visible_ids),
                    )
                    .order_by(ActivationCard.id.asc())
                )
            ).scalars().all()
            if not rows:
                raise HTTPException(status_code=404, detail="未找到可复制的卡密")
            for row in rows:
                row.copy_status = "copied"
            copied_text = "\n".join(
                (
                    f"{row.card_code} | {row.plan_code or '-'} | {row.batch_id or '-'}"
                    if with_meta else row.card_code
                )
                for row in rows
            )
            return {
                "count": len(rows),
                "copied_text": copied_text,
            }

    async def list_audit_logs(
        self,
        *,
        current_admin: AdminAccount,
        action: Optional[str] = None,
        target_type: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit, offset = self._normalize_page(limit, offset)
        async with get_async_session() as session:
            stmt = select(AdminAuditLog)
            count_stmt = select(func.count(AdminAuditLog.id))
            normalized_action = (action or "").strip()
            if normalized_action:
                stmt = stmt.where(AdminAuditLog.action == normalized_action)
                count_stmt = count_stmt.where(AdminAuditLog.action == normalized_action)
            normalized_target = (target_type or "").strip()
            if normalized_target:
                stmt = stmt.where(AdminAuditLog.target_type == normalized_target)
                count_stmt = count_stmt.where(AdminAuditLog.target_type == normalized_target)
            normalized_keyword = (keyword or "").strip()
            if normalized_keyword:
                keyword_value = f"%{normalized_keyword}%"
                keyword_condition = (
                    AdminAuditLog.actor.ilike(keyword_value)
                    | AdminAuditLog.action.ilike(keyword_value)
                    | AdminAuditLog.target_id.ilike(keyword_value)
                )
                stmt = stmt.where(keyword_condition)
                count_stmt = count_stmt.where(keyword_condition)
            visible_ids = set(await self._visible_account_ids(session, current_admin))
            can_read_system_audit = self._has_permission(current_admin, "audit.system.read")
            if can_read_system_audit:
                total = int((await session.execute(count_stmt)).scalar_one() or 0)
                rows = (
                    await session.execute(
                        stmt.order_by(AdminAuditLog.id.desc()).limit(limit).offset(offset)
                    )
                ).scalars().all()
            else:
                rows = (
                    await session.execute(
                        stmt.order_by(AdminAuditLog.id.desc())
                    )
                ).scalars().all()
        result: List[Dict[str, Any]] = []
        for row in rows:
            detail = row.detail or {}
            actor_account_id = detail.get("actor_account_id")
            if not can_read_system_audit and actor_account_id is not None and int(actor_account_id) not in visible_ids:
                continue
            result.append(
                {
                    "id": row.id,
                    "actor": row.actor,
                    "action": row.action,
                    "target_type": row.target_type,
                    "target_id": row.target_id,
                    "old_value": row.old_value,
                    "new_value": row.new_value,
                    "detail": detail,
                    "ip_address": row.ip_address,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )
        if not can_read_system_audit:
            total = len(result)
            result = result[offset:offset + limit]
        return {
            "items": result,
            "total": total,
            "limit": limit,
            "offset": offset,
        }


_admin_panel_service: Optional[AdminPanelService] = None


def get_admin_panel_service() -> AdminPanelService:
    global _admin_panel_service
    if _admin_panel_service is None:
        _admin_panel_service = AdminPanelService()
    return _admin_panel_service
