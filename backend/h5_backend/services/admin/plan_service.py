"""Pricing-plan CRUD service extracted from AdminLicenseService."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import ActivationCard, PricingPlan
from backend.h5_backend.services.shared.audit import append_audit_log, mask_actor_name
from backend.h5_backend.services.shared.serializers import serialize_pricing_plan


class PlansService:
    """Isolated CRUD operations for pricing plans."""

    async def list_plans(self) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            result = await session.execute(
                select(PricingPlan)
                .where(PricingPlan.is_active.is_(True))
                .order_by(PricingPlan.sort_order.asc(), PricingPlan.price_cents.asc())
            )
            plans = result.scalars().all()
        return [serialize_pricing_plan(plan) for plan in plans]

    async def list_all_plans(self) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            result = await session.execute(
                select(PricingPlan).order_by(PricingPlan.sort_order.asc(), PricingPlan.price_cents.asc())
            )
            plans = result.scalars().all()
        return [serialize_pricing_plan(plan) for plan in plans]

    async def update_plan(
        self,
        plan_code: str,
        display_name: Optional[str] = None,
        billing_cycle: Optional[str] = None,
        price_cents: Optional[int] = None,
        duration_days: Optional[int] = None,
        is_active: Optional[bool] = None,
        sort_order: Optional[int] = None,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with get_async_session() as session:
            result = await session.execute(
                select(PricingPlan).where(PricingPlan.plan_code == plan_code).limit(1)
            )
            plan = result.scalar_one_or_none()
            if not plan:
                raise HTTPException(status_code=404, detail="套餐不存在")

            old_value = {
                "display_name": plan.display_name,
                "billing_cycle": plan.billing_cycle,
                "price_cents": plan.price_cents,
                "duration_days": plan.duration_days,
                "is_active": plan.is_active,
                "sort_order": plan.sort_order,
            }
            if display_name is not None:
                plan.display_name = display_name.strip() or plan.display_name
            if billing_cycle is not None:
                plan.billing_cycle = billing_cycle.strip() or plan.billing_cycle
            if price_cents is not None:
                if price_cents <= 0:
                    raise HTTPException(status_code=400, detail="price_cents 必须大于 0")
                plan.price_cents = price_cents
            if duration_days is not None:
                if duration_days <= 0:
                    raise HTTPException(status_code=400, detail="duration_days 必须大于 0")
                plan.duration_days = duration_days
            if is_active is not None:
                plan.is_active = is_active
            if sort_order is not None:
                plan.sort_order = sort_order

            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
                action="admin.update_plan",
                target_type="plan",
                target_id=plan_code,
                old_value=old_value,
                new_value={
                    "display_name": plan.display_name,
                    "billing_cycle": plan.billing_cycle,
                    "price_cents": plan.price_cents,
                    "duration_days": plan.duration_days,
                    "is_active": plan.is_active,
                    "sort_order": plan.sort_order,
                },
                detail={
                    "display_name": display_name,
                    "billing_cycle": billing_cycle,
                    "price_cents": price_cents,
                    "duration_days": duration_days,
                    "is_active": is_active,
                    "sort_order": sort_order,
                },
                ip_address=ip_address,
            )
            await session.commit()
            await session.refresh(plan)
            return serialize_pricing_plan(plan)

    async def create_plan(
        self,
        *,
        plan_code: str,
        display_name: str,
        billing_cycle: str,
        price_cents: int,
        duration_days: int,
        is_active: bool = True,
        sort_order: int = 0,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_code = (plan_code or "").strip()
        if not normalized_code:
            raise HTTPException(status_code=400, detail="plan_code 不能为空")
        if not (display_name or "").strip():
            raise HTTPException(status_code=400, detail="display_name 不能为空")
        if price_cents <= 0:
            raise HTTPException(status_code=400, detail="price_cents 必须大于 0")
        if duration_days <= 0:
            raise HTTPException(status_code=400, detail="duration_days 必须大于 0")

        async with get_async_session() as session:
            exists = (
                await session.execute(
                    select(PricingPlan).where(PricingPlan.plan_code == normalized_code).limit(1)
                )
            ).scalar_one_or_none()
            if exists:
                raise HTTPException(status_code=409, detail="卡密规格编码已存在")
            plan = PricingPlan(
                plan_code=normalized_code,
                display_name=display_name.strip(),
                billing_cycle=(billing_cycle or "custom").strip(),
                price_cents=int(price_cents),
                duration_days=int(duration_days),
                is_active=bool(is_active),
                sort_order=int(sort_order),
            )
            session.add(plan)
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
                action="admin.update_plan",
                target_type="plan",
                target_id=normalized_code,
                old_value=None,
                new_value=serialize_pricing_plan(plan),
                detail={"created": True},
                ip_address=ip_address,
            )
            await session.commit()
            await session.refresh(plan)
            return serialize_pricing_plan(plan)

    async def delete_plan(
        self,
        plan_code: str,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_code = (plan_code or "").strip()
        if not normalized_code:
            raise HTTPException(status_code=400, detail="plan_code 不能为空")

        async with get_async_session() as session:
            plan = await session.get(PricingPlan, normalized_code)
            if plan is None:
                raise HTTPException(status_code=404, detail="卡密规格不存在")

            unused_stmt = select(func.count(ActivationCard.id)).where(
                ActivationCard.plan_code == normalized_code,
                ActivationCard.is_used.is_(False),
            )
            used_stmt = select(func.count(ActivationCard.id)).where(
                ActivationCard.plan_code == normalized_code,
                ActivationCard.is_used.is_(True),
            )
            disabled_unused_cards = int((await session.execute(unused_stmt)).scalar_one() or 0)
            used_cards_kept = int((await session.execute(used_stmt)).scalar_one() or 0)

            if disabled_unused_cards:
                await session.execute(
                    ActivationCard.__table__.update()
                    .where(
                        ActivationCard.plan_code == normalized_code,
                        ActivationCard.is_used.is_(False),
                    )
                    .values(is_active=False)
                )

            plan_snapshot = serialize_pricing_plan(plan)
            await session.delete(plan)
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
                action="admin.delete_plan",
                target_type="plan",
                target_id=normalized_code,
                old_value=plan_snapshot,
                detail={
                    "disabled_unused_cards": disabled_unused_cards,
                    "used_cards_kept": used_cards_kept,
                },
                ip_address=ip_address,
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                logger.warning("删除卡密规格冲突: plan_code={}, error={}", normalized_code, exc)
                raise HTTPException(status_code=409, detail="删除卡密规格失败，请稍后重试") from exc
            except SQLAlchemyError as exc:
                await session.rollback()
                logger.exception("删除卡密规格异常: plan_code={}, error={}", normalized_code, exc)
                raise HTTPException(status_code=500, detail="删除卡密规格失败，请稍后重试") from exc

        return {
            "plan_code": normalized_code,
            "disabled_unused_cards": disabled_unused_cards,
            "used_cards_kept": used_cards_kept,
        }


_plan_service: PlansService | None = None


def get_plan_service() -> PlansService:
    global _plan_service
    if _plan_service is None:
        _plan_service = PlansService()
    return _plan_service
