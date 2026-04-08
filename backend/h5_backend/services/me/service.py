"""Profile, current authorization overview and card renewal service."""
from __future__ import annotations

import re
import secrets
import string
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError

from backend.config.core.settings import settings
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    ActivationCard,
    AppSetting,
    PricingPlan,
    SystemSession,
    User,
)
from backend.h5_backend.services.auth.service import get_auth_service
from backend.utils.security.crypto import get_crypto_manager
from backend.h5_backend.services.licensing.service import (
    activate_card_for_user,
    ensure_can_add_tg_account,
    get_account_authorization_summary,
    get_authorization_overview,
    list_user_authorizations,
)

DEFAULT_PURCHASE_URL = "https://t.me/"
DEFAULT_PURCHASE_BUTTON_TEXT = "联系 Telegram 购买"
DEFAULT_BOT_NOTICE_ENTRY_BUTTON_TEXT = "📢 公告栏"
_NOTICE_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)


class MeService:
    """Business service for 'My' page."""

    @staticmethod
    def _generate_reset_password(length: int = 14) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

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
    async def _resolve_bot_username() -> str:
        username = (settings.bot_username or "").strip().lstrip("@")
        if username:
            return username

        async with get_async_session() as session:
            row = await session.get(SystemSession, "manager_bot")
            if not row or not isinstance(row.session_meta, dict):
                return ""
            return str(row.session_meta.get("username") or "").strip().lstrip("@")

    @classmethod
    async def _serialize_bot_entry(cls) -> Dict[str, str]:
        username = await cls._resolve_bot_username()
        return {
            "username": username,
            "bind_deep_link_base": (
                f"https://t.me/{username}" if username else ""
            ),
        }

    @staticmethod
    def _serialize_authorization_status(overview: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "is_active": bool(overview.get("has_active_authorization", False)),
            "current_authorization": overview.get("current_authorization"),
            "remain_days": overview.get("remain_days"),
        }

    @staticmethod
    def _extract_first_url(text: str) -> str:
        match = _NOTICE_URL_PATTERN.search(text or "")
        return match.group(0).strip() if match else ""

    @classmethod
    def _remove_first_url(cls, text: str) -> str:
        if not text:
            return ""
        return _NOTICE_URL_PATTERN.sub("", text, count=1).strip()

    @staticmethod
    def _build_notice_version(*, enabled: bool, message_text: str, target_url: str) -> str:
        import hashlib

        payload = f"{1 if enabled else 0}\n{message_text.strip()}\n{target_url.strip()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    async def get_current_authorization(self, user_id: int) -> Optional[Dict[str, Any]]:
        status = await self.get_authorization_status(user_id)
        return status.get("current_authorization")

    async def get_bot_initial_password(self, user_id: int) -> Optional[str]:
        async with get_async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id).limit(1))
            ).scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")
            if not user.bot_initial_password_viewable or not user.bot_initial_password_encrypted:
                return None
            return get_crypto_manager().decrypt(user.bot_initial_password_encrypted)

    async def reset_corrupted_bot_initial_password(self, user_id: int) -> str:
        auth_service = get_auth_service()
        new_password = self._generate_reset_password()

        async with get_async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id).limit(1))
            ).scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")

            user.password_hash = auth_service.get_password_hash(new_password)
            user.bot_initial_password_encrypted = None
            user.bot_initial_password_viewable = False
            user.password_changed_after_bot_registration = True
            await session.commit()

        logger.warning(
            "Bot 初始密码解密失败，已按需重置用户密码: user_id={}",
            user_id,
        )
        return new_password

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

    async def get_public_notice_entry(self) -> Dict[str, Any]:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(AppSetting).where(
                        AppSetting.key.in_(
                            [
                                "bot_notice_enabled",
                                "bot_notice_entry_button_text",
                                "bot_notice_message_text",
                                "bot_notice_target_url",
                                # 兼容旧版配置键
                                "bot_notice_title",
                                "bot_notice_content",
                                "bot_notice_button_text",
                            ]
                        )
                    )
                )
            ).scalars().all()
            values = {row.key: row.value for row in rows}
            updated_at = None
            for row in rows:
                if row.updated_at and (updated_at is None or row.updated_at > updated_at):
                    updated_at = row.updated_at
            enabled_raw = (values.get("bot_notice_enabled") or "").strip().lower()
            message_text = (values.get("bot_notice_message_text") or "").strip()
            legacy_content = (values.get("bot_notice_content") or "").strip()
            if not message_text and legacy_content:
                message_text = self._remove_first_url(legacy_content) or legacy_content
            target_url = (values.get("bot_notice_target_url") or "").strip()
            if not target_url and legacy_content:
                target_url = self._extract_first_url(legacy_content)
            entry_button_text = (
                values.get("bot_notice_entry_button_text")
                or values.get("bot_notice_button_text")
                or DEFAULT_BOT_NOTICE_ENTRY_BUTTON_TEXT
            )
            enabled = enabled_raw in {"1", "true", "yes", "on"}
            return {
                "enabled": enabled,
                "entry_button_text": str(entry_button_text).strip() or DEFAULT_BOT_NOTICE_ENTRY_BUTTON_TEXT,
                "message_text": message_text,
                "target_url": target_url,
                "updated_at": updated_at.isoformat() if updated_at else None,
                "notice_version": self._build_notice_version(
                    enabled=enabled,
                    message_text=message_text,
                    target_url=target_url,
                ),
            }

    async def get_profile(self, user_id: int) -> Dict[str, Any]:
        plans = await self.list_active_plans()
        purchase = await self.get_purchase_entry()
        authorization_overview = await get_authorization_overview(user_id)
        authorization_status = await self.get_authorization_status(user_id)

        async with get_async_session() as session:
            user_result = await session.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")

        return {
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "is_active": user.is_active,
                "bot_initial_password_viewable": bool(user.bot_initial_password_viewable and user.bot_initial_password_encrypted),
                "bot_trial_eligible_at": user.bot_trial_eligible_at.isoformat() if user.bot_trial_eligible_at else None,
                "bot_trial_granted_at": user.bot_trial_granted_at.isoformat() if user.bot_trial_granted_at else None,
                "bot_trial_authorization_id": user.bot_trial_authorization_id,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            },
            "authorization_status": authorization_status["authorization_status"],
            "authorization_overview": authorization_overview.to_dict(),
            "current_authorization": authorization_status["current_authorization"],
            "bot": await self._serialize_bot_entry(),
            "plans": plans,
            "purchase": purchase,
        }

    async def get_authorization_status(self, user_id: int) -> Dict[str, Any]:
        plans = await self.list_active_plans()
        purchase = await self.get_purchase_entry()
        authorization_items = await list_user_authorizations(user_id)
        authorization_overview = await get_authorization_overview(user_id)
        active_authorizations = [item for item in authorization_items if item.status == "active"]
        current = None
        remain_days = None
        if active_authorizations:
            slot = min(active_authorizations, key=lambda item: item.end_at)
            current = slot.to_dict()
            remain_days = slot.remaining_days
        return {
            "is_active": bool(active_authorizations),
            "authorization_status": {
                "is_active": bool(active_authorizations),
                "current_authorization": current,
                "remain_days": remain_days,
            },
            "authorization_overview": authorization_overview.to_dict(),
            "current_authorization": current,
            "bot": await self._serialize_bot_entry(),
            "plans": plans,
            "purchase": purchase,
        }

    async def ensure_can_add_tg_account(self, user_id: int, *, existing_tg_user_id: Optional[int] = None) -> Dict[str, Any]:
        overview = await ensure_can_add_tg_account(user_id, existing_tg_user_id=existing_tg_user_id)
        return overview.to_dict()

    async def require_active_license(self, user_id: int) -> None:
        status_data = await self.get_authorization_status(user_id)
        if status_data["is_active"]:
            return
        detail = "当前系统账号还没有可用于自动发送的有效授权，请先输入卡密续费。"
        purchase_url = ((status_data.get("purchase") or {}).get("url") or "").strip()
        if purchase_url:
            detail = f"{detail} 购买入口：{purchase_url}"
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=detail)

    async def activate_card(
        self,
        user_id: int,
        card_code: str,
    ) -> Dict[str, Any]:
        async with get_async_session() as session:
            slot, _card = await activate_card_for_user(
                user_id=user_id,
                card_code=card_code,
                session=session,
            )
            await session.commit()
        status_data = await self.get_authorization_status(user_id)
        return status_data

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
            user.bot_initial_password_viewable = False
            user.password_changed_after_bot_registration = True
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
