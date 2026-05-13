"""Operation-log and audit-log service extracted from AdminPanelService."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import func, select

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    AdminAccount,
    AdminAuditLog,
    AgentFundLedger,
    CardBatch,
)
from backend.h5_backend.services.admin_panel.shared_helpers import (
    has_permission,
    visible_account_ids,
    parse_datetime_filter,
    extract_batch_funding_source,
    build_account_name_map_from_ids,
    build_plan_name_map_from_codes,
    serialize_operation_log,
)
from backend.h5_backend.services.shared.pagination import normalize_page
from backend.h5_backend.services.shared.search import LIKE_ESCAPE_CHAR, contains_like_pattern


class OperationLogService:
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
        limit, offset = normalize_page(limit, offset)
        normalized_type = (log_type or "").strip().lower()
        if normalized_type and normalized_type not in {"all", "recharge", "card_generate", "credit_settlement"}:
            raise HTTPException(status_code=400, detail="不支持的操作日志类型")
        normalized_keyword = (keyword or "").strip().lower()
        started_at = parse_datetime_filter(date_from)
        ended_at = parse_datetime_filter(date_to, is_end=True)
        if started_at and ended_at and started_at >= ended_at:
            raise HTTPException(status_code=400, detail="时间范围无效")

        async with get_async_session() as session:
            visible_ids = await visible_account_ids(session, current_admin) if scope_only else [int(current_admin.id)]
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
                    funding_source = extract_batch_funding_source(row)
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

            account_name_map = await build_account_name_map_from_ids(session, account_name_ids)
            for item in items:
                item["operator_name"] = account_name_map.get(int(item["operator_account_id"])) if item.get("operator_account_id") else None
                item["subject_name"] = account_name_map.get(int(item["subject_account_id"])) if item.get("subject_account_id") else None
                item["counterparty_name"] = account_name_map.get(int(item["counterparty_account_id"])) if item.get("counterparty_account_id") else None
            plan_name_map = await build_plan_name_map_from_codes(
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
                "items": [serialize_operation_log(item) for item in paged_items],
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
        limit, offset = normalize_page(limit, offset)
        total = 0
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
                keyword_value = contains_like_pattern(normalized_keyword)
                keyword_condition = (
                    AdminAuditLog.actor.ilike(keyword_value, escape=LIKE_ESCAPE_CHAR)
                    | AdminAuditLog.action.ilike(keyword_value, escape=LIKE_ESCAPE_CHAR)
                    | AdminAuditLog.target_id.ilike(keyword_value, escape=LIKE_ESCAPE_CHAR)
                )
                stmt = stmt.where(keyword_condition)
                count_stmt = count_stmt.where(keyword_condition)
            visible_ids = set(await visible_account_ids(session, current_admin))
            can_read_system_audit = has_permission(current_admin, "audit.system.read")
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


_log_service: OperationLogService | None = None


def get_log_service() -> OperationLogService:
    global _log_service
    if _log_service is None:
        _log_service = OperationLogService()
    return _log_service
