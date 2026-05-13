"""Card batch generation, listing, export, and settlement service."""
from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence, Tuple
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.config.core.settings import settings
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    ActivationCard,
    AdminAccount,
    AgentCreditLimit,
    AgentFundLedger,
    CardBatch,
    PricingPlan,
)
from backend.h5_backend.services.admin_panel.shared_helpers import (
    has_permission,
    is_staff,
    is_agent,
    is_master_agent,
    visible_account_ids,
    append_audit,
    serialize_batch,
    serialize_card,
    build_plan_name_map_from_codes,
    build_account_name_map_from_ids,
    extract_batch_funding_source,
)
from backend.h5_backend.services.shared.card_utils import generate_card_code
from backend.h5_backend.services.shared.pagination import normalize_page
from backend.h5_backend.services.shared.search import LIKE_ESCAPE_CHAR, contains_like_pattern


MAX_COPY_CARD_COUNT = 40


class CardBatchService:
    """Extracted card-batch domain operations."""

    # ──────────────────── kept private helpers ────────────────────

    @staticmethod
    def _remaining_credit(account: AdminAccount) -> int:
        return max(0, int(account.credit_limit_cents or 0) - int(account.credit_used_cents or 0))

    def _ensure_credit_mode_allowed(self, account: AdminAccount) -> None:
        if account.settlement_mode not in {"credit", "hybrid"}:
            raise HTTPException(status_code=400, detail="当前账号未开启授信结算模式")
        if not account.is_credit_whitelisted:
            raise HTTPException(status_code=400, detail="当前账号未开通授信白名单")

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

        if is_staff(current_admin):
            allowed = True
        elif is_master_agent(current_admin) and int(target.root_master_account_id or 0) == int(current_admin.id):
            allowed = True
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
            raise HTTPException(status_code=400, detail="未找到该代理的授信额度配置")
        return parent, row

    # ──────────────────── internal batch helpers ────────────────────

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
            generated_codes.add(generate_card_code(prefix))
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
                generated_codes.add(generate_card_code(prefix))

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

    # ──────────────────── public API ────────────────────

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
        if not has_permission(current_admin, "batches.generate"):
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
            if is_staff(current_admin):
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
                remark=f"funding_source={'platform' if is_staff(current_admin) else normalized_funding_source}",
            )

            if is_staff(current_admin):
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

            await append_audit(
                session,
                actor=operator,
                action="agent.generate_card_batch",
                target_type="card_batch",
                target_id=batch.batch_id,
                detail={
                    "plan_code": quote["plan"].plan_code,
                    "quantity": int(quote["quantity"]),
                    "total_amount_cents": int(total_amount),
                    "funding_source": "platform" if is_staff(current_admin) else normalized_funding_source,
                },
                ip_address=ip_address,
            )
            await session.flush()

            return {
                "batch": serialize_batch(batch),
                "cards": [serialize_card(card) for card in cards],
                "copied_text": "\n".join(card.card_code for card in cards[-MAX_COPY_CARD_COUNT:]),
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
        limit, offset = normalize_page(limit, offset)
        async with get_async_session() as session:
            visible_ids = await visible_account_ids(session, current_admin)
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
                keyword_value = contains_like_pattern(normalized_keyword)
                keyword_condition = (
                    CardBatch.batch_id.ilike(keyword_value, escape=LIKE_ESCAPE_CHAR)
                    | CardBatch.plan_code.ilike(keyword_value, escape=LIKE_ESCAPE_CHAR)
                )
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
            counterparty_name_map = await build_account_name_map_from_ids(session, account_ids) if account_ids else {}
            plan_name_map = await build_plan_name_map_from_codes(
                session,
                {str(row.plan_code) for row in rows if row.plan_code},
            )
            items = [
                serialize_batch(
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
        limit, offset = normalize_page(limit, offset)
        async with get_async_session() as session:
            visible_ids = await visible_account_ids(session, current_admin)
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
                keyword_value = contains_like_pattern(normalized_keyword)
                keyword_condition = (
                    ActivationCard.card_code.ilike(keyword_value, escape=LIKE_ESCAPE_CHAR)
                    | ActivationCard.batch_id.ilike(keyword_value, escape=LIKE_ESCAPE_CHAR)
                    | ActivationCard.plan_code.ilike(keyword_value, escape=LIKE_ESCAPE_CHAR)
                )
                stmt = stmt.where(keyword_condition)
                count_stmt = count_stmt.where(keyword_condition)
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (
                await session.execute(
                    stmt.order_by(ActivationCard.created_at.desc(), ActivationCard.id.desc()).limit(limit).offset(offset)
                )
            ).scalars().all()
            plan_name_map = await build_plan_name_map_from_codes(
                session,
                {str(row.plan_code) for row in rows if row.plan_code},
            )
            return {
                "items": [
                    serialize_card(
                        row,
                        plan_display_name=plan_name_map.get(str(row.plan_code), str(row.plan_code or "")) if row.plan_code else None,
                    )
                    for row in rows
                ],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

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
        if len(normalized_ids) > MAX_COPY_CARD_COUNT:
            raise HTTPException(status_code=400, detail=f"单次最多复制 {MAX_COPY_CARD_COUNT} 个卡密，请改用导出 Excel")
        async with get_async_session() as session:
            visible_ids = set(await visible_account_ids(session, current_admin))
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
            visible_ids = await visible_account_ids(session, operator)
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
            await append_audit(
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
            return serialize_batch(batch)


# ──────────────────── module-level singleton ────────────────────

_batch_service: CardBatchService | None = None


def get_batch_service() -> CardBatchService:
    global _batch_service
    if _batch_service is None:
        _batch_service = CardBatchService()
    return _batch_service
