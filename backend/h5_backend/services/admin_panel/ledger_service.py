"""Fund ledger service extracted from AdminPanelService."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import func, select

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import AdminAccount, AgentFundLedger
from backend.h5_backend.services.admin_panel.shared_helpers import (
    is_staff,
    is_agent,
    visible_account_ids,
    ensure_visible_account,
    append_audit,
    serialize_fund_ledger,
    serialize_admin_account,
    build_account_name_map,
)
from backend.h5_backend.services.shared.pagination import normalize_page
from backend.h5_backend.services.admin_panel.batch_service import get_batch_service


class FundLedgerService:
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
        limit, offset = normalize_page(limit, offset)
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
            account_map = await build_account_name_map(session, rows)
            items = [
                serialize_fund_ledger(
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
        limit, offset = normalize_page(limit, offset)
        async with get_async_session() as session:
            visible_ids = await visible_account_ids(session, current_admin)
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
            account_map = await build_account_name_map(session, rows)
            items = [
                serialize_fund_ledger(
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
            subject = await ensure_visible_account(session, operator, int(subject_account_id))
            if not is_agent(subject):
                raise HTTPException(status_code=400, detail="只能为代理账号直接充值入账")
            if not is_staff(operator) and int(subject.parent_account_id or 0) != int(operator.id):
                raise HTTPException(status_code=403, detail="只能为直系下级直接充值入账")

            subject.credit_prepay_cents = int(getattr(subject, "credit_prepay_cents", 0) or 0) + amount
            settled_credit_amount, settled_batch_ids = await get_batch_service()._auto_settle_credit_batches_for_recharge(
                session,
                subject=subject,
                operator=operator,
            )
            has_pending_credit_batches = await get_batch_service()._has_pending_credit_batches(
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
                    ledger_scope="platform" if is_staff(operator) else "channel",
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
            await append_audit(
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
            return serialize_admin_account(subject)


_ledger_service: FundLedgerService | None = None


def get_ledger_service() -> FundLedgerService:
    global _ledger_service
    if _ledger_service is None:
        _ledger_service = FundLedgerService()
    return _ledger_service
