"""Profile, subscription and card activation service."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import ActivationCard, AppSetting, PricingPlan, User, UserSubscription
from backend.h5_backend.services.auth.service import get_auth_service

DEFAULT_PURCHASE_URL = "https://t.me/"
DEFAULT_PURCHASE_BUTTON_TEXT = "联系 Telegram 购买"


class MeService:
    """Business service for 'My' page."""

    @staticmethod
    def _to_price_yuan(price_cents: int) -> str:
        return f"{(Decimal(price_cents) / Decimal(100)).quantize(Decimal('0.00'))}"

    @staticmethod
    def _serialize_plan(plan: PricingPlan) -> Dict[str, Any]:
        return {
            "plan_code": plan.plan_code,
            "display_name": plan.display_name,
            "billing_cycle": plan.billing_cycle,
            "price_cents": plan.price_cents,
            "price_yuan": MeService._to_price_yuan(plan.price_cents),
            "duration_days": plan.duration_days,
            "is_active": plan.is_active,
            "sort_order": plan.sort_order,
        }

    @staticmethod
    def _serialize_subscription(subscription: Optional[UserSubscription]) -> Optional[Dict[str, Any]]:
        if subscription is None:
            return None
        return {
            "id": subscription.id,
            "plan_code": subscription.plan_code,
            "source": subscription.source,
            "card_code": subscription.card_code,
            "start_at": subscription.start_at.isoformat() if subscription.start_at else None,
            "end_at": subscription.end_at.isoformat() if subscription.end_at else None,
            "status": subscription.status,
        }

    async def get_active_subscription(self, user_id: int) -> Optional[UserSubscription]:
        now = datetime.now()
        async with get_async_session() as session:
            # 先把过期的 active 状态修正，避免页面状态漂移
            await session.execute(
                UserSubscription.__table__.update()
                .where(
                    and_(
                        UserSubscription.user_id == user_id,
                        UserSubscription.status == "active",
                        UserSubscription.end_at <= now,
                    )
                )
                .values(status="expired")
            )

            result = await session.execute(
                select(UserSubscription)
                .where(
                    and_(
                        UserSubscription.user_id == user_id,
                        UserSubscription.status == "active",
                        UserSubscription.end_at > now,
                    )
                )
                .order_by(UserSubscription.end_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def list_active_plans(self) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            result = await session.execute(
                select(PricingPlan)
                .where(PricingPlan.is_active.is_(True))
                .order_by(PricingPlan.sort_order.asc(), PricingPlan.price_cents.asc())
            )
            plans = result.scalars().all()
            return [self._serialize_plan(plan) for plan in plans]

    async def get_purchase_entry(self) -> Dict[str, str]:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(AppSetting).where(AppSetting.key.in_(["purchase_url", "purchase_button_text"]))
                )
            ).scalars().all()
            values = {row.key: row.value for row in rows}
            return {
                "url": (values.get("purchase_url") or DEFAULT_PURCHASE_URL).strip(),
                "button_text": (values.get("purchase_button_text") or DEFAULT_PURCHASE_BUTTON_TEXT).strip(),
            }

    async def get_profile(self, user_id: int) -> Dict[str, Any]:
        active_subscription = await self.get_active_subscription(user_id)
        plans = await self.list_active_plans()
        purchase = await self.get_purchase_entry()

        async with get_async_session() as session:
            user_result = await session.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")

        now = datetime.now()
        remain_days = None
        if active_subscription and active_subscription.end_at:
            remain_days = max(0, int((active_subscription.end_at - now).total_seconds() // 86400))

        return {
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            },
            "subscription": {
                "is_active": active_subscription is not None,
                "current": self._serialize_subscription(active_subscription),
                "remain_days": remain_days,
            },
            "plans": plans,
            "purchase": purchase,
        }

    async def get_subscription_status(self, user_id: int) -> Dict[str, Any]:
        active_subscription = await self.get_active_subscription(user_id)
        plans = await self.list_active_plans()
        purchase = await self.get_purchase_entry()
        now = datetime.now()
        remain_days = None
        if active_subscription and active_subscription.end_at:
            remain_days = max(0, int((active_subscription.end_at - now).total_seconds() // 86400))
        return {
            "is_active": active_subscription is not None,
            "current": self._serialize_subscription(active_subscription),
            "remain_days": remain_days,
            "plans": plans,
            "purchase": purchase,
        }

    async def require_active_subscription(self, user_id: int) -> None:
        status_data = await self.get_subscription_status(user_id)
        if status_data["is_active"]:
            return

        plan_text = "；".join(
            [f"{plan['display_name']} {plan['price_yuan']}元" for plan in status_data["plans"]]
        )
        detail = "当前账号未开通付费服务，请前往“我的”页面激活卡密后再添加账号。"
        if plan_text:
            detail = f"{detail} 当前套餐：{plan_text}"
        purchase_url = ((status_data.get("purchase") or {}).get("url") or "").strip()
        if purchase_url:
            detail = f"{detail} 购买入口：{purchase_url}"
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=detail)

    async def activate_card(self, user_id: int, card_code: str) -> Dict[str, Any]:
        normalized_code = (card_code or "").strip().upper()
        if not normalized_code:
            raise HTTPException(status_code=400, detail="卡密不能为空")

        now = datetime.now()
        async with get_async_session() as session:
            result = await session.execute(
                select(ActivationCard)
                .where(func.upper(ActivationCard.card_code) == normalized_code)
                .limit(1)
            )
            card = result.scalar_one_or_none()
            if not card:
                raise HTTPException(status_code=404, detail="卡密不存在")
            if not card.is_active:
                raise HTTPException(status_code=400, detail="卡密已失效")
            if card.is_used:
                raise HTTPException(status_code=400, detail="卡密已被使用")
            if card.expires_at and card.expires_at <= now:
                raise HTTPException(status_code=400, detail="卡密已过期")

            plan = None
            if card.plan_code:
                plan_result = await session.execute(
                    select(PricingPlan).where(PricingPlan.plan_code == card.plan_code).limit(1)
                )
                plan = plan_result.scalar_one_or_none()

            duration_days = card.duration_days or (plan.duration_days if plan else 0)
            if duration_days <= 0:
                raise HTTPException(status_code=400, detail="卡密配置异常：时长无效")

            sub_result = await session.execute(
                select(UserSubscription)
                .where(
                    and_(
                        UserSubscription.user_id == user_id,
                        UserSubscription.status == "active",
                    )
                )
                .order_by(UserSubscription.end_at.desc())
                .limit(1)
            )
            active_sub = sub_result.scalar_one_or_none()
            if active_sub and active_sub.end_at <= now:
                active_sub.status = "expired"
                active_sub = None

            if active_sub is None:
                new_subscription = UserSubscription(
                    user_id=user_id,
                    plan_code=card.plan_code,
                    source="card",
                    card_code=card.card_code,
                    start_at=now,
                    end_at=now + timedelta(days=duration_days),
                    status="active",
                )
                session.add(new_subscription)
            else:
                active_sub.end_at = active_sub.end_at + timedelta(days=duration_days)
                if card.plan_code:
                    active_sub.plan_code = card.plan_code
                active_sub.source = "card"
                active_sub.card_code = card.card_code

            card.is_used = True
            card.used_by_user_id = user_id
            card.used_at = now

            await session.commit()

        return await self.get_subscription_status(user_id)

    async def change_password(self, user_id: int, old_password: str, new_password: str) -> None:
        auth_service = get_auth_service()
        async with get_async_session() as session:
            result = await session.execute(select(User).where(User.id == user_id).limit(1))
            user = result.scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")

            if not auth_service.verify_password(old_password, user.password_hash):
                raise HTTPException(status_code=400, detail="原密码错误")

            user.password_hash = auth_service.get_password_hash(new_password)
            await session.commit()

    async def update_profile(self, user_id: int, email: Optional[str]) -> Dict[str, Any]:
        """Update editable profile fields for current user."""
        normalized_email = (email or "").strip().lower()
        if normalized_email == "":
            normalized_email = None

        if normalized_email and len(normalized_email) > 100:
            raise HTTPException(status_code=400, detail="邮箱长度不能超过 100")

        async with get_async_session() as session:
            result = await session.execute(select(User).where(User.id == user_id).limit(1))
            user = result.scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")

            if normalized_email:
                exists = await session.execute(
                    select(User.id)
                    .where(and_(User.id != user_id, func.lower(User.email) == normalized_email))
                    .limit(1)
                )
                if exists.scalar_one_or_none() is not None:
                    raise HTTPException(status_code=400, detail="邮箱已被占用")

            user.email = normalized_email
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise HTTPException(status_code=400, detail="邮箱已被占用") from exc
            await session.refresh(user)

            return {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "is_active": user.is_active,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }


_me_service: Optional[MeService] = None


def get_me_service() -> MeService:
    """Get singleton me service."""
    global _me_service
    if _me_service is None:
        _me_service = MeService()
    return _me_service
