"""Single-authorization service for TG auto-send capability."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    Account,
    ActivationCard,
    PricingPlan,
    AuthorizationNoticeLog,
    User,
    UserAuthorization,
    UserAuthorizationBinding,
    UserAuthorizationCard,
)

BOT_TRIAL_DURATION_DAYS = 7
GRANT_SOURCE_CARD = "card"
GRANT_SOURCE_BOT_TRIAL = "bot_trial"

@dataclass(frozen=True)
class AccountAuthorizationSummary:
    account_id: str
    authorization_id: Optional[str]
    authorization_status: str
    can_create_tasks: bool
    authorization_end_at: Optional[datetime]
    authorization_card_count: int
    authorization_grant_source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "authorization_status": self.authorization_status,
            "can_create_tasks": self.can_create_tasks,
            "authorization_end_at": self.authorization_end_at.isoformat() if self.authorization_end_at else None,
            "authorization_card_count": int(self.authorization_card_count),
            "authorization_grant_source": self.authorization_grant_source,
            "authorization_grant_source_label": _grant_source_label(self.authorization_grant_source),
        }


@dataclass(frozen=True)
class AuthorizationRecord:
    authorization_id: str
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
            "authorization_id": self.authorization_id,
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
class AuthorizationOverview:
    user_id: int
    account_count: int
    has_active_authorization: bool
    next_expiring_at: Optional[datetime]

    @property
    def max_account_count(self) -> int:
        return 1

    @property
    def remaining_login_slots(self) -> int:
        return max(0, self.max_account_count - int(self.account_count))

    @property
    def is_at_limit(self) -> bool:
        return self.account_count >= self.max_account_count

    @property
    def is_over_limit(self) -> bool:
        return self.account_count > self.max_account_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_count": int(self.account_count),
            "max_account_count": int(self.max_account_count),
            "can_bind_account": self.account_count < self.max_account_count,
            "is_at_limit": self.is_at_limit,
            "is_over_limit": self.is_over_limit,
            "has_active_authorization": bool(self.has_active_authorization),
            "next_expiring_at": self.next_expiring_at.isoformat() if self.next_expiring_at else None,
        }


def _mask_card_code(card_code: Optional[str]) -> Optional[str]:
    value = (card_code or "").strip()
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}****{value[-4:]}"


class TgAccountLimitExceededError(RuntimeError):
    def __init__(self, overview: AuthorizationOverview):
        self.overview = overview
        message = (
            "当前系统账号仅支持绑定 1 个 TG 账号。"
            "如需更换，请先删除或退出当前已绑定账号后再继续绑定新的 TG 账号。"
        )
        super().__init__(message)


def _account_display_name(account: Optional[Account]) -> Optional[str]:
    if account is None:
        return None
    if account.username:
        return f"@{account.username}"
    if account.phone:
        return account.phone
    if account.tg_user_id:
        return str(account.tg_user_id)
    return None


def _grant_source_label(grant_source: Optional[str]) -> str:
    if grant_source == GRANT_SOURCE_BOT_TRIAL:
        return "首次绑定 TG 赠送试用"
    return "卡密续费"


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
            select(UserAuthorization.authorization_id).where(
                UserAuthorization.current_account_id == account_id,
                UserAuthorization.status == "active",
                UserAuthorization.end_at > now,
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
            UserAuthorizationCard,
            UserAuthorizationCard.activation_card_id == ActivationCard.id,
        )
        .where(
            ActivationCard.is_used.is_(True),
            ActivationCard.used_by_user_id.is_not(None),
            UserAuthorizationCard.id.is_(None),
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

        slot = UserAuthorization(
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
            UserAuthorizationCard(
                authorization_id=slot.authorization_id,
                activation_card_id=card.id,
                duration_days=duration_days,
                applied_at=start_at,
            )
        )
        if bind_account_id:
            session.add(
                UserAuthorizationBinding(
                    authorization_id=slot.authorization_id,
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
    stmt = select(UserAuthorization).where(
        UserAuthorization.status == "active",
        UserAuthorization.end_at <= now,
    )
    if user_id is not None:
        stmt = stmt.where(UserAuthorization.user_id == int(user_id))

    rows = (await session.execute(stmt)).scalars().all()
    updated = False
    for slot in rows:
        if slot.status != "expired":
            slot.status = "expired"
            updated = True
    if updated:
        await session.flush()


def _slot_priority(slot: UserAuthorization, *, now: datetime, accounts_by_id: Dict[str, Account]) -> tuple:
    account = accounts_by_id.get(str(slot.current_account_id or ""))
    return (
        1 if slot.status == "active" and slot.end_at > now else 0,
        1 if account and account.is_active else 0,
        1 if account and str(account.health_status) == "online" else 0,
        slot.end_at or datetime.min,
        slot.updated_at or slot.created_at or datetime.min,
        str(slot.authorization_id),
    )


def _account_priority(account: Account) -> tuple:
    return (
        1 if account.is_active else 0,
        1 if str(account.health_status) == "online" else 0,
        account.last_used_at or datetime.min,
        account.created_at or datetime.min,
        str(account.account_id),
    )


async def _disable_tasks_for_accounts(
    *,
    account_ids: List[str],
    session: AsyncSession,
) -> int:
    if not account_ids:
        return 0
    from backend.database.schema.models import ScheduledMessageTask

    rows = (
        await session.execute(
            select(ScheduledMessageTask).where(
                ScheduledMessageTask.account_id.in_(account_ids),
                ScheduledMessageTask.enabled == True,
            )
        )
    ).scalars().all()
    for row in rows:
        row.enabled = False
    return len(rows)


async def _normalize_single_authorization_model(
    *,
    user_id: int,
    session: AsyncSession,
) -> tuple[Optional[UserAuthorization], Optional[Account]]:
    await _backfill_legacy_used_cards(session, user_id=user_id)
    await _sync_expired_slots(session, user_id=user_id)
    now = datetime.now()

    accounts = (
        await session.execute(
            select(Account).where(Account.user_id == int(user_id)).order_by(Account.created_at.asc())
        )
    ).scalars().all()
    slots = (
        await session.execute(
            select(UserAuthorization).where(UserAuthorization.user_id == int(user_id)).order_by(UserAuthorization.created_at.asc())
        )
    ).scalars().all()
    accounts_by_id = {str(account.account_id): account for account in accounts}
    original_active_account_count = sum(1 for account in accounts if account.is_active)
    original_slot_count = len(slots)

    primary_slot = max(slots, key=lambda item: _slot_priority(item, now=now, accounts_by_id=accounts_by_id)) if slots else None
    primary_account: Optional[Account] = None
    if primary_slot and primary_slot.current_account_id:
        primary_account = accounts_by_id.get(str(primary_slot.current_account_id))
    if primary_account is None and accounts:
        primary_account = max(accounts, key=_account_priority)

    changed = False
    deleted_slot_ids: List[str] = []
    if primary_account is not None and not primary_account.is_active:
        primary_account.is_active = True
        changed = True

    disabled_account_ids: List[str] = []
    for account in accounts:
        if primary_account is not None and str(account.account_id) == str(primary_account.account_id):
            continue
        if account.is_active:
            account.is_active = False
            changed = True
        disabled_account_ids.append(str(account.account_id))

    if primary_slot is not None:
        expected_status = "active" if primary_slot.end_at > now else "expired"
        if primary_slot.status != expected_status:
            primary_slot.status = expected_status
            changed = True
        desired_account_id = str(primary_account.account_id) if primary_account is not None else None
        if str(primary_slot.current_account_id or "") != str(desired_account_id or ""):
            previous_account_id = str(primary_slot.current_account_id or "")
            if previous_account_id:
                open_bindings = (
                    await session.execute(
                        select(UserAuthorizationBinding).where(
                            UserAuthorizationBinding.authorization_id == str(primary_slot.authorization_id),
                            UserAuthorizationBinding.unbind_at.is_(None),
                        )
                    )
                ).scalars().all()
                for binding in open_bindings:
                    binding.unbind_at = now
                    binding.unbind_reason = "single_authorization_normalized"
            primary_slot.current_account_id = desired_account_id
            changed = True
            if desired_account_id:
                existing_binding = (
                    await session.execute(
                        select(UserAuthorizationBinding)
                        .where(
                            UserAuthorizationBinding.authorization_id == str(primary_slot.authorization_id),
                            UserAuthorizationBinding.account_id == desired_account_id,
                            UserAuthorizationBinding.unbind_at.is_(None),
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if existing_binding is None:
                    session.add(
                        UserAuthorizationBinding(
                            authorization_id=str(primary_slot.authorization_id),
                            account_id=desired_account_id,
                            bind_at=now,
                        )
                    )

    for slot in slots:
        if primary_slot is not None and str(slot.authorization_id) == str(primary_slot.authorization_id):
            continue
        if slot.current_account_id:
            open_bindings = (
                await session.execute(
                    select(UserAuthorizationBinding).where(
                        UserAuthorizationBinding.authorization_id == str(slot.authorization_id),
                        UserAuthorizationBinding.unbind_at.is_(None),
                    )
                )
            ).scalars().all()
            for binding in open_bindings:
                binding.unbind_at = now
                binding.unbind_reason = "single_authorization_deleted"
        deleted_slot_ids.append(str(slot.authorization_id))
        await session.delete(slot)
        changed = True

    if disabled_account_ids:
        await _disable_tasks_for_accounts(account_ids=disabled_account_ids, session=session)
    if changed:
        await session.flush()
        logger.info(
            "single authorization normalized: user_id={}, original_active_accounts={}, original_slots={}, kept_account_id={}, kept_authorization_id={}, disabled_accounts={}, deleted_slots={}",
            int(user_id),
            int(original_active_account_count),
            int(original_slot_count),
            str(primary_account.account_id) if primary_account is not None else None,
            str(primary_slot.authorization_id) if primary_slot is not None else None,
            len(disabled_account_ids),
            len(deleted_slot_ids),
        )
    return primary_slot, primary_account


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
    await _normalize_single_authorization_model(user_id=int(user_id), session=session)
    user = await session.get(User, int(user_id))
    if user is None:
        return False
    if user.bot_trial_eligible_at or user.bot_trial_granted_at or user.bot_trial_authorization_id:
        return False

    authorization_exists = await session.execute(
        select(UserAuthorization.authorization_id).where(UserAuthorization.user_id == int(user_id)).limit(1)
    )
    if authorization_exists.scalar_one_or_none() is not None:
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


async def grant_trial_authorization_if_eligible(
    *,
    user_id: int,
    account_id: str,
    session: Optional[AsyncSession] = None,
) -> Optional[UserAuthorization]:
    if session is not None:
        return await _grant_trial_authorization_if_eligible(user_id=user_id, account_id=account_id, session=session)
    async with get_async_session() as own_session:
        authorization = await _grant_trial_authorization_if_eligible(user_id=user_id, account_id=account_id, session=own_session)
        await own_session.commit()
        return authorization


async def _grant_trial_authorization_if_eligible(
    *,
    user_id: int,
    account_id: str,
    session: AsyncSession,
) -> Optional[UserAuthorization]:
    primary_authorization, _primary_account = await _normalize_single_authorization_model(user_id=int(user_id), session=session)
    user = await session.get(User, int(user_id))
    if user is None:
        return None
    if user.bot_trial_granted_at or user.bot_trial_authorization_id:
        return None

    account = await session.get(Account, str(account_id))
    if account is None or int(account.user_id) != int(user_id):
        return None

    has_used_card = (
        await session.execute(
            select(ActivationCard.id).where(
                ActivationCard.used_by_user_id == int(user_id),
                ActivationCard.is_used.is_(True),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if has_used_card is not None:
        user.bot_trial_eligible_at = None
        await session.flush()
        return None

    if primary_authorization is not None:
        user.bot_trial_eligible_at = None
        await session.flush()
        return None

    now = datetime.now()
    authorization = UserAuthorization(
        user_id=int(user_id),
        current_account_id=str(account_id),
        source_card_id=None,
        grant_source=GRANT_SOURCE_BOT_TRIAL,
        total_duration_days=BOT_TRIAL_DURATION_DAYS,
        start_at=now,
        end_at=now + timedelta(days=BOT_TRIAL_DURATION_DAYS),
        status="active",
    )
    session.add(authorization)
    await session.flush()
    session.add(
        UserAuthorizationBinding(
            authorization_id=authorization.authorization_id,
            account_id=str(account_id),
            bind_at=now,
        )
    )
    user.bot_trial_eligible_at = user.bot_trial_eligible_at or now
    user.bot_trial_granted_at = now
    user.bot_trial_authorization_id = authorization.authorization_id
    await session.flush()
    return authorization


async def _build_authorization_overview(user_id: int, session: AsyncSession) -> AuthorizationOverview:
    primary_authorization, _primary_account = await _normalize_single_authorization_model(user_id=int(user_id), session=session)
    now = datetime.now()
    account_count = await _count_active_accounts(user_id, session)
    has_active_authorization = bool(
        primary_authorization is not None
        and primary_authorization.status == "active"
        and primary_authorization.end_at > now
    )
    next_expiring_at = primary_authorization.end_at if has_active_authorization else None

    return AuthorizationOverview(
        user_id=int(user_id),
        account_count=account_count,
        has_active_authorization=has_active_authorization,
        next_expiring_at=next_expiring_at,
    )


async def get_authorization_overview(
    user_id: int,
    session: Optional[AsyncSession] = None,
) -> AuthorizationOverview:
    if session is not None:
        return await _build_authorization_overview(user_id, session)
    async with get_async_session() as own_session:
        return await _build_authorization_overview(user_id, own_session)


async def ensure_can_add_tg_account(
    user_id: int,
    *,
    existing_tg_user_id: Optional[int] = None,
    session: Optional[AsyncSession] = None,
) -> AuthorizationOverview:
    if session is not None:
        return await _ensure_can_add_tg_account(user_id, existing_tg_user_id=existing_tg_user_id, session=session)
    async with get_async_session() as own_session:
        return await _ensure_can_add_tg_account(user_id, existing_tg_user_id=existing_tg_user_id, session=own_session)


async def _ensure_can_add_tg_account(
    user_id: int,
    *,
    existing_tg_user_id: Optional[int],
    session: AsyncSession,
) -> AuthorizationOverview:
    await _normalize_single_authorization_model(user_id=int(user_id), session=session)
    if existing_tg_user_id is not None:
        existing = await session.execute(
            select(Account.account_id).where(
                Account.user_id == int(user_id),
                Account.tg_user_id == int(existing_tg_user_id),
                Account.is_active.is_(True),
            )
        )
        if existing.scalar_one_or_none() is not None:
            return await _build_authorization_overview(user_id, session)

    overview = await _build_authorization_overview(user_id, session)
    if overview.account_count >= overview.max_account_count:
        raise TgAccountLimitExceededError(overview)
    return overview


async def list_user_authorizations(user_id: int, session: Optional[AsyncSession] = None) -> List[AuthorizationRecord]:
    if session is not None:
        return await _list_user_authorizations(user_id, session)
    async with get_async_session() as own_session:
        return await _list_user_authorizations(user_id, own_session)


async def _list_user_authorizations(user_id: int, session: AsyncSession) -> List[AuthorizationRecord]:
    primary_authorization, primary_account = await _normalize_single_authorization_model(user_id=int(user_id), session=session)
    if primary_authorization is None:
        return []
    now = datetime.now()
    card_count = (
        await session.execute(
            select(func.count(UserAuthorizationCard.id)).where(UserAuthorizationCard.authorization_id == primary_authorization.authorization_id)
        )
    ).scalar_one()
    card_rows = (
        await session.execute(
            select(UserAuthorizationCard, ActivationCard.card_code)
            .join(ActivationCard, ActivationCard.id == UserAuthorizationCard.activation_card_id)
            .where(UserAuthorizationCard.authorization_id == primary_authorization.authorization_id)
            .order_by(UserAuthorizationCard.applied_at.asc(), UserAuthorizationCard.id.asc())
        )
    ).all()
    source_card_code_masked = _mask_card_code(card_rows[0][1]) if card_rows else None
    latest_card_code_masked = _mask_card_code(card_rows[-1][1]) if card_rows else None
    remaining_days = max(0, int((primary_authorization.end_at - now).total_seconds() // 86400)) if primary_authorization.end_at else 0
    return [
        AuthorizationRecord(
            authorization_id=primary_authorization.authorization_id,
            account_id=primary_authorization.current_account_id,
            account_name=_account_display_name(primary_account),
            status=primary_authorization.status,
            duration_days=int(primary_authorization.total_duration_days or 0),
            start_at=primary_authorization.start_at,
            end_at=primary_authorization.end_at,
            card_count=int(card_count or 0),
            remaining_days=remaining_days,
            grant_source=getattr(primary_authorization, "grant_source", None),
            source_card_code_masked=source_card_code_masked,
            latest_card_code_masked=latest_card_code_masked,
        )
    ]


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
        await _normalize_single_authorization_model(user_id=int(account.user_id), session=session)
    now = datetime.now()
    slot = (
        await session.execute(
            select(UserAuthorization)
            .where(
                UserAuthorization.current_account_id == str(account_id),
                UserAuthorization.status == "active",
                UserAuthorization.end_at > now,
            )
            .order_by(UserAuthorization.end_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if slot is None:
        expired_slot = (
            await session.execute(
                select(UserAuthorization)
                .where(UserAuthorization.current_account_id == str(account_id))
                .order_by(UserAuthorization.end_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if expired_slot is not None:
            card_count = (
                await session.execute(
                    select(func.count(UserAuthorizationCard.id)).where(UserAuthorizationCard.authorization_id == expired_slot.authorization_id)
                )
            ).scalar_one()
            return AccountAuthorizationSummary(
                account_id=str(account_id),
                authorization_id=expired_slot.authorization_id,
                authorization_status="expired" if expired_slot.end_at <= now else expired_slot.status,
                can_create_tasks=False,
                authorization_end_at=expired_slot.end_at,
                authorization_card_count=int(card_count or 0),
                authorization_grant_source=getattr(expired_slot, "grant_source", None),
            )
        return AccountAuthorizationSummary(
            account_id=str(account_id),
            authorization_id=None,
            authorization_status="unlicensed",
            can_create_tasks=False,
            authorization_end_at=None,
            authorization_card_count=0,
            authorization_grant_source=None,
        )

    card_count = (
        await session.execute(
            select(func.count(UserAuthorizationCard.id)).where(UserAuthorizationCard.authorization_id == slot.authorization_id)
        )
    ).scalar_one()
    return AccountAuthorizationSummary(
        account_id=str(account_id),
        authorization_id=slot.authorization_id,
        authorization_status="licensed",
        can_create_tasks=True,
        authorization_end_at=slot.end_at,
        authorization_card_count=int(card_count or 0),
        authorization_grant_source=getattr(slot, "grant_source", None),
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
            "请先为当前授权续费后再试。"
        ),
    )


async def activate_card_for_user(
    *,
    user_id: int,
    card_code: str,
    session: Optional[AsyncSession] = None,
) -> tuple[UserAuthorization, ActivationCard]:
    if session is not None:
        return await _activate_card_for_user(
            user_id=user_id,
            card_code=card_code,
            session=session,
        )
    async with get_async_session() as own_session:
        authorization, card = await _activate_card_for_user(
            user_id=user_id,
            card_code=card_code,
            session=own_session,
        )
        return authorization, card


async def _activate_card_for_user(
    *,
    user_id: int,
    card_code: str,
    session: AsyncSession,
) -> tuple[UserAuthorization, ActivationCard]:
    primary_authorization, primary_account = await _normalize_single_authorization_model(user_id=int(user_id), session=session)
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

    renewal_authorization: Optional[UserAuthorization] = primary_authorization
    if renewal_authorization is not None:
        authorization = await _renew_slot_with_card(slot=renewal_authorization, card=card, duration_days=duration_days, session=session)
    else:
        authorization = await _create_slot_from_card(
            user_id=user_id,
            card=card,
            duration_days=duration_days,
            account_id=str(primary_account.account_id) if primary_account is not None else None,
            session=session,
        )

    card.is_used = True
    card.used_by_user_id = int(user_id)
    card.used_at = now
    await session.flush()
    return authorization, card


async def _create_slot_from_card(
    *,
    user_id: int,
    card: ActivationCard,
    duration_days: int,
    account_id: Optional[str],
    session: AsyncSession,
) -> UserAuthorization:
    now = datetime.now()
    slot = UserAuthorization(
        user_id=int(user_id),
        current_account_id=str(account_id) if account_id else None,
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
        UserAuthorizationCard(
            authorization_id=slot.authorization_id,
            activation_card_id=card.id,
            duration_days=duration_days,
            applied_at=now,
        )
    )
    if account_id:
        session.add(
            UserAuthorizationBinding(
                authorization_id=slot.authorization_id,
                account_id=str(account_id),
                bind_at=now,
            )
        )
    await session.flush()
    return slot


async def _renew_slot_with_card(
    *,
    slot: UserAuthorization,
    card: ActivationCard,
    duration_days: int,
    session: AsyncSession,
) -> UserAuthorization:
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
        UserAuthorizationCard(
            authorization_id=slot.authorization_id,
            activation_card_id=card.id,
            duration_days=duration_days,
            applied_at=now,
        )
    )
    if slot.current_account_id:
        open_binding = (
            await session.execute(
                select(UserAuthorizationBinding)
                .where(
                    UserAuthorizationBinding.authorization_id == str(slot.authorization_id),
                    UserAuthorizationBinding.account_id == str(slot.current_account_id),
                    UserAuthorizationBinding.unbind_at.is_(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if open_binding is None:
            session.add(
                UserAuthorizationBinding(
                    authorization_id=str(slot.authorization_id),
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
) -> UserAuthorization:
    await _normalize_single_authorization_model(user_id=int(user_id), session=session)
    account = await session.get(Account, str(account_id))
    if account is None or int(account.user_id) != int(user_id):
        raise HTTPException(status_code=404, detail="目标 TG 账号不存在")

    slot = (
        await session.execute(
            select(UserAuthorization)
            .where(
                UserAuthorization.user_id == int(user_id),
                UserAuthorization.current_account_id == str(account_id),
            )
            .order_by(UserAuthorization.end_at.desc(), UserAuthorization.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if slot is None:
        raise HTTPException(status_code=400, detail="该 TG 账号当前没有可续费的授权，请先绑定账号并触发试用，或输入卡密开通当前授权")
    return slot


async def bind_current_authorization_to_account_if_possible(
    *,
    user_id: int,
    account_id: str,
    session: Optional[AsyncSession] = None,
) -> Optional[UserAuthorization]:
    if session is not None:
        return await _bind_current_authorization_to_account_if_possible(user_id=user_id, account_id=account_id, session=session)
    async with get_async_session() as own_session:
        return await _bind_current_authorization_to_account_if_possible(user_id=user_id, account_id=account_id, session=own_session)


async def _bind_current_authorization_to_account_if_possible(
    *,
    user_id: int,
    account_id: str,
    session: AsyncSession,
) -> Optional[UserAuthorization]:
    primary_authorization, _primary_account = await _normalize_single_authorization_model(user_id=int(user_id), session=session)
    summary = await _get_account_authorization_summary(account_id, session)
    if summary.can_create_tasks:
        return await session.get(UserAuthorization, summary.authorization_id)

    if primary_authorization is None:
        return None
    now = datetime.now()
    if primary_authorization.status != "active" or primary_authorization.end_at <= now:
        return primary_authorization
    if primary_authorization.current_account_id and str(primary_authorization.current_account_id) != str(account_id):
        return primary_authorization
    if not primary_authorization.current_account_id:
        primary_authorization.current_account_id = str(account_id)
        session.add(
            UserAuthorizationBinding(
                authorization_id=primary_authorization.authorization_id,
                account_id=str(account_id),
                bind_at=now,
            )
        )
        await session.flush()
    return primary_authorization


async def release_slots_for_account(
    *,
    account_id: str,
    session: AsyncSession,
    reason: str = "account_deleted",
) -> int:
    slots = (
        await session.execute(
            select(UserAuthorization).where(UserAuthorization.current_account_id == str(account_id))
        )
    ).scalars().all()
    if not slots:
        return 0

    now = datetime.now()
    authorization_ids = [slot.authorization_id for slot in slots]
    binding_rows = (
        await session.execute(
            select(UserAuthorizationBinding)
            .where(
                UserAuthorizationBinding.authorization_id.in_(authorization_ids),
                UserAuthorizationBinding.account_id == str(account_id),
                UserAuthorizationBinding.unbind_at.is_(None),
            )
        )
    ).scalars().all()
    binding_map = {row.authorization_id: row for row in binding_rows}

    for slot in slots:
        slot.current_account_id = None
        if slot.end_at <= now:
            slot.status = "expired"
        else:
            slot.status = "active"
        binding = binding_map.get(slot.authorization_id)
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
            select(UserAuthorization)
            .where(
                UserAuthorization.status == "active",
                UserAuthorization.user_id.in_(list(user_id_to_tg.keys())),
                UserAuthorization.end_at > now,
                UserAuthorization.end_at <= upper,
            )
            .order_by(UserAuthorization.end_at.asc())
        )
    ).scalars().all()
    items: list[dict[str, Any]] = []
    for slot in rows:
        days_before = (slot.end_at.date() - now.date()).days
        if days_before not in notice_days:
            continue
        exists = await session.execute(
            select(AuthorizationNoticeLog.id).where(
                AuthorizationNoticeLog.authorization_id == slot.authorization_id,
                AuthorizationNoticeLog.days_before == int(days_before),
            )
        )
        if exists.scalar_one_or_none() is not None:
            continue
        items.append(
            {
                "authorization_id": slot.authorization_id,
                "user_id": int(slot.user_id),
                "tg_user_id": int(user_id_to_tg[int(slot.user_id)]),
                "days_before": int(days_before),
                "end_at": slot.end_at,
                "account_id": slot.current_account_id,
            }
        )
    return items
