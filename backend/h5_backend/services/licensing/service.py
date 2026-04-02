"""Slot-based licensing service for TG auto-send capability."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    Account,
    ActivationCard,
    PricingPlan,
    SlotNoticeLog,
    User,
    UserLicenseSlot,
    UserLicenseSlotBinding,
    UserLicenseSlotCard,
)

BOT_TRIAL_DURATION_DAYS = 7
GRANT_SOURCE_CARD = "card"
GRANT_SOURCE_BOT_TRIAL = "bot_trial"

@dataclass(frozen=True)
class AccountAuthorizationSummary:
    account_id: str
    slot_id: Optional[str]
    license_status: str
    can_create_tasks: bool
    license_end_at: Optional[datetime]
    license_key_count: int
    slot_grant_source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "license_status": self.license_status,
            "can_create_tasks": self.can_create_tasks,
            "license_end_at": self.license_end_at.isoformat() if self.license_end_at else None,
            "license_key_count": int(self.license_key_count),
            "slot_grant_source": self.slot_grant_source,
            "slot_grant_source_label": _grant_source_label(self.slot_grant_source),
        }


@dataclass(frozen=True)
class SlotOverview:
    slot_id: str
    account_id: Optional[str]
    account_name: Optional[str]
    status: str
    duration_days: int
    start_at: datetime
    end_at: datetime
    card_count: int
    remaining_days: int
    grant_source: Optional[str]
    source_card_code_masked: Optional[str]
    latest_card_code_masked: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "account_id": self.account_id,
            "account_name": self.account_name,
            "status": self.status,
            "duration_days": int(self.duration_days),
            "start_at": self.start_at.isoformat() if self.start_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
            "card_count": int(self.card_count),
            "remaining_days": int(self.remaining_days),
            "grant_source": self.grant_source,
            "grant_source_label": _grant_source_label(self.grant_source),
            "source_card_code_masked": self.source_card_code_masked,
            "latest_card_code_masked": self.latest_card_code_masked,
        }


@dataclass(frozen=True)
class LicenseOverview:
    user_id: int
    account_count: int
    slot_count: int
    active_slot_count: int
    unbound_active_slot_count: int
    remaining_slots: int
    has_active_license: bool
    next_expiring_at: Optional[datetime]

    @property
    def login_capacity(self) -> int:
        return max(1, int(self.active_slot_count))

    @property
    def remaining_login_slots(self) -> int:
        return max(0, self.login_capacity - int(self.account_count))

    @property
    def is_at_limit(self) -> bool:
        return self.account_count >= self.login_capacity

    @property
    def is_over_limit(self) -> bool:
        return self.account_count > self.login_capacity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_count": int(self.account_count),
            "slot_count": int(self.slot_count),
            "active_slot_count": int(self.active_slot_count),
            "unbound_active_slot_count": int(self.unbound_active_slot_count),
            "remaining_slots": int(self.remaining_slots),
            "login_capacity": int(self.login_capacity),
            "remaining_login_slots": int(self.remaining_login_slots),
            "is_at_limit": self.is_at_limit,
            "is_over_limit": self.is_over_limit,
            "has_active_license": bool(self.has_active_license),
            "next_expiring_at": self.next_expiring_at.isoformat() if self.next_expiring_at else None,
        }


def _mask_card_code(card_code: Optional[str]) -> Optional[str]:
    value = (card_code or "").strip()
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}****{value[-4:]}"


def _grant_source_label(grant_source: Optional[str]) -> str:
    if grant_source == GRANT_SOURCE_BOT_TRIAL:
        return "Bot 首绑试用"
    return "卡密激活"


class TgAccountLimitExceededError(RuntimeError):
    def __init__(self, overview: LicenseOverview):
        self.overview = overview
        if overview.active_slot_count <= 0:
            message = (
                "当前未激活 Key 时，最多只能登录 1 个 TG 账号用于查看和管理。"
                "如需继续新增账号，请先激活新的 Key，或删除当前已登录账号后再切换。"
            )
        else:
            message = (
                "当前有效套餐位数量不足，无法新增 TG 账号。"
                "请先激活新的 Key，或释放已有套餐位绑定账号。"
            )
        super().__init__(message)


async def _count_active_accounts(user_id: int, session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count(Account.account_id)).where(
            and_(
                Account.user_id == int(user_id),
                Account.is_active.is_(True),
            )
        )
    )
    return int(result.scalar_one() or 0)


async def _resolve_card_duration_days(card: ActivationCard, session: AsyncSession) -> int:
    duration_days = int(card.duration_days or 0)
    if duration_days <= 0 and card.plan_code:
        plan = await session.get(PricingPlan, card.plan_code)
        duration_days = int(getattr(plan, "duration_days", 0) or 0)
    return max(0, duration_days)


async def _choose_legacy_bind_account(user_id: int, session: AsyncSession) -> Optional[str]:
    now = datetime.now()
    accounts = (
        await session.execute(
            select(Account).where(
                Account.user_id == int(user_id),
                Account.is_active.is_(True),
            ).order_by(Account.created_at.asc())
        )
    ).scalars().all()
    if len(accounts) != 1:
        return None

    account_id = str(accounts[0].account_id)
    existing_slot = (
        await session.execute(
            select(UserLicenseSlot.slot_id).where(
                UserLicenseSlot.current_account_id == account_id,
                UserLicenseSlot.status == "active",
                UserLicenseSlot.end_at > now,
            ).limit(1)
        )
    ).scalar_one_or_none()
    if existing_slot is not None:
        return None
    return account_id


async def _backfill_legacy_used_cards(
    session: AsyncSession,
    *,
    user_id: Optional[int] = None,
) -> int:
    """
    Repair legacy key data by converting already-used old cards into slot rows.

    Older environments may have `activation_cards.is_used=true` with no slot records yet.
    We backfill one slot per used card so the new licensing model can see historical data.
    """
    stmt = (
        select(ActivationCard)
        .outerjoin(
            UserLicenseSlotCard,
            UserLicenseSlotCard.activation_card_id == ActivationCard.id,
        )
        .where(
            ActivationCard.is_used.is_(True),
            ActivationCard.used_by_user_id.is_not(None),
            UserLicenseSlotCard.id.is_(None),
        )
        .order_by(ActivationCard.id.asc())
    )
    if user_id is not None:
        stmt = stmt.where(ActivationCard.used_by_user_id == int(user_id))

    cards = (await session.execute(stmt)).scalars().all()
    if not cards:
        return 0

    now = datetime.now()
    created = 0
    for card in cards:
        duration_days = await _resolve_card_duration_days(card, session)
        if duration_days <= 0:
            continue

        bind_account_id = await _choose_legacy_bind_account(int(card.used_by_user_id), session)
        start_at = card.used_at or card.created_at or now
        end_at = start_at + timedelta(days=duration_days)
        status = "active" if end_at > now else "expired"

        slot = UserLicenseSlot(
            user_id=int(card.used_by_user_id),
            current_account_id=bind_account_id,
            source_card_id=card.id,
            total_duration_days=duration_days,
            start_at=start_at,
            end_at=end_at,
            status=status,
        )
        session.add(slot)
        await session.flush()

        session.add(
            UserLicenseSlotCard(
                slot_id=slot.slot_id,
                activation_card_id=card.id,
                duration_days=duration_days,
                applied_at=start_at,
            )
        )
        if bind_account_id:
            session.add(
                UserLicenseSlotBinding(
                    slot_id=slot.slot_id,
                    account_id=bind_account_id,
                    bind_at=start_at,
                )
            )
        created += 1

    if created:
        await session.flush()
    return created


async def _sync_expired_slots(session: AsyncSession, *, user_id: Optional[int] = None) -> None:
    now = datetime.now()
    stmt = select(UserLicenseSlot).where(
        UserLicenseSlot.status == "active",
        UserLicenseSlot.end_at <= now,
    )
    if user_id is not None:
        stmt = stmt.where(UserLicenseSlot.user_id == int(user_id))

    rows = (await session.execute(stmt)).scalars().all()
    updated = False
    for slot in rows:
        if slot.status != "expired":
            slot.status = "expired"
            updated = True
    if updated:
        await session.flush()


async def mark_bot_trial_eligible_on_first_bind(
    *,
    user_id: int,
    session: Optional[AsyncSession] = None,
) -> bool:
    if session is not None:
        return await _mark_bot_trial_eligible_on_first_bind(user_id=user_id, session=session)
    async with get_async_session() as own_session:
        marked = await _mark_bot_trial_eligible_on_first_bind(user_id=user_id, session=own_session)
        await own_session.commit()
        return marked


async def _mark_bot_trial_eligible_on_first_bind(
    *,
    user_id: int,
    session: AsyncSession,
) -> bool:
    user = await session.get(User, int(user_id))
    if user is None:
        return False
    if user.bot_trial_eligible_at or user.bot_trial_granted_at or user.bot_trial_slot_id:
        return False

    slot_exists = await session.execute(
        select(UserLicenseSlot.slot_id).where(UserLicenseSlot.user_id == int(user_id)).limit(1)
    )
    if slot_exists.scalar_one_or_none() is not None:
        return False

    used_card_exists = await session.execute(
        select(ActivationCard.id).where(
            ActivationCard.used_by_user_id == int(user_id),
            ActivationCard.is_used.is_(True),
        ).limit(1)
    )
    if used_card_exists.scalar_one_or_none() is not None:
        return False

    user.bot_trial_eligible_at = datetime.now()
    await session.flush()
    return True


async def grant_bot_trial_slot_if_eligible(
    *,
    user_id: int,
    account_id: str,
    session: Optional[AsyncSession] = None,
) -> Optional[UserLicenseSlot]:
    if session is not None:
        return await _grant_bot_trial_slot_if_eligible(user_id=user_id, account_id=account_id, session=session)
    async with get_async_session() as own_session:
        slot = await _grant_bot_trial_slot_if_eligible(user_id=user_id, account_id=account_id, session=own_session)
        await own_session.commit()
        return slot


async def _grant_bot_trial_slot_if_eligible(
    *,
    user_id: int,
    account_id: str,
    session: AsyncSession,
) -> Optional[UserLicenseSlot]:
    user = await session.get(User, int(user_id))
    if user is None:
        return None
    if not user.bot_trial_eligible_at or user.bot_trial_granted_at or user.bot_trial_slot_id:
        return None

    account = await session.get(Account, str(account_id))
    if account is None or int(account.user_id) != int(user_id):
        return None

    existing_slot_count = (
        await session.execute(
            select(func.count(UserLicenseSlot.slot_id)).where(UserLicenseSlot.user_id == int(user_id))
        )
    ).scalar_one()
    # 若用户在首次绑定 Bot 后、首次绑定 TG 账号前已自行购入/生成套餐位，
    # 则不再额外赠送试用，避免同一账号叠加双重授权。
    if int(existing_slot_count or 0) > 0:
        user.bot_trial_eligible_at = None
        await session.flush()
        return None

    now = datetime.now()
    slot = UserLicenseSlot(
        user_id=int(user_id),
        current_account_id=str(account_id),
        source_card_id=None,
        grant_source=GRANT_SOURCE_BOT_TRIAL,
        total_duration_days=BOT_TRIAL_DURATION_DAYS,
        start_at=now,
        end_at=now + timedelta(days=BOT_TRIAL_DURATION_DAYS),
        status="active",
    )
    session.add(slot)
    await session.flush()
    session.add(
        UserLicenseSlotBinding(
            slot_id=slot.slot_id,
            account_id=str(account_id),
            bind_at=now,
        )
    )
    user.bot_trial_granted_at = now
    user.bot_trial_slot_id = slot.slot_id
    await session.flush()
    return slot


async def _build_license_overview(user_id: int, session: AsyncSession) -> LicenseOverview:
    await _backfill_legacy_used_cards(session, user_id=user_id)
    await _sync_expired_slots(session, user_id=user_id)
    now = datetime.now()

    account_count = await _count_active_accounts(user_id, session)
    slot_rows = (
        await session.execute(
            select(UserLicenseSlot).where(UserLicenseSlot.user_id == int(user_id))
        )
    ).scalars().all()

    slot_count = len(slot_rows)
    active_slots = [slot for slot in slot_rows if slot.status == "active" and slot.end_at > now]
    active_slot_count = len(active_slots)
    unbound_active_slot_count = len([slot for slot in active_slots if not slot.current_account_id])
    next_expiring_at = min((slot.end_at for slot in active_slots), default=None)

    remaining_slots = max(0, active_slot_count - account_count)

    return LicenseOverview(
        user_id=int(user_id),
        account_count=account_count,
        slot_count=slot_count,
        active_slot_count=active_slot_count,
        unbound_active_slot_count=unbound_active_slot_count,
        remaining_slots=remaining_slots,
        has_active_license=active_slot_count > 0,
        next_expiring_at=next_expiring_at,
    )


async def get_license_overview(
    user_id: int,
    session: Optional[AsyncSession] = None,
) -> LicenseOverview:
    if session is not None:
        return await _build_license_overview(user_id, session)
    async with get_async_session() as own_session:
        return await _build_license_overview(user_id, own_session)


async def ensure_can_add_tg_account(
    user_id: int,
    *,
    existing_tg_user_id: Optional[int] = None,
    session: Optional[AsyncSession] = None,
) -> LicenseOverview:
    if session is not None:
        return await _ensure_can_add_tg_account(user_id, existing_tg_user_id=existing_tg_user_id, session=session)
    async with get_async_session() as own_session:
        return await _ensure_can_add_tg_account(user_id, existing_tg_user_id=existing_tg_user_id, session=own_session)


async def _ensure_can_add_tg_account(
    user_id: int,
    *,
    existing_tg_user_id: Optional[int],
    session: AsyncSession,
) -> LicenseOverview:
    if existing_tg_user_id is not None:
        existing = await session.execute(
            select(Account.account_id).where(
                Account.user_id == int(user_id),
                Account.tg_user_id == int(existing_tg_user_id),
            )
        )
        if existing.scalar_one_or_none() is not None:
            return await _build_license_overview(user_id, session)

    overview = await _build_license_overview(user_id, session)
    if overview.account_count >= overview.login_capacity:
        raise TgAccountLimitExceededError(overview)
    return overview


async def list_user_slots(user_id: int, session: Optional[AsyncSession] = None) -> List[SlotOverview]:
    if session is not None:
        return await _list_user_slots(user_id, session)
    async with get_async_session() as own_session:
        return await _list_user_slots(user_id, own_session)


async def _list_user_slots(user_id: int, session: AsyncSession) -> List[SlotOverview]:
    await _sync_expired_slots(session, user_id=user_id)
    rows = (
        await session.execute(
            select(UserLicenseSlot).where(UserLicenseSlot.user_id == int(user_id)).order_by(UserLicenseSlot.end_at.asc())
        )
    ).scalars().all()
    now = datetime.now()
    items: List[SlotOverview] = []
    for slot in rows:
        account_name = None
        if slot.current_account_id:
            account = await session.get(Account, str(slot.current_account_id))
            if account is not None:
                account_name = (
                    f"@{account.username}" if account.username
                    else (account.phone or (str(account.tg_user_id) if account.tg_user_id else None))
                )

        card_count = (
            await session.execute(
                select(func.count(UserLicenseSlotCard.id)).where(UserLicenseSlotCard.slot_id == slot.slot_id)
            )
        ).scalar_one()
        card_rows = (
            await session.execute(
                select(UserLicenseSlotCard, ActivationCard.card_code)
                .join(ActivationCard, ActivationCard.id == UserLicenseSlotCard.activation_card_id)
                .where(UserLicenseSlotCard.slot_id == slot.slot_id)
                .order_by(UserLicenseSlotCard.applied_at.asc(), UserLicenseSlotCard.id.asc())
            )
        ).all()
        source_card_code_masked = _mask_card_code(card_rows[0][1]) if card_rows else None
        latest_card_code_masked = _mask_card_code(card_rows[-1][1]) if card_rows else None
        remaining_days = max(0, int((slot.end_at - now).total_seconds() // 86400)) if slot.end_at else 0
        items.append(
            SlotOverview(
                slot_id=slot.slot_id,
                account_id=slot.current_account_id,
                account_name=account_name,
                status=slot.status,
                duration_days=int(slot.total_duration_days or 0),
                start_at=slot.start_at,
                end_at=slot.end_at,
                card_count=int(card_count or 0),
                remaining_days=remaining_days,
                grant_source=getattr(slot, "grant_source", None),
                source_card_code_masked=source_card_code_masked,
                latest_card_code_masked=latest_card_code_masked,
            )
        )
    return items


async def get_account_authorization_summary(
    account_id: str,
    session: Optional[AsyncSession] = None,
) -> AccountAuthorizationSummary:
    if session is not None:
        return await _get_account_authorization_summary(account_id, session)
    async with get_async_session() as own_session:
        return await _get_account_authorization_summary(account_id, own_session)


async def _get_account_authorization_summary(
    account_id: str,
    session: AsyncSession,
) -> AccountAuthorizationSummary:
    account = await session.get(Account, str(account_id))
    if account is not None:
        await _backfill_legacy_used_cards(session, user_id=int(account.user_id))
    await _sync_expired_slots(session)
    now = datetime.now()
    slot = (
        await session.execute(
            select(UserLicenseSlot)
            .where(
                UserLicenseSlot.current_account_id == str(account_id),
                UserLicenseSlot.status == "active",
                UserLicenseSlot.end_at > now,
            )
            .order_by(UserLicenseSlot.end_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if slot is None:
        expired_slot = (
            await session.execute(
                select(UserLicenseSlot)
                .where(UserLicenseSlot.current_account_id == str(account_id))
                .order_by(UserLicenseSlot.end_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if expired_slot is not None:
            card_count = (
                await session.execute(
                    select(func.count(UserLicenseSlotCard.id)).where(UserLicenseSlotCard.slot_id == expired_slot.slot_id)
                )
            ).scalar_one()
            return AccountAuthorizationSummary(
                account_id=str(account_id),
                slot_id=expired_slot.slot_id,
                license_status="expired" if expired_slot.end_at <= now else expired_slot.status,
                can_create_tasks=False,
                license_end_at=expired_slot.end_at,
                license_key_count=int(card_count or 0),
                slot_grant_source=getattr(expired_slot, "grant_source", None),
            )
        return AccountAuthorizationSummary(
            account_id=str(account_id),
            slot_id=None,
            license_status="unlicensed",
            can_create_tasks=False,
            license_end_at=None,
            license_key_count=0,
            slot_grant_source=None,
        )

    card_count = (
        await session.execute(
            select(func.count(UserLicenseSlotCard.id)).where(UserLicenseSlotCard.slot_id == slot.slot_id)
        )
    ).scalar_one()
    return AccountAuthorizationSummary(
        account_id=str(account_id),
        slot_id=slot.slot_id,
        license_status="licensed",
        can_create_tasks=True,
        license_end_at=slot.end_at,
        license_key_count=int(card_count or 0),
        slot_grant_source=getattr(slot, "grant_source", None),
    )


async def require_account_task_permission(
    account_id: Optional[str],
    *,
    session: Optional[AsyncSession] = None,
    action_text: str = "创建或执行自动发送任务",
) -> AccountAuthorizationSummary:
    if not account_id:
        raise HTTPException(status_code=400, detail="缺少执行账号")
    summary = await get_account_authorization_summary(account_id, session=session)
    if summary.can_create_tasks:
        return summary
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=(
            f"当前 TG 账号尚未获得自动发送授权，暂不可{action_text}。"
            "请为该账号激活套餐位后再试。"
        ),
    )


async def activate_card_for_user(
    *,
    user_id: int,
    card_code: str,
    account_id: Optional[str] = None,
    slot_id: Optional[str] = None,
    session: Optional[AsyncSession] = None,
) -> tuple[UserLicenseSlot, ActivationCard]:
    if session is not None:
        return await _activate_card_for_user(
            user_id=user_id,
            card_code=card_code,
            account_id=account_id,
            slot_id=slot_id,
            session=session,
        )
    async with get_async_session() as own_session:
        slot, card = await _activate_card_for_user(
            user_id=user_id,
            card_code=card_code,
            account_id=account_id,
            slot_id=slot_id,
            session=own_session,
        )
        return slot, card


async def _activate_card_for_user(
    *,
    user_id: int,
    card_code: str,
    account_id: Optional[str],
    slot_id: Optional[str],
    session: AsyncSession,
) -> tuple[UserLicenseSlot, ActivationCard]:
    normalized_code = (card_code or "").strip().upper()
    if not normalized_code:
        raise HTTPException(status_code=400, detail="卡密不能为空")

    now = datetime.now()
    card = (
        await session.execute(
            select(ActivationCard).where(func.upper(ActivationCard.card_code) == normalized_code).limit(1)
        )
    ).scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="卡密不存在")
    if not card.is_active:
        raise HTTPException(status_code=400, detail="卡密已失效")
    if card.is_used:
        raise HTTPException(status_code=400, detail="卡密已被使用")
    if card.expires_at and card.expires_at <= now:
        raise HTTPException(status_code=400, detail="卡密已过期")

    duration_days = await _resolve_card_duration_days(card, session)
    if duration_days <= 0:
        raise HTTPException(status_code=400, detail="卡密配置异常：时长无效")

    renewal_slot: Optional[UserLicenseSlot] = None
    if slot_id:
        renewal_slot = await session.get(UserLicenseSlot, str(slot_id))
        if renewal_slot is None or int(renewal_slot.user_id) != int(user_id):
            raise HTTPException(status_code=404, detail="套餐位不存在")
    elif account_id:
        renewal_slot = await _resolve_renewal_slot_by_account(user_id, account_id, session)

    if renewal_slot is not None:
        slot = await _renew_slot_with_card(slot=renewal_slot, card=card, duration_days=duration_days, session=session)
    else:
        slot = await _create_slot_from_card(
            user_id=user_id,
            card=card,
            duration_days=duration_days,
            session=session,
        )

    card.is_used = True
    card.used_by_user_id = int(user_id)
    card.used_at = now
    await session.flush()
    return slot, card


async def _create_slot_from_card(
    *,
    user_id: int,
    card: ActivationCard,
    duration_days: int,
    session: AsyncSession,
) -> UserLicenseSlot:
    now = datetime.now()
    slot = UserLicenseSlot(
        user_id=int(user_id),
        current_account_id=None,
        source_card_id=card.id,
        grant_source=GRANT_SOURCE_CARD,
        total_duration_days=duration_days,
        start_at=now,
        end_at=now + timedelta(days=duration_days),
        status="active",
    )
    session.add(slot)
    await session.flush()
    session.add(
        UserLicenseSlotCard(
            slot_id=slot.slot_id,
            activation_card_id=card.id,
            duration_days=duration_days,
            applied_at=now,
        )
    )
    await session.flush()
    return slot


async def _renew_slot_with_card(
    *,
    slot: UserLicenseSlot,
    card: ActivationCard,
    duration_days: int,
    session: AsyncSession,
) -> UserLicenseSlot:
    now = datetime.now()
    base_time = slot.end_at if slot.end_at and slot.end_at > now else now
    if not slot.start_at:
        slot.start_at = now
    slot.end_at = base_time + timedelta(days=duration_days)
    slot.total_duration_days = int(slot.total_duration_days or 0) + duration_days
    slot.status = "active"
    if not slot.source_card_id:
        slot.source_card_id = card.id
    session.add(
        UserLicenseSlotCard(
            slot_id=slot.slot_id,
            activation_card_id=card.id,
            duration_days=duration_days,
            applied_at=now,
        )
    )
    if slot.current_account_id:
        open_binding = (
            await session.execute(
                select(UserLicenseSlotBinding)
                .where(
                    UserLicenseSlotBinding.slot_id == str(slot.slot_id),
                    UserLicenseSlotBinding.account_id == str(slot.current_account_id),
                    UserLicenseSlotBinding.unbind_at.is_(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if open_binding is None:
            session.add(
                UserLicenseSlotBinding(
                    slot_id=str(slot.slot_id),
                    account_id=str(slot.current_account_id),
                    bind_at=now,
                )
            )
    await session.flush()
    return slot


async def _resolve_activation_account_id(
    user_id: int,
    account_id: Optional[str],
    session: AsyncSession,
) -> Optional[str]:
    return None


async def _resolve_renewal_slot_by_account(
    user_id: int,
    account_id: str,
    session: AsyncSession,
) -> UserLicenseSlot:
    account = await session.get(Account, str(account_id))
    if account is None or int(account.user_id) != int(user_id):
        raise HTTPException(status_code=404, detail="目标 TG 账号不存在")

    slot = (
        await session.execute(
            select(UserLicenseSlot)
            .where(
                UserLicenseSlot.user_id == int(user_id),
                UserLicenseSlot.current_account_id == str(account_id),
            )
            .order_by(UserLicenseSlot.end_at.desc(), UserLicenseSlot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if slot is None:
        raise HTTPException(status_code=400, detail="该 TG 账号当前没有可续费的套餐位，请先新开套餐位")
    return slot


async def auto_bind_available_slot_to_account(
    *,
    user_id: int,
    account_id: str,
    session: Optional[AsyncSession] = None,
) -> Optional[UserLicenseSlot]:
    if session is not None:
        return await _auto_bind_available_slot_to_account(user_id=user_id, account_id=account_id, session=session)
    async with get_async_session() as own_session:
        return await _auto_bind_available_slot_to_account(user_id=user_id, account_id=account_id, session=own_session)


async def _auto_bind_available_slot_to_account(
    *,
    user_id: int,
    account_id: str,
    session: AsyncSession,
) -> Optional[UserLicenseSlot]:
    summary = await _get_account_authorization_summary(account_id, session)
    if summary.can_create_tasks:
        return await session.get(UserLicenseSlot, summary.slot_id)

    now = datetime.now()
    unbound_slots = (
        await session.execute(
            select(UserLicenseSlot)
            .where(
                UserLicenseSlot.user_id == int(user_id),
                UserLicenseSlot.current_account_id.is_(None),
                UserLicenseSlot.status == "active",
                UserLicenseSlot.end_at > now,
            )
            .order_by(UserLicenseSlot.end_at.asc(), UserLicenseSlot.created_at.asc())
        )
    ).scalars().all()
    if len(unbound_slots) != 1:
        return None

    slot = unbound_slots[0]
    slot.current_account_id = str(account_id)
    slot.status = "active"
    session.add(
        UserLicenseSlotBinding(
            slot_id=slot.slot_id,
            account_id=str(account_id),
            bind_at=now,
        )
    )
    await session.flush()
    return slot


async def bind_slot_to_account(
    *,
    user_id: int,
    slot_id: str,
    account_id: str,
    session: Optional[AsyncSession] = None,
) -> UserLicenseSlot:
    if session is not None:
        return await _bind_slot_to_account(user_id=user_id, slot_id=slot_id, account_id=account_id, session=session)
    async with get_async_session() as own_session:
        slot = await _bind_slot_to_account(user_id=user_id, slot_id=slot_id, account_id=account_id, session=own_session)
        await own_session.commit()
        return slot


async def _bind_slot_to_account(
    *,
    user_id: int,
    slot_id: str,
    account_id: str,
    session: AsyncSession,
) -> UserLicenseSlot:
    await _sync_expired_slots(session, user_id=user_id)
    now = datetime.now()

    slot = await session.get(UserLicenseSlot, str(slot_id))
    if slot is None or int(slot.user_id) != int(user_id):
        raise HTTPException(status_code=404, detail="套餐位不存在")
    if slot.end_at <= now or slot.status != "active":
        raise HTTPException(status_code=400, detail="该套餐位已到期，无法再绑定 TG 账号")
    if slot.current_account_id and str(slot.current_account_id) != str(account_id):
        raise HTTPException(status_code=400, detail="该套餐位已绑定其他 TG 账号，请先退出原账号后再切换")

    account = await session.get(Account, str(account_id))
    if account is None or int(account.user_id) != int(user_id):
        raise HTTPException(status_code=404, detail="目标 TG 账号不存在")

    account_summary = await _get_account_authorization_summary(account_id, session)
    if account_summary.can_create_tasks and str(account_summary.slot_id) != str(slot_id):
        raise HTTPException(status_code=400, detail="该 TG 账号已绑定其他有效套餐位，不能重复绑定")

    slot.current_account_id = str(account_id)
    slot.status = "active"
    open_binding = (
        await session.execute(
            select(UserLicenseSlotBinding)
            .where(
                UserLicenseSlotBinding.slot_id == str(slot_id),
                UserLicenseSlotBinding.account_id == str(account_id),
                UserLicenseSlotBinding.unbind_at.is_(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if open_binding is None:
        session.add(
            UserLicenseSlotBinding(
                slot_id=str(slot_id),
                account_id=str(account_id),
                bind_at=now,
            )
        )
    await session.flush()
    return slot


async def release_slots_for_account(
    *,
    account_id: str,
    session: AsyncSession,
    reason: str = "account_deleted",
) -> int:
    slots = (
        await session.execute(
            select(UserLicenseSlot).where(UserLicenseSlot.current_account_id == str(account_id))
        )
    ).scalars().all()
    if not slots:
        return 0

    now = datetime.now()
    slot_ids = [slot.slot_id for slot in slots]
    binding_rows = (
        await session.execute(
            select(UserLicenseSlotBinding)
            .where(
                UserLicenseSlotBinding.slot_id.in_(slot_ids),
                UserLicenseSlotBinding.account_id == str(account_id),
                UserLicenseSlotBinding.unbind_at.is_(None),
            )
        )
    ).scalars().all()
    binding_map = {row.slot_id: row for row in binding_rows}

    for slot in slots:
        slot.current_account_id = None
        if slot.end_at <= now:
            slot.status = "expired"
        else:
            slot.status = "active"
        binding = binding_map.get(slot.slot_id)
        if binding is not None:
            binding.unbind_at = now
            binding.unbind_reason = reason

    await session.flush()
    return len(slots)


async def disable_tasks_for_account_if_unlicensed(
    *,
    account_id: str,
    session: AsyncSession,
) -> int:
    from backend.database.schema.models import ScheduledMessageTask

    summary = await _get_account_authorization_summary(account_id, session)
    if summary.can_create_tasks:
        return 0

    tasks = (
        await session.execute(
            select(ScheduledMessageTask).where(
                ScheduledMessageTask.account_id == str(account_id),
                ScheduledMessageTask.enabled == True,
            )
        )
    ).scalars().all()
    for task in tasks:
        task.enabled = False
    await session.flush()
    return len(tasks)


async def list_due_slot_reminders(
    *,
    user_id_to_tg: Dict[int, int],
    session: AsyncSession,
    notice_days: tuple[int, ...],
) -> list[dict[str, Any]]:
    await _sync_expired_slots(session)
    now = datetime.now()
    upper = now + timedelta(days=max(notice_days) + 1)
    rows = (
        await session.execute(
            select(UserLicenseSlot)
            .where(
                UserLicenseSlot.status == "active",
                UserLicenseSlot.user_id.in_(list(user_id_to_tg.keys())),
                UserLicenseSlot.end_at > now,
                UserLicenseSlot.end_at <= upper,
            )
            .order_by(UserLicenseSlot.end_at.asc())
        )
    ).scalars().all()
    items: list[dict[str, Any]] = []
    for slot in rows:
        days_before = (slot.end_at.date() - now.date()).days
        if days_before not in notice_days:
            continue
        exists = await session.execute(
            select(SlotNoticeLog.id).where(
                SlotNoticeLog.slot_id == slot.slot_id,
                SlotNoticeLog.days_before == int(days_before),
            )
        )
        if exists.scalar_one_or_none() is not None:
            continue
        items.append(
            {
                "slot_id": slot.slot_id,
                "user_id": int(slot.user_id),
                "tg_user_id": int(user_id_to_tg[int(slot.user_id)]),
                "days_before": int(days_before),
                "end_at": slot.end_at,
                "account_id": slot.current_account_id,
            }
        )
    return items
