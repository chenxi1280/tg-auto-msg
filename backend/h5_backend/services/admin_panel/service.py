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
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from telethon import Button

from backend.bot.client_runtime.manager import bot_client
from backend.config.core.settings import settings
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    ActivationCard,
    AdminAccount,
    AdminAccountTgBinding,
    AdminAuditLog,
    AgentCreditLimit,
    AgentFundLedger,
    ApprovalRequest,
    CardBatch,
    PricingPlan,
)
from backend.h5_backend.services.admin.service import get_admin_license_service
from backend.h5_backend.services.me.service import MeService

CARD_ALPHABET = string.ascii_uppercase + string.digits
ROLE_SUPER_ADMIN = "super_admin"
ROLE_MASTER_AGENT = "master_agent"
ROLE_SUB_AGENT = "sub_agent"


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
        return {
            "id": account.id,
            "username": account.username,
            "display_name": account.display_name,
            "role_code": account.role_code,
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
            "balance_cents": int(account.balance_cents or 0),
            "force_password_change": bool(account.force_password_change),
            "contact_name": account.contact_name,
            "contact_phone": account.contact_phone,
            "last_login_at": account.last_login_at.isoformat() if account.last_login_at else None,
            "created_at": account.created_at.isoformat() if account.created_at else None,
            "updated_at": account.updated_at.isoformat() if account.updated_at else None,
            "tg_binding": self._serialize_tg_binding(binding),
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

    def _serialize_batch(self, batch: CardBatch) -> Dict[str, Any]:
        return {
            "batch_id": batch.batch_id,
            "province_code": batch.province_code,
            "creator_account_id": batch.creator_account_id,
            "owner_account_id": batch.owner_account_id,
            "direct_parent_account_id": batch.direct_parent_account_id,
            "root_master_account_id": batch.root_master_account_id,
            "current_liability_account_id": batch.current_liability_account_id,
            "current_counterparty_account_id": batch.current_counterparty_account_id,
            "plan_code": batch.plan_code,
            "quantity": batch.quantity,
            "duration_days": batch.duration_days,
            "unit_price_cents": int(batch.unit_price_cents or 0),
            "total_amount_cents": int(batch.total_amount_cents or 0),
            "settlement_status": batch.settlement_status,
            "payment_status": batch.payment_status,
            "export_count": int(batch.export_count or 0),
            "last_exported_at": batch.last_exported_at.isoformat() if batch.last_exported_at else None,
            "remark": batch.remark,
            "created_at": batch.created_at.isoformat() if batch.created_at else None,
        }

    def _serialize_card(self, card: ActivationCard) -> Dict[str, Any]:
        return {
            "id": card.id,
            "card_code": card.card_code,
            "plan_code": card.plan_code,
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

    def _serialize_approval_request(self, row: ApprovalRequest) -> Dict[str, Any]:
        return {
            "request_id": row.request_id,
            "province_code": row.province_code,
            "request_type": row.request_type,
            "requester_account_id": row.requester_account_id,
            "subject_account_id": row.subject_account_id,
            "approver_account_id": row.approver_account_id,
            "status": row.status,
            "amount_cents": int(row.amount_cents or 0) if row.amount_cents is not None else None,
            "credit_delta_cents": int(row.credit_delta_cents or 0) if row.credit_delta_cents is not None else None,
            "payload_json": row.payload_json or {},
            "approved_at": row.approved_at.isoformat() if row.approved_at else None,
            "rejected_at": row.rejected_at.isoformat() if row.rejected_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
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
        if current_admin.role_code == ROLE_SUPER_ADMIN:
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
        if current_admin.role_code == ROLE_SUPER_ADMIN:
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

        if current_admin.role_code == ROLE_SUPER_ADMIN:
            allowed = True
        elif current_admin.role_code == ROLE_MASTER_AGENT:
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
        if int(subject.credit_used_cents or 0) < amount:
            raise HTTPException(status_code=400, detail="当前账号授信欠款不足，无法结清该批次")

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

    async def _find_super_admin_approver(self, session: Any, province_code: str) -> AdminAccount:
        approver = (
            await session.execute(
                select(AdminAccount)
                .where(
                    AdminAccount.role_code == ROLE_SUPER_ADMIN,
                    AdminAccount.province_code == province_code,
                    AdminAccount.status == "active",
                )
                .order_by(AdminAccount.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if approver is None:
            approver = (
                await session.execute(
                    select(AdminAccount)
                    .where(
                        AdminAccount.role_code == ROLE_SUPER_ADMIN,
                        AdminAccount.status == "active",
                    )
                    .order_by(AdminAccount.id.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if approver is None:
            raise HTTPException(status_code=400, detail="当前未配置可用的超管审批账号")
        return approver

    async def _notify_approval_request(self, request: ApprovalRequest) -> None:
        async with get_async_session() as session:
            approver = await session.get(AdminAccount, int(request.approver_account_id))
            binding = (
                await session.execute(
                    select(AdminAccountTgBinding)
                    .where(
                        AdminAccountTgBinding.admin_account_id == int(request.approver_account_id),
                        AdminAccountTgBinding.bind_status == "bound",
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            requester = await session.get(AdminAccount, int(request.requester_account_id))
            subject = await session.get(AdminAccount, int(request.subject_account_id))
        if approver is None or binding is None or binding.tg_user_id is None:
            return
        amount_text = ""
        if request.amount_cents is not None:
            amount_text = f"\n金额：{int(request.amount_cents) / 100:.2f} 元"
        if request.credit_delta_cents is not None:
            amount_text += f"\n额度变化：{int(request.credit_delta_cents) / 100:.2f} 元"
        payload = request.payload_json or {}
        extra_lines: List[str] = []
        if payload.get("plan_code"):
            extra_lines.append(f"规格：{payload.get('plan_code')}")
        if payload.get("quantity"):
            extra_lines.append(f"数量：{payload.get('quantity')}")
        if payload.get("batch_id"):
            extra_lines.append(f"批次：{payload.get('batch_id')}")
        extra_text = ""
        if extra_lines:
            extra_text = "\n" + "\n".join(extra_lines)
        text = (
            f"审批待处理\n"
            f"申请单号：{request.request_id}\n"
            f"类型：{request.request_type}\n"
            f"发起人：{requester.display_name if requester else request.requester_account_id}\n"
            f"主体：{subject.display_name if subject else request.subject_account_id}"
            f"{amount_text}{extra_text}\n"
            f"时间：{request.created_at.strftime('%Y-%m-%d %H:%M:%S') if request.created_at else '-'}"
        )
        buttons = [
            [
                Button.inline("确认", data=f"admapp:approve:{request.request_id}"),
                Button.inline("驳回", data=f"admapp:reject:{request.request_id}"),
            ]
        ]
        try:
            await bot_client.send_message(int(binding.tg_user_id), text, buttons=buttons)
        except Exception as exc:
            logger.warning("发送审批 TG 通知失败: request_id={}, error_type={}", request.request_id, type(exc).__name__)

    async def get_profile(self, current_admin: AdminAccount) -> Dict[str, Any]:
        async with get_async_session() as session:
            account = (
                await session.execute(
                    select(AdminAccount)
                    .options(selectinload(AdminAccount.tg_binding))
                    .where(AdminAccount.id == int(current_admin.id))
                    .limit(1)
                )
            ).scalar_one()
            visible_count = len(await self._visible_account_ids(session, account))
        return {
            "account": self._serialize_admin_account(account),
            "visible_account_count": visible_count,
            "province_code": account.province_code,
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
        if current_admin.role_code != ROLE_SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="只有超管可以创建总代")
        if len(password or "") < 6:
            raise HTTPException(status_code=400, detail="密码至少 6 位")
        async with get_async_session() as session:
            existing_master = (
                await session.execute(
                    select(AdminAccount)
                    .where(
                        AdminAccount.role_code == ROLE_MASTER_AGENT,
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
        if current_admin.role_code != ROLE_SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="只有超管可以配置总代总额度")
        async with get_async_session() as session:
            target = await self._ensure_visible_account(session, current_admin, int(account_id))
            if target.role_code != ROLE_MASTER_AGENT:
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
        if current_admin.role_code != ROLE_SUPER_ADMIN:
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

    async def list_accounts(self, *, current_admin: AdminAccount) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            visible_ids = await self._visible_account_ids(session, current_admin)
            rows = (
                await session.execute(
                    select(AdminAccount)
                    .options(selectinload(AdminAccount.tg_binding))
                    .where(AdminAccount.id.in_(visible_ids))
                    .order_by(AdminAccount.level_depth.asc(), AdminAccount.id.asc())
                )
            ).scalars().all()
            return [self._serialize_admin_account(row) for row in rows]

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
        if current_admin.role_code not in {ROLE_MASTER_AGENT, ROLE_SUB_AGENT}:
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
            if target.id == current_admin.id and current_admin.role_code != ROLE_SUPER_ADMIN:
                raise HTTPException(status_code=400, detail="不能修改自己的结算模式")
            if current_admin.role_code != ROLE_SUPER_ADMIN:
                if target.parent_account_id != current_admin.id and not (
                    current_admin.role_code == ROLE_MASTER_AGENT and target.root_master_account_id == current_admin.id
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

    async def list_pricing_plans(self, *, current_admin: AdminAccount) -> List[Dict[str, Any]]:
        del current_admin
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(PricingPlan).order_by(PricingPlan.sort_order.asc(), PricingPlan.plan_code.asc())
                )
            ).scalars().all()
            return [self._serialize_pricing_plan(row) for row in rows]

    async def update_pricing_plan(
        self,
        *,
        current_admin: AdminAccount,
        plan_code: str,
        price_cents: int,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if current_admin.role_code != ROLE_SUPER_ADMIN:
            raise HTTPException(status_code=403, detail="只有超管可以维护统一价格")
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
        if current_admin.role_code not in {ROLE_MASTER_AGENT, ROLE_SUB_AGENT}:
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
            if normalized_funding_source == "credit":
                self._ensure_credit_mode_allowed(operator)
            if normalized_funding_source == "balance":
                self._apply_balance_generation(operator=operator, amount_cents=total_amount)
                payment_status = "paid"
                settlement_status = "settled"
                card_source_type = "balance"
                chain: List[Tuple[AdminAccount, AdminAccount, AgentCreditLimit]] = []
            else:
                chain = await self._validate_credit_generation(
                    session,
                    operator=operator,
                    root_master=quote["root_master"],
                    amount_cents=total_amount,
                )
                payment_status = "credit"
                settlement_status = "pending"
                card_source_type = "credit"

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
                remark=f"funding_source={normalized_funding_source}",
            )

            if normalized_funding_source == "balance":
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
                    "funding_source": normalized_funding_source,
                },
                ip_address=ip_address,
            )
            await session.flush()

            return {
                "batch": self._serialize_batch(batch),
                "cards": [self._serialize_card(card) for card in cards],
                "copied_text": "\n".join(card.card_code for card in cards[:10]),
            }

    async def list_card_batches(self, *, current_admin: AdminAccount) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            visible_ids = await self._visible_account_ids(session, current_admin)
            rows = (
                await session.execute(
                    select(CardBatch).where(CardBatch.owner_account_id.in_(visible_ids)).order_by(CardBatch.created_at.desc())
                )
            ).scalars().all()
            return [self._serialize_batch(row) for row in rows]

    async def list_cards(
        self,
        *,
        current_admin: AdminAccount,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        async with get_async_session() as session:
            visible_ids = await self._visible_account_ids(session, current_admin)
            count_stmt = select(func.count(ActivationCard.id)).where(ActivationCard.owner_account_id.in_(visible_ids))
            stmt = (
                select(ActivationCard)
                .where(ActivationCard.owner_account_id.in_(visible_ids))
                .order_by(ActivationCard.created_at.desc(), ActivationCard.id.desc())
                .limit(max(1, min(500, int(limit))))
                .offset(max(0, int(offset)))
            )
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (await session.execute(stmt)).scalars().all()
            return {
                "items": [self._serialize_card(row) for row in rows],
                "total": total,
                "limit": max(1, min(500, int(limit))),
                "offset": max(0, int(offset)),
            }

    async def list_self_fund_ledgers(
        self,
        *,
        current_admin: AdminAccount,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(AgentFundLedger)
                    .where(AgentFundLedger.account_id == int(current_admin.id))
                    .order_by(AgentFundLedger.created_at.desc(), AgentFundLedger.id.desc())
                    .limit(max(1, min(500, int(limit))))
                )
            ).scalars().all()
            account_map = await self._build_account_name_map(session, rows)
            return [
                self._serialize_fund_ledger(
                    row,
                    account_name=account_map.get(int(row.account_id)),
                    counterparty_name=account_map.get(int(row.counterparty_account_id)) if row.counterparty_account_id is not None else None,
                    operator_name=account_map.get(int(row.operator_account_id)) if row.operator_account_id is not None else None,
                )
                for row in rows
            ]

    async def list_visible_fund_ledgers(
        self,
        *,
        current_admin: AdminAccount,
        limit: int = 200,
        account_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            visible_ids = await self._visible_account_ids(session, current_admin)
            if account_id is not None and int(account_id) not in set(visible_ids):
                raise HTTPException(status_code=403, detail="无权查看该账号流水")
            stmt = select(AgentFundLedger).where(AgentFundLedger.account_id.in_(visible_ids))
            if account_id is not None:
                stmt = stmt.where(AgentFundLedger.account_id == int(account_id))
            rows = (
                await session.execute(
                    stmt.order_by(AgentFundLedger.created_at.desc(), AgentFundLedger.id.desc()).limit(max(1, min(500, int(limit))))
                )
            ).scalars().all()
            account_map = await self._build_account_name_map(session, rows)
            return [
                self._serialize_fund_ledger(
                    row,
                    account_name=account_map.get(int(row.account_id)),
                    counterparty_name=account_map.get(int(row.counterparty_account_id)) if row.counterparty_account_id is not None else None,
                    operator_name=account_map.get(int(row.operator_account_id)) if row.operator_account_id is not None else None,
                )
                for row in rows
            ]

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

    async def export_cards_xlsx(self, *, current_admin: AdminAccount) -> Tuple[bytes, int]:
        cards_page = await self.list_cards(current_admin=current_admin, limit=5000, offset=0)
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

    async def create_approval_request(
        self,
        *,
        current_admin: AdminAccount,
        request_type: str,
        amount_cents: Optional[int] = None,
        credit_delta_cents: Optional[int] = None,
        subject_account_id: Optional[int] = None,
        payload_json: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        request_type = (request_type or "").strip()
        if request_type not in {"recharge", "settlement", "credit_adjust", "batch_purchase"}:
            raise HTTPException(status_code=400, detail="不支持的审批类型")
        async with get_async_session() as session:
            subject = await self._ensure_visible_account(session, current_admin, int(subject_account_id or current_admin.id))
            normalized_payload = dict(payload_json or {})

            if request_type == "recharge":
                if int(amount_cents or 0) <= 0:
                    raise HTTPException(status_code=400, detail="充值金额必须大于 0")
            elif request_type == "credit_adjust":
                requested_limit = int(normalized_payload.get("credit_limit_cents") or credit_delta_cents or 0)
                if requested_limit < 0:
                    raise HTTPException(status_code=400, detail="目标额度不能为负数")
                credit_delta_cents = requested_limit
                normalized_payload["credit_limit_cents"] = requested_limit
            elif request_type == "batch_purchase":
                quote = await self._prepare_batch_quote(
                    session,
                    account=subject,
                    plan_code=str(normalized_payload.get("plan_code") or "").strip(),
                    quantity=int(normalized_payload.get("quantity") or 0),
                    prefix=str(normalized_payload.get("prefix") or ""),
                    valid_days=normalized_payload.get("valid_days"),
                )
                amount_cents = int(quote["total_amount_cents"])
                normalized_payload = {
                    **normalized_payload,
                    "plan_code": quote["plan"].plan_code,
                    "quantity": int(quote["quantity"]),
                    "prefix": quote["prefix"],
                    "valid_days": quote["valid_days"],
                    "duration_days": int(quote["duration_days"]),
                    "direct_parent_account_id": quote["direct_parent_account_id"],
                    "root_master_account_id": int(quote["root_master"].id),
                    "unit_price_cents": int(quote["unit_price_cents"]),
                    "quoted_amount_cents": int(quote["total_amount_cents"]),
                }
            elif request_type == "settlement":
                batch_id = str(normalized_payload.get("batch_id") or "").strip()
                if not batch_id:
                    raise HTTPException(status_code=400, detail="结算审批必须指定授信批次")
                batch = await session.get(CardBatch, batch_id)
                if batch is None or int(batch.current_liability_account_id or 0) != int(subject.id):
                    raise HTTPException(status_code=404, detail="待结算批次不存在")
                if batch.payment_status != "credit" or batch.settlement_status == "settled":
                    raise HTTPException(status_code=400, detail="该批次不是待结算授信批次")
                pending_rows = (
                    await session.execute(
                        select(ApprovalRequest)
                        .where(
                            ApprovalRequest.request_type == "settlement",
                            ApprovalRequest.status == "pending",
                            ApprovalRequest.subject_account_id == int(subject.id),
                        )
                    )
                ).scalars().all()
                if any(str((row.payload_json or {}).get("batch_id") or "") == batch_id for row in pending_rows):
                    raise HTTPException(status_code=409, detail="该批次已有待处理结算审批")
                amount_cents = int(batch.total_amount_cents or 0)
                normalized_payload = {
                    **normalized_payload,
                    "batch_id": batch.batch_id,
                    "plan_code": batch.plan_code,
                    "quantity": int(batch.quantity or 0),
                    "quoted_amount_cents": int(batch.total_amount_cents or 0),
                    "current_counterparty_account_id": batch.current_counterparty_account_id,
                }

            if current_admin.role_code == ROLE_SUPER_ADMIN:
                approver = current_admin
            elif subject.parent_account_id is None:
                approver = await self._find_super_admin_approver(session, current_admin.province_code)
            else:
                approver = await session.get(AdminAccount, int(subject.parent_account_id))
                if approver is None:
                    raise HTTPException(status_code=400, detail="审批上级不存在")
            row = ApprovalRequest(
                province_code=current_admin.province_code,
                request_type=request_type,
                requester_account_id=int(current_admin.id),
                subject_account_id=int(subject.id),
                approver_account_id=int(approver.id),
                status="pending",
                amount_cents=int(amount_cents) if amount_cents is not None else None,
                credit_delta_cents=int(credit_delta_cents) if credit_delta_cents is not None else None,
                payload_json=normalized_payload,
            )
            session.add(row)
            await self._append_audit(
                session,
                actor=current_admin,
                action="agent.create_approval_request",
                target_type="approval_request",
                target_id=row.request_id,
                detail={"request_type": request_type, "approver_account_id": int(approver.id), "subject_account_id": int(subject.id)},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(row)
        await self._notify_approval_request(row)
        return self._serialize_approval_request(row)

    async def list_pending_approvals(self, *, current_admin: AdminAccount) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(ApprovalRequest)
                    .where(
                        ApprovalRequest.approver_account_id == int(current_admin.id),
                        ApprovalRequest.status == "pending",
                    )
                    .order_by(ApprovalRequest.created_at.desc())
                )
            ).scalars().all()
            return [self._serialize_approval_request(row) for row in rows]

    async def list_approval_requests(
        self,
        *,
        current_admin: AdminAccount,
        status: Optional[str] = None,
        request_type: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            visible_ids = await self._visible_account_ids(session, current_admin)
            stmt = select(ApprovalRequest).where(ApprovalRequest.province_code == current_admin.province_code)
            if current_admin.role_code != ROLE_SUPER_ADMIN:
                stmt = stmt.where(
                    or_(
                        ApprovalRequest.approver_account_id == int(current_admin.id),
                        ApprovalRequest.requester_account_id.in_(visible_ids),
                        ApprovalRequest.subject_account_id.in_(visible_ids),
                    )
                )
            normalized_status = (status or "").strip().lower()
            if normalized_status and normalized_status != "all":
                stmt = stmt.where(ApprovalRequest.status == normalized_status)
            normalized_type = (request_type or "").strip().lower()
            if normalized_type and normalized_type != "all":
                stmt = stmt.where(ApprovalRequest.request_type == normalized_type)
            rows = (
                await session.execute(
                    stmt.order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.request_id.desc()).limit(max(1, min(500, int(limit))))
                )
            ).scalars().all()
            return [self._serialize_approval_request(row) for row in rows]

    async def _apply_approval_effect(self, session: Any, request: ApprovalRequest, operator: AdminAccount) -> None:
        subject = await session.get(AdminAccount, int(request.subject_account_id))
        if subject is None:
            raise HTTPException(status_code=404, detail="审批主体账号不存在")
        amount = int(request.amount_cents or 0)
        if request.request_type == "recharge":
            subject.balance_cents = int(subject.balance_cents or 0) + amount
            session.add(
                AgentFundLedger(
                    ledger_scope="channel" if operator.role_code != ROLE_SUPER_ADMIN else "platform",
                    account_id=int(subject.id),
                    counterparty_account_id=int(operator.id),
                    biz_type=request.request_type,
                    direction="in",
                    amount_cents=amount,
                    balance_after_cents=int(subject.balance_cents or 0),
                    credit_used_after_cents=int(subject.credit_used_cents or 0),
                    related_request_id=request.request_id,
                    operator_account_id=int(operator.id),
                    remark=f"审批通过: {request.request_type}",
                )
            )
        elif request.request_type == "settlement":
            payload = request.payload_json or {}
            batch_id = str(payload.get("batch_id") or "").strip()
            if not batch_id:
                raise HTTPException(status_code=400, detail="结算审批缺少 batch_id")
            batch = await session.get(CardBatch, batch_id)
            if batch is None or int(batch.current_liability_account_id or 0) != int(subject.id):
                raise HTTPException(status_code=404, detail="待结算批次不存在")
            await self._apply_settlement_for_batch(
                session,
                subject=subject,
                batch=batch,
                operator=operator,
                request_id=request.request_id,
            )
        elif request.request_type == "credit_adjust":
            payload = request.payload_json or {}
            requested_limit = int(payload.get("credit_limit_cents") or request.credit_delta_cents or 0)
            if operator.role_code == ROLE_SUPER_ADMIN and subject.role_code == ROLE_MASTER_AGENT:
                if int(subject.allocated_credit_limit_cents or 0) > requested_limit:
                    raise HTTPException(status_code=400, detail="总代已分配额度超过目标值")
                subject.credit_limit_cents = requested_limit
            else:
                parent, row = await self._ensure_direct_parent_or_master_override(session, operator, subject)
                old_limit = int(row.delegated_credit_limit_cents or 0)
                new_allocated = int(parent.allocated_credit_limit_cents or 0) - old_limit + requested_limit
                if new_allocated > int(parent.credit_limit_cents or 0):
                    raise HTTPException(status_code=400, detail="目标额度超过上级可分配额度")
                parent.allocated_credit_limit_cents = new_allocated
                row.delegated_credit_limit_cents = requested_limit
                row.last_adjusted_by = int(operator.id)
                subject.credit_limit_cents = requested_limit
        elif request.request_type == "batch_purchase":
            payload = request.payload_json or {}
            root_master = await session.get(AdminAccount, int(subject.root_master_account_id or subject.id))
            if root_master is None:
                raise HTTPException(status_code=400, detail="审批主体缺少总代账号")
            batch, cards = await self._create_batch_records(
                session,
                operator=subject,
                root_master=root_master,
                direct_parent_account_id=int(payload.get("direct_parent_account_id")) if payload.get("direct_parent_account_id") is not None else subject.parent_account_id,
                plan_code=str(payload.get("plan_code") or ""),
                duration_days=int(payload.get("duration_days") or 0),
                unit_price_cents=int(payload.get("unit_price_cents") or 0),
                total_amount_cents=int(payload.get("quoted_amount_cents") or amount),
                quantity=int(payload.get("quantity") or 0),
                prefix=str(payload.get("prefix") or ""),
                expires_at=datetime.now() + timedelta(days=int(payload["valid_days"])) if payload.get("valid_days") else None,
                settlement_status="settled",
                payment_status="paid",
                card_source_type="approval",
                remark=f"approval_request={request.request_id}",
            )
            request.payload_json = {
                **payload,
                "approved_batch_id": batch.batch_id,
                "approved_card_count": len(cards),
            }

    async def approve_request(
        self,
        *,
        current_admin: AdminAccount,
        request_id: str,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with get_async_session() as session:
            row = await session.get(ApprovalRequest, (request_id or "").strip())
            if row is None:
                raise HTTPException(status_code=404, detail="审批单不存在")
            if row.status != "pending":
                raise HTTPException(status_code=409, detail="审批单已处理，请勿重复操作")
            if current_admin.role_code != ROLE_SUPER_ADMIN and int(row.approver_account_id) != int(current_admin.id):
                raise HTTPException(status_code=403, detail="无权审批该请求")
            operator = await session.get(AdminAccount, int(current_admin.id))
            await self._apply_approval_effect(session, row, operator)
            row.status = "approved"
            row.approved_at = datetime.now()
            await self._append_audit(
                session,
                actor=operator,
                action="agent.approve_request",
                target_type="approval_request",
                target_id=row.request_id,
                detail={"request_type": row.request_type},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(row)
            return self._serialize_approval_request(row)

    async def reject_request(
        self,
        *,
        current_admin: AdminAccount,
        request_id: str,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with get_async_session() as session:
            row = await session.get(ApprovalRequest, (request_id or "").strip())
            if row is None:
                raise HTTPException(status_code=404, detail="审批单不存在")
            if row.status != "pending":
                raise HTTPException(status_code=409, detail="审批单已处理，请勿重复操作")
            if current_admin.role_code != ROLE_SUPER_ADMIN and int(row.approver_account_id) != int(current_admin.id):
                raise HTTPException(status_code=403, detail="无权审批该请求")
            operator = await session.get(AdminAccount, int(current_admin.id))
            row.status = "rejected"
            row.rejected_at = datetime.now()
            await self._append_audit(
                session,
                actor=operator,
                action="agent.reject_request",
                target_type="approval_request",
                target_id=row.request_id,
                detail={"request_type": row.request_type},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(row)
            return self._serialize_approval_request(row)

    async def batch_process_requests(
        self,
        *,
        current_admin: AdminAccount,
        request_ids: Sequence[str],
        decision: str,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_ids = [str(item or "").strip() for item in request_ids if str(item or "").strip()]
        if not normalized_ids:
            raise HTTPException(status_code=400, detail="请选择要处理的审批单")
        if len(normalized_ids) > 50:
            raise HTTPException(status_code=400, detail="单次最多批量处理 50 个审批单")

        success_items: List[Dict[str, Any]] = []
        failed_items: List[Dict[str, Any]] = []
        for request_id in normalized_ids:
            try:
                if decision == "approve":
                    result = await self.approve_request(
                        current_admin=current_admin,
                        request_id=request_id,
                        ip_address=ip_address,
                    )
                else:
                    result = await self.reject_request(
                        current_admin=current_admin,
                        request_id=request_id,
                        ip_address=ip_address,
                    )
                success_items.append({"request_id": request_id, "result": result})
            except HTTPException as exc:
                failed_items.append({"request_id": request_id, "detail": exc.detail})
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.exception("批量审批失败: request_id={}", request_id)
                failed_items.append({"request_id": request_id, "detail": str(exc) or type(exc).__name__})

        return {
            "decision": decision,
            "success_count": len(success_items),
            "failed_count": len(failed_items),
            "success_items": success_items,
            "failed_items": failed_items,
        }

    async def handle_tg_approval_callback(self, *, tg_user_id: int, request_id: str, decision: str) -> Dict[str, Any]:
        async with get_async_session() as session:
            binding = (
                await session.execute(
                    select(AdminAccountTgBinding)
                    .where(
                        AdminAccountTgBinding.tg_user_id == int(tg_user_id),
                        AdminAccountTgBinding.bind_status == "bound",
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if binding is None:
                raise HTTPException(status_code=404, detail="当前 TG 账号未绑定后台账号")
            account = await session.get(AdminAccount, int(binding.admin_account_id))
        if decision == "approve":
            return await self.approve_request(current_admin=account, request_id=request_id)
        return await self.reject_request(current_admin=account, request_id=request_id)

    async def list_audit_logs(self, *, current_admin: AdminAccount, limit: int = 200) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            rows = (
                await session.execute(select(AdminAuditLog).order_by(AdminAuditLog.id.desc()).limit(max(1, min(500, int(limit)))))
            ).scalars().all()
            visible_ids = set(await self._visible_account_ids(session, current_admin))
        result: List[Dict[str, Any]] = []
        for row in rows:
            detail = row.detail or {}
            actor_account_id = detail.get("actor_account_id")
            if current_admin.role_code != ROLE_SUPER_ADMIN and actor_account_id is not None and int(actor_account_id) not in visible_ids:
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
        return result


_admin_panel_service: Optional[AdminPanelService] = None


def get_admin_panel_service() -> AdminPanelService:
    global _admin_panel_service
    if _admin_panel_service is None:
        _admin_panel_service = AdminPanelService()
    return _admin_panel_service
