"""AdminPanelService — thin facade delegating to domain services.

This module preserves backward compatibility: all existing callers
(`get_admin_panel_service().xxx(...)`) continue to work. Each method
delegates to the appropriate domain service extracted in this package.

Domain services:
  - agent_service.AgentHierarchyService
  - batch_service.CardBatchService
  - ledger_service.FundLedgerService
  - log_service.OperationLogService

Shared helpers live in shared_helpers.py.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.h5_backend.services.admin.service import get_admin_license_service
from backend.h5_backend.services.admin_panel.shared_helpers import (
    append_audit,
    serialize_pricing_plan,
)

# ---------------------------------------------------------------------------
# Constants (kept for backward compat; router imports MAX_COPY_CARD_COUNT)
# ---------------------------------------------------------------------------

MAX_COPY_CARD_COUNT = 40


class AdminPanelService:
    """Thin facade — delegates every method to the appropriate domain service."""

    # ------------------------------------------------------------------
    # Agent Hierarchy → agent_service.AgentHierarchyService
    # ------------------------------------------------------------------

    async def get_profile(self, current_admin) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.agent_service import get_agent_service
        return await get_agent_service().get_profile(current_admin)

    async def create_master_agent(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.agent_service import get_agent_service
        return await get_agent_service().create_master_agent(**kwargs)

    async def set_master_credit_limit(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.agent_service import get_agent_service
        return await get_agent_service().set_master_credit_limit(**kwargs)

    async def set_credit_whitelist(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.agent_service import get_agent_service
        return await get_agent_service().set_credit_whitelist(**kwargs)

    async def list_accounts(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.agent_service import get_agent_service
        return await get_agent_service().list_accounts(**kwargs)

    async def create_child_agent(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.agent_service import get_agent_service
        return await get_agent_service().create_child_agent(**kwargs)

    async def set_settlement_mode(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.agent_service import get_agent_service
        return await get_agent_service().set_settlement_mode(**kwargs)

    async def set_child_credit_limit(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.agent_service import get_agent_service
        return await get_agent_service().set_child_credit_limit(**kwargs)

    # ------------------------------------------------------------------
    # Card Batch → batch_service.CardBatchService
    # ------------------------------------------------------------------

    async def generate_card_batch(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.batch_service import get_batch_service
        return await get_batch_service().generate_card_batch(**kwargs)

    async def list_card_batches(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.batch_service import get_batch_service
        return await get_batch_service().list_card_batches(**kwargs)

    async def list_cards(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.batch_service import get_batch_service
        return await get_batch_service().list_cards(**kwargs)

    async def export_cards_xlsx(self, **kwargs):
        from backend.h5_backend.services.admin_panel.batch_service import get_batch_service
        return await get_batch_service().export_cards_xlsx(**kwargs)

    async def copy_cards(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.batch_service import get_batch_service
        return await get_batch_service().copy_cards(**kwargs)

    async def settle_credit_batch(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.batch_service import get_batch_service
        return await get_batch_service().settle_credit_batch(**kwargs)

    # ------------------------------------------------------------------
    # Fund Ledger → ledger_service.FundLedgerService
    # ------------------------------------------------------------------

    async def list_self_fund_ledgers(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.ledger_service import get_ledger_service
        return await get_ledger_service().list_self_fund_ledgers(**kwargs)

    async def list_visible_fund_ledgers(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.ledger_service import get_ledger_service
        return await get_ledger_service().list_visible_fund_ledgers(**kwargs)

    async def create_recharge_entry(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.ledger_service import get_ledger_service
        return await get_ledger_service().create_recharge_entry(**kwargs)

    # ------------------------------------------------------------------
    # Operation Logs → log_service.OperationLogService
    # ------------------------------------------------------------------

    async def list_operation_logs(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.log_service import get_log_service
        return await get_log_service().list_operation_logs(**kwargs)

    async def list_audit_logs(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin_panel.log_service import get_log_service
        return await get_log_service().list_audit_logs(**kwargs)

    # ------------------------------------------------------------------
    # Pricing Plans (stays here — small, ~70 lines)
    # ------------------------------------------------------------------

    async def list_plans(self) -> List[Dict[str, Any]]:
        return await get_admin_license_service().list_plans()

    async def list_pricing_plans(self, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        from backend.database.runtime.session import get_async_session
        from backend.database.schema.models import PricingPlan
        from backend.h5_backend.services.shared.pagination import normalize_page
        from sqlalchemy import func, select

        limit, offset = normalize_page(limit, offset)
        async with get_async_session() as session:
            total = int((await session.execute(select(func.count(PricingPlan.id)))).scalar_one() or 0)
            rows = (
                await session.execute(
                    select(PricingPlan)
                    .order_by(PricingPlan.sort_order.asc(), PricingPlan.price_cents.asc())
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars().all()
        return {
            "items": [serialize_pricing_plan(p) for p in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def update_pricing_plan(
        self,
        plan_code: str,
        *,
        display_name: Optional[str] = None,
        price_cents: Optional[int] = None,
        duration_days: Optional[int] = None,
        is_active: Optional[bool] = None,
        sort_order: Optional[int] = None,
        actor=None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        from backend.database.runtime.session import get_async_session
        from backend.database.schema.models import PricingPlan
        from fastapi import HTTPException

        async with get_async_session() as session:
            from sqlalchemy import select

            plan = (
                await session.execute(select(PricingPlan).where(PricingPlan.plan_code == plan_code).limit(1))
            ).scalar_one_or_none()
            if not plan:
                raise HTTPException(status_code=404, detail="规格不存在")
            old_value = serialize_pricing_plan(plan)
            if display_name is not None:
                plan.display_name = display_name.strip()
            if price_cents is not None:
                plan.price_cents = price_cents
            if duration_days is not None:
                plan.duration_days = duration_days
            if is_active is not None:
                plan.is_active = is_active
            if sort_order is not None:
                plan.sort_order = sort_order
            new_value = serialize_pricing_plan(plan)
            await append_audit(
                session,
                actor=actor,
                action="admin.update_plan",
                target_type="plan",
                target_id=plan_code,
                old_value=old_value,
                new_value=new_value,
                ip_address=ip_address,
            )
            await session.commit()
        return new_value


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_admin_panel_service: AdminPanelService | None = None


def get_admin_panel_service() -> AdminPanelService:
    """Get singleton admin panel service."""
    global _admin_panel_service
    if _admin_panel_service is None:
        _admin_panel_service = AdminPanelService()
    return _admin_panel_service
