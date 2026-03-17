"""TG account limit computation and enforcement."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account, PricingPlan, User, UserSubscription


@dataclass(frozen=True)
class TgAccountLimitSnapshot:
    """Effective TG account limit for a user."""

    user_id: int
    account_count: int
    plan_limit: Optional[int]
    override_limit: Optional[int]
    effective_limit: int

    @property
    def remaining_slots(self) -> Optional[int]:
        if self.effective_limit == 0:
            return None
        return max(0, int(self.effective_limit) - int(self.account_count))

    @property
    def is_at_limit(self) -> bool:
        return self.effective_limit > 0 and self.account_count >= self.effective_limit

    @property
    def is_over_limit(self) -> bool:
        return self.effective_limit > 0 and self.account_count > self.effective_limit

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_count": int(self.account_count),
            "plan_limit": self.plan_limit,
            "override_limit": self.override_limit,
            "effective_limit": int(self.effective_limit),
            "remaining_slots": self.remaining_slots,
            "is_at_limit": self.is_at_limit,
            "is_over_limit": self.is_over_limit,
        }


class TgAccountLimitExceededError(RuntimeError):
    """Raised when a user cannot add more TG accounts."""

    def __init__(self, snapshot: TgAccountLimitSnapshot):
        self.snapshot = snapshot
        limit_text = "不限制" if snapshot.effective_limit == 0 else str(snapshot.effective_limit)
        message = (
            f"当前账号最多可登录 {limit_text} 个 Telegram 账号，已达上限。"
            "现有账号可继续使用，但暂时不能新增账号。"
            "请删除闲置账号、升级套餐或联系管理员调整。"
        )
        super().__init__(message)


async def _get_latest_active_subscription(
    user_id: int,
    session: AsyncSession,
) -> Optional[UserSubscription]:
    now = datetime.now()
    result = await session.execute(
        select(UserSubscription)
        .where(
            and_(
                UserSubscription.user_id == int(user_id),
                UserSubscription.status == "active",
                UserSubscription.end_at > now,
            )
        )
        .order_by(UserSubscription.end_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _build_snapshot(
    user_id: int,
    session: AsyncSession,
) -> TgAccountLimitSnapshot:
    user = await session.get(User, int(user_id))
    if user is None:
        raise RuntimeError("用户不存在")

    count_result = await session.execute(
        select(func.count(Account.account_id))
        .where(
            and_(
                Account.user_id == int(user_id),
                Account.is_active.is_(True),
            )
        )
    )
    account_count = int(count_result.scalar_one() or 0)

    active_subscription = await _get_latest_active_subscription(int(user_id), session)
    plan_limit: Optional[int] = None
    if active_subscription and active_subscription.plan_code:
        plan = await session.get(PricingPlan, active_subscription.plan_code)
        if plan is not None:
            plan_limit = int(plan.max_tg_accounts or 0)

    override_limit = (
        int(user.max_tg_accounts_override)
        if user.max_tg_accounts_override is not None
        else None
    )
    effective_limit = int(override_limit if override_limit is not None else (plan_limit or 0))

    return TgAccountLimitSnapshot(
        user_id=int(user_id),
        account_count=account_count,
        plan_limit=plan_limit,
        override_limit=override_limit,
        effective_limit=effective_limit,
    )


async def get_tg_account_limit_snapshot(
    user_id: int,
    session: Optional[AsyncSession] = None,
) -> TgAccountLimitSnapshot:
    """Return effective TG account limit snapshot for a user."""
    if session is not None:
        return await _build_snapshot(user_id, session)

    async with get_async_session() as own_session:
        return await _build_snapshot(user_id, own_session)


async def ensure_can_add_tg_account(
    user_id: int,
    *,
    existing_tg_user_id: Optional[int] = None,
    session: Optional[AsyncSession] = None,
) -> TgAccountLimitSnapshot:
    """Ensure the user can add a new TG account.

    Rebinding the same TG account for the same user is always allowed.
    """
    if session is not None:
        return await _ensure_can_add_tg_account(user_id, existing_tg_user_id=existing_tg_user_id, session=session)

    async with get_async_session() as own_session:
        return await _ensure_can_add_tg_account(user_id, existing_tg_user_id=existing_tg_user_id, session=own_session)


async def _ensure_can_add_tg_account(
    user_id: int,
    *,
    existing_tg_user_id: Optional[int],
    session: AsyncSession,
) -> TgAccountLimitSnapshot:
    if existing_tg_user_id is not None:
        existing = await session.execute(
            select(Account.account_id)
            .where(
                and_(
                    Account.user_id == int(user_id),
                    Account.tg_user_id == int(existing_tg_user_id),
                )
            )
            .limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            return await _build_snapshot(user_id, session)

    snapshot = await _build_snapshot(user_id, session)
    if snapshot.is_at_limit:
        raise TgAccountLimitExceededError(snapshot)
    return snapshot
