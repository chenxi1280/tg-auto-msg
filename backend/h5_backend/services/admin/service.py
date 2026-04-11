"""Admin-side key-spec, card and license-slot management service."""
from __future__ import annotations

import re
import secrets
import string
from io import BytesIO
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import Select, and_, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import selectinload

from backend.bot.developer_apps import get_developer_app_service
from backend.bot.proxy.pool import get_proxy_pool
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    Account,
    ActivationCard,
    AdminAuditLog,
    AppSetting,
    PricingPlan,
    Proxy,
    TaskLog,
    TelegramDeveloperApp,
    User,
    UserAuthorization,
    UserAuthorizationCard,
)
from backend.h5_backend.services.auth.service import get_auth_service
from backend.h5_backend.services.licensing.service import (
    get_account_authorization_summary,
    get_authorization_overview,
    list_user_authorizations,
)
from backend.config.core.settings import settings
from backend.utils.url_validation import is_valid_button_url


CARD_ALPHABET = string.ascii_uppercase + string.digits
AUDIT_ACTION_LABELS = {
    "admin.update_plan": "更新卡密规格配置",
    "admin.delete_plan": "删除卡密规格",
    "admin.generate_cards": "批量生成卡密",
    "admin.set_card_active": "修改卡密状态",
    "admin.reset_user_password": "重置用户密码",
    "admin.delete_account": "删除账号",
    "admin.add_proxy": "新增代理",
    "admin.check_proxy_health": "检测代理健康",
    "admin.delete_proxy": "删除代理",
    "admin.assign_proxy": "分配代理",
    "admin.unassign_proxy": "解绑代理",
    "admin.update_purchase_settings": "更新购买入口配置",
    "admin.update_bot_notice_settings": "更新 Bot 公告栏配置",
    "admin.create_developer_app": "新增开发者应用",
    "admin.update_developer_app": "更新开发者应用",
    "admin.set_default_developer_app": "设置默认开发者应用",
    "admin.set_user_developer_app": "设置用户开发者应用",
    "admin.update_developer_app_settings": "更新开发者应用策略",
    "admin.check_developer_app_health": "手动检测开发者应用",
    "rbac.create_role": "创建后台角色",
    "rbac.update_role": "更新后台角色",
    "rbac.update_role_permissions": "更新角色权限",
    "admin_account.create": "创建后台账号",
    "admin_account.update": "更新后台账号",
    "admin_account.update_roles": "更新后台账号角色",
    "admin_account.reset_password": "重置后台账号密码",
    "system.developer_app_health_changed": "开发者应用健康状态变更",
    "system.developer_app_health_recovered": "开发者应用健康恢复",
}
AUDIT_TARGET_TYPE_LABELS = {
    "user": "用户",
    "account": "账号",
    "plan": "卡密规格",
    "card": "卡密",
    "proxy": "代理",
    "settings": "配置",
    "developer_app": "开发者应用",
    "role": "后台角色",
    "admin_account": "后台账号",
}

DEFAULT_PURCHASE_URL = "https://t.me/"
DEFAULT_PURCHASE_BUTTON_TEXT = "联系 Telegram 购买"
DEFAULT_BOT_NOTICE_ENTRY_BUTTON_TEXT = "📢 公告栏"
_NOTICE_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
MAX_CARD_EXPORT_ROWS = 5000


class AdminLicenseService:
    """Admin-only operations for key specs, activation cards and slot authorization."""

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
    def _to_price_yuan(price_cents: int) -> str:
        return f"{(Decimal(price_cents) / Decimal(100)).quantize(Decimal('0.00'))}"

    @staticmethod
    def _serialize_plan(plan: PricingPlan) -> Dict[str, Any]:
        return {
            "plan_code": plan.plan_code,
            "display_name": plan.display_name,
            "billing_cycle": plan.billing_cycle,
            "price_cents": plan.price_cents,
            "price_yuan": AdminLicenseService._to_price_yuan(plan.price_cents),
            "duration_days": plan.duration_days,
            "is_active": plan.is_active,
            "sort_order": plan.sort_order,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
        }

    @staticmethod
    def _serialize_card(card: ActivationCard) -> Dict[str, Any]:
        loaded_slot_usages = card.__dict__.get("slot_usages") or []
        first_usage = loaded_slot_usages[0] if loaded_slot_usages else None
        loaded_used_user = card.__dict__.get("used_by_user")
        bound_account = None
        if first_usage and first_usage.__dict__.get("slot") is not None:
            bound_account = first_usage.slot.__dict__.get("current_account")
        bound_account_name = None
        if bound_account is not None:
            bound_account_name = (
                bound_account.username
                or bound_account.phone
                or bound_account.first_name
                or (str(bound_account.tg_user_id) if bound_account.tg_user_id is not None else None)
            )
        return {
            "id": card.id,
            "card_code": card.card_code,
            "plan_code": card.plan_code,
            "duration_days": card.duration_days,
            "is_active": card.is_active,
            "is_used": card.is_used,
            "expires_at": card.expires_at.isoformat() if card.expires_at else None,
            "used_by_user_id": card.used_by_user_id,
            "used_by_username": loaded_used_user.username if loaded_used_user else None,
            "used_at": card.used_at.isoformat() if card.used_at else None,
            "authorization_id": first_usage.authorization_id if first_usage else None,
            "bound_account_id": (
                first_usage.slot.current_account_id
                if first_usage and first_usage.__dict__.get("slot") is not None
                else None
            ),
            "bound_account_name": bound_account_name,
            "authorization_end_at": (
                first_usage.slot.end_at.isoformat()
                if first_usage and first_usage.__dict__.get("slot") is not None and first_usage.slot.end_at
                else None
            ),
            "created_at": card.created_at.isoformat() if card.created_at else None,
            "updated_at": card.updated_at.isoformat() if card.updated_at else None,
        }

    @staticmethod
    def _serialize_proxy(proxy: Proxy, assigned_account_name: Optional[str] = None) -> Dict[str, Any]:
        return {
            "proxy_id": proxy.proxy_id,
            "proxy_type": proxy.proxy_type,
            "host": proxy.host,
            "port": proxy.port,
            "username": proxy.username,
            "is_active": proxy.is_active,
            "is_healthy": proxy.is_healthy,
            "response_time_ms": proxy.response_time_ms,
            "usage_count": proxy.usage_count,
            "assigned_account_id": proxy.assigned_account_id,
            "assigned_account_name": assigned_account_name,
            "last_check_at": proxy.last_check_at.isoformat() if proxy.last_check_at else None,
            "created_at": proxy.created_at.isoformat() if proxy.created_at else None,
        }

    @staticmethod
    def _paginate_items(items: List[Dict[str, Any]], *, limit: int, offset: int) -> Dict[str, Any]:
        normalized_limit = max(1, min(500, int(limit)))
        normalized_offset = max(0, int(offset))
        sliced_items = items[normalized_offset:normalized_offset + normalized_limit]
        return {
            "items": sliced_items,
            "total": len(items),
            "limit": normalized_limit,
            "offset": normalized_offset,
        }

    @staticmethod
    def _generate_card_code(prefix: str = "") -> str:
        normalized_prefix = (prefix or "").strip().upper()
        random_part = "".join(secrets.choice(CARD_ALPHABET) for _ in range(16))
        return f"{normalized_prefix}{random_part}"

    @staticmethod
    def _mask_actor(actor: str) -> str:
        raw = (actor or "").strip()
        if not raw:
            return "admin"
        if "#" in raw:
            return raw
        if len(raw) <= 8:
            return "***"
        return f"{raw[:4]}***{raw[-4:]}"

    async def _append_audit(
        self,
        session: Any,
        *,
        actor: str,
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        developer_app_id: Optional[int] = None,
        old_value: Optional[Dict[str, Any]] = None,
        new_value: Optional[Dict[str, Any]] = None,
        detail: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        log_item = AdminAuditLog(
            actor=self._mask_actor(actor),
            action=action,
            target_type=target_type,
            target_id=target_id,
            developer_app_id=developer_app_id,
            old_value=old_value,
            new_value=new_value,
            detail=detail,
            ip_address=ip_address,
        )
        session.add(log_item)

    async def list_plans(self) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            result = await session.execute(
                select(PricingPlan)
                .where(PricingPlan.is_active.is_(True))
                .order_by(PricingPlan.sort_order.asc(), PricingPlan.price_cents.asc())
            )
            plans = result.scalars().all()
        return [self._serialize_plan(plan) for plan in plans]

    async def list_all_plans(self) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            result = await session.execute(
                select(PricingPlan).order_by(PricingPlan.sort_order.asc(), PricingPlan.price_cents.asc())
            )
            plans = result.scalars().all()
        return [self._serialize_plan(plan) for plan in plans]

    async def list_users(self, search: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))

        async with get_async_session() as session:
            base_stmt = (
                select(func.count(User.id))
            )
            stmt = (
                select(
                    User.id,
                    User.username,
                    User.email,
                    User.is_active,
                    User.created_at,
                    func.count(Account.account_id).filter(Account.is_active.is_(True)).label("account_count"),
                )
                .outerjoin(Account, Account.user_id == User.id)
                .group_by(User.id)
                .order_by(User.id.desc())
                .limit(limit)
                .offset(offset)
            )

            if search:
                search_value = f"%{search.strip()}%"
                search_condition = (User.username.ilike(search_value)) | (User.email.ilike(search_value))
                stmt = stmt.where(search_condition)
                base_stmt = base_stmt.where(search_condition)

            total = int((await session.execute(base_stmt)).scalar_one() or 0)
            rows = (await session.execute(stmt)).all()
            user_ids = [row.id for row in rows]

            user_app_map: Dict[int, Optional[int]] = {}
            if user_ids:
                keys = [f"user_dev_app:{uid}" for uid in user_ids]
                app_rows = (
                    await session.execute(
                        select(AppSetting.key, AppSetting.value).where(AppSetting.key.in_(keys))
                    )
                ).all()
                for key, value in app_rows:
                    try:
                        uid = int(str(key).split(":", 1)[1])
                        app_id = int((value or "").strip()) if (value or "").strip() else None
                        user_app_map[uid] = app_id
                    except Exception:
                        continue

            data: List[Dict[str, Any]] = []
            for row in rows:
                authorizations = await list_user_authorizations(int(row.id), session=session)
                current = authorizations[0] if authorizations else None
                data.append(
                    {
                        "id": row.id,
                        "username": row.username,
                        "email": row.email,
                        "is_active": row.is_active,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                        "account_count": int(row.account_count or 0),
                        "authorization_count": 1 if current else 0,
                        "developer_app_id": user_app_map.get(row.id),
                        "current_authorization": {
                            "start_at": current.start_at.isoformat() if current else None,
                            "end_at": current.end_at.isoformat() if current else None,
                            "status": current.status if current else None,
                        },
                    }
                )
            return {
                "items": data,
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    async def list_account_options(self, search: Optional[str] = None, limit: int = 300) -> List[Dict[str, Any]]:
        limit = max(1, min(1000, int(limit)))
        async with get_async_session() as session:
            stmt = (
                select(
                    Account.account_id,
                    Account.username,
                    Account.phone,
                    Account.tg_user_id,
                    User.id.label("user_id"),
                    User.username.label("owner_username"),
                )
                .join(User, User.id == Account.user_id)
                .order_by(Account.created_at.desc())
                .limit(limit)
            )
            if search:
                q = f"%{search.strip()}%"
                stmt = stmt.where(
                    (Account.username.ilike(q))
                    | (Account.phone.ilike(q))
                    | (User.username.ilike(q))
                )
            rows = (await session.execute(stmt)).all()
            return [
                {
                    "account_id": row.account_id,
                    "username": row.username,
                    "phone": row.phone,
                    "tg_user_id": row.tg_user_id,
                    "owner_user_id": row.user_id,
                    "owner_username": row.owner_username,
                    "label": f"{row.owner_username} / {row.username or row.phone or row.account_id}",
                }
                for row in rows
            ]

    async def list_proxies(
        self,
        *,
        search: Optional[str] = None,
        is_healthy: Optional[bool] = None,
        is_assigned: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        proxy_pool = get_proxy_pool()
        proxies = await proxy_pool.get_proxies(is_active=False, is_healthy=None)
        assigned_ids = [proxy.assigned_account_id for proxy in proxies if proxy.assigned_account_id]
        assigned_name_map: Dict[str, str] = {}
        if assigned_ids:
            async with get_async_session() as session:
                stmt = (
                    select(Account.account_id, Account.username, Account.phone, User.username.label("owner_username"))
                    .outerjoin(User, User.id == Account.user_id)
                    .where(Account.account_id.in_(assigned_ids))
                )
                rows = (await session.execute(stmt)).all()
                assigned_name_map = {
                    row.account_id: row.username or row.phone or row.owner_username or row.account_id
                    for row in rows
                }
        items = [
            self._serialize_proxy(proxy, assigned_name_map.get(proxy.assigned_account_id or ""))
            for proxy in proxies
        ]
        keyword = (search or "").strip().lower()
        if keyword:
            items = [
                item for item in items
                if keyword in f"{item['proxy_type']}://{item['host']}:{item['port']}".lower()
                or keyword in str(item.get("username") or "").lower()
                or keyword in str(item.get("assigned_account_id") or "").lower()
                or keyword in str(item.get("assigned_account_name") or "").lower()
            ]
        if is_healthy is not None:
            items = [item for item in items if bool(item.get("is_healthy")) is bool(is_healthy)]
        if is_assigned is not None:
            items = [item for item in items if bool(item.get("assigned_account_id")) is bool(is_assigned)]
        return self._paginate_items(items, limit=limit, offset=offset)

    async def get_purchase_settings(self) -> Dict[str, str]:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(AppSetting).where(AppSetting.key.in_(["purchase_url", "purchase_button_text"]))
                )
            ).scalars().all()
            values = {row.key: row.value for row in rows}
            return {
                "purchase_url": (values.get("purchase_url") or DEFAULT_PURCHASE_URL).strip(),
                "purchase_button_text": (
                    values.get("purchase_button_text") or DEFAULT_PURCHASE_BUTTON_TEXT
                ).strip(),
            }

    async def get_bot_notice_settings(self) -> Dict[str, Any]:
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
                                # 兼容旧版配置
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
            return {
                "enabled": enabled_raw in {"1", "true", "yes", "on"},
                "entry_button_text": str(entry_button_text).strip() or DEFAULT_BOT_NOTICE_ENTRY_BUTTON_TEXT,
                "message_text": message_text,
                "target_url": target_url,
                "updated_at": updated_at.isoformat() if updated_at else None,
            }

    async def update_purchase_settings(
        self,
        *,
        purchase_url: str,
        purchase_button_text: str,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, str]:
        url = (purchase_url or "").strip()
        button_text = (purchase_button_text or "").strip() or DEFAULT_PURCHASE_BUTTON_TEXT
        if not url:
            raise HTTPException(status_code=400, detail="购买链接不能为空")
        if not (
            url.startswith("https://t.me/")
            or url.startswith("https://telegram.me/")
            or url.startswith("tg://")
        ):
            raise HTTPException(status_code=400, detail="购买链接格式无效，仅支持 Telegram 聊天链接")

        async with get_async_session() as session:
            url_row = await session.get(AppSetting, "purchase_url")
            if not url_row:
                session.add(AppSetting(key="purchase_url", value=url))
            else:
                url_row.value = url

            text_row = await session.get(AppSetting, "purchase_button_text")
            if not text_row:
                session.add(AppSetting(key="purchase_button_text", value=button_text))
            else:
                text_row.value = button_text

            await self._append_audit(
                session,
                actor=actor,
                action="admin.update_purchase_settings",
                target_type="settings",
                target_id="purchase",
                detail={"purchase_url": url, "purchase_button_text": button_text},
                ip_address=ip_address,
            )
            await session.commit()

        return {"purchase_url": url, "purchase_button_text": button_text}

    async def update_bot_notice_settings(
        self,
        *,
        enabled: bool,
        entry_button_text: str,
        message_text: str,
        target_url: str,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_entry_button_text = (entry_button_text or "").strip() or DEFAULT_BOT_NOTICE_ENTRY_BUTTON_TEXT
        normalized_message_text = (message_text or "").strip()
        normalized_target_url = (target_url or "").strip()

        if enabled and not normalized_message_text:
            raise HTTPException(status_code=400, detail="启用公告时，公告正文不能为空")
        if normalized_target_url and not is_valid_button_url(normalized_target_url):
            raise HTTPException(status_code=400, detail="公告链接格式无效，请填写可公网访问的 http/https 链接")

        async with get_async_session() as session:
            values = {
                "bot_notice_enabled": "1" if enabled else "0",
                "bot_notice_entry_button_text": normalized_entry_button_text,
                "bot_notice_message_text": normalized_message_text,
                "bot_notice_target_url": normalized_target_url,
            }
            for key, value in values.items():
                row = await session.get(AppSetting, key)
                if row is None:
                    session.add(AppSetting(key=key, value=value))
                else:
                    row.value = value

            await self._append_audit(
                session,
                actor=actor,
                action="admin.update_bot_notice_settings",
                target_type="settings",
                target_id="bot_notice",
                detail={
                    "enabled": enabled,
                    "entry_button_text": normalized_entry_button_text,
                    "message_length": len(normalized_message_text),
                    "target_url": normalized_target_url,
                },
                ip_address=ip_address,
            )
            await session.commit()
        from backend.bot.notice_manager import get_bot_notice_manager

        refresh_summary = await get_bot_notice_manager().refresh_all_linked_users()
        result = await self.get_bot_notice_settings()
        result["refresh_summary"] = refresh_summary
        return result

    async def get_today_system_stats(self) -> Dict[str, Any]:
        timezone_name = settings.timezone or "Asia/Shanghai"
        now = datetime.now(ZoneInfo(timezone_name))
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
        end_of_day = (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).replace(tzinfo=None)

        async with get_async_session() as session:
            sent_messages = int(
                (
                    await session.execute(
                        select(func.count(TaskLog.id)).where(
                            TaskLog.result == "success",
                            TaskLog.send_at >= start_of_day,
                            TaskLog.send_at < end_of_day,
                        )
                    )
                ).scalar_one()
                or 0
            )
            bound_cards = int(
                (
                    await session.execute(
                        select(func.count(ActivationCard.id)).where(
                            ActivationCard.is_used.is_(True),
                            ActivationCard.used_at.is_not(None),
                            ActivationCard.used_at >= start_of_day,
                            ActivationCard.used_at < end_of_day,
                        )
                    )
                ).scalar_one()
                or 0
            )
            new_users = int(
                (
                    await session.execute(
                        select(func.count(User.id)).where(
                            User.created_at >= start_of_day,
                            User.created_at < end_of_day,
                        )
                    )
                ).scalar_one()
                or 0
            )

        return {
            "date": now.date().isoformat(),
            "timezone": timezone_name,
            "today_sent_messages": sent_messages,
            "today_bound_cards": bound_cards,
            "today_new_users": new_users,
        }

    async def list_developer_apps(
        self,
        *,
        search: Optional[str] = None,
        health_status: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        service = get_developer_app_service()
        apps = await service.list_apps()
        settings_data = await service.get_assignment_settings()
        keyword = (search or "").strip().lower()
        if keyword:
            apps = [
                item for item in apps
                if keyword in str(item.get("app_name") or "").lower()
                or keyword in str(item.get("api_id") or "").lower()
                or keyword in str(item.get("notes") or "").lower()
            ]
        normalized_health = (health_status or "").strip().lower()
        if normalized_health and normalized_health != "all":
            apps = [item for item in apps if str(item.get("health_status") or "").lower() == normalized_health]
        if is_active is not None:
            apps = [item for item in apps if bool(item.get("is_active")) is bool(is_active)]
        page = self._paginate_items(apps, limit=limit, offset=offset)
        return {**page, "settings": settings_data}

    async def create_developer_app(
        self,
        *,
        app_name: str,
        api_id: int,
        api_hash: str,
        is_active: bool = True,
        max_accounts: int = 0,
        selection_weight: int = 100,
        notes: Optional[str] = None,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        service = get_developer_app_service()
        data = await service.create_app(
            app_name=app_name,
            api_id=api_id,
            api_hash=api_hash,
            is_active=is_active,
            max_accounts=max_accounts,
            selection_weight=selection_weight,
            notes=notes,
        )
        async with get_async_session() as session:
            await self._append_audit(
                session,
                actor=actor,
                action="admin.create_developer_app",
                target_type="developer_app",
                target_id=str(data["id"]),
                developer_app_id=int(data["id"]),
                old_value=None,
                new_value={
                    "id": int(data["id"]),
                    "app_name": data["app_name"],
                    "api_id": data["api_id"],
                    "is_active": data["is_active"],
                    "max_accounts": data["max_accounts"],
                    "selection_weight": data["selection_weight"],
                    "credentials_version": data.get("credentials_version"),
                    "last_rotated_at": data.get("last_rotated_at"),
                    "health_status": data.get("health_status"),
                },
                detail={
                    "app_name": data["app_name"],
                    "api_id": data["api_id"],
                    "is_active": data["is_active"],
                    "max_accounts": data["max_accounts"],
                    "selection_weight": data["selection_weight"],
                },
                ip_address=ip_address,
            )
            await session.commit()
        return data

    async def update_developer_app(
        self,
        app_id: int,
        *,
        app_name: Optional[str] = None,
        api_hash: Optional[str] = None,
        is_active: Optional[bool] = None,
        max_accounts: Optional[int] = None,
        selection_weight: Optional[int] = None,
        notes: Optional[str] = None,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        service = get_developer_app_service()
        data = await service.update_app(
            app_id,
            app_name=app_name,
            api_hash=api_hash,
            is_active=is_active,
            max_accounts=max_accounts,
            selection_weight=selection_weight,
            notes=notes,
        )
        async with get_async_session() as session:
            await self._append_audit(
                session,
                actor=actor,
                action="admin.update_developer_app",
                target_type="developer_app",
                target_id=str(app_id),
                developer_app_id=int(app_id),
                old_value=data.get("old_value"),
                new_value=data.get("new_value"),
                detail={
                    "app_name": app_name,
                    "api_hash_updated": api_hash is not None,
                    "is_active": is_active,
                    "max_accounts": max_accounts,
                    "selection_weight": selection_weight,
                    "notes": notes,
                    "rotated_accounts": data.get("rotated_accounts", 0),
                },
                ip_address=ip_address,
            )
            await session.commit()
        return data

    async def update_developer_app_settings(
        self,
        *,
        assignment_mode: str,
        alert_tg_user_ids: str,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        service = get_developer_app_service()
        result = await service.update_assignment_settings(
            assignment_mode=assignment_mode,
            alert_tg_user_ids=alert_tg_user_ids,
        )
        async with get_async_session() as session:
            await self._append_audit(
                session,
                actor=actor,
                action="admin.update_developer_app_settings",
                target_type="settings",
                target_id="developer_app_assignment",
                old_value={
                    "assignment_mode": result["old_assignment_mode"],
                    "alert_tg_user_ids_text": result["old_alert_tg_user_ids_text"],
                },
                new_value={
                    "assignment_mode": result["new_assignment_mode"],
                    "alert_tg_user_ids_text": result["new_alert_tg_user_ids_text"],
                },
                detail={
                    "assignment_mode": result["new_assignment_mode"],
                    "alert_tg_user_ids": result["alert_tg_user_ids"],
                },
                ip_address=ip_address,
            )
            await session.commit()
        return {
            "assignment_mode": result["new_assignment_mode"],
            "alert_tg_user_ids": result["alert_tg_user_ids"],
            "alert_tg_user_ids_text": result["new_alert_tg_user_ids_text"],
        }

    async def check_developer_app_health(
        self,
        app_id: int,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        service = get_developer_app_service()
        return await service.check_app_health(
            app_id,
            actor=self._mask_actor(actor),
            ip_address=ip_address,
            notify_admins=True,
            force_audit=True,
        )

    async def set_default_developer_app(
        self,
        app_id: int,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> None:
        service = get_developer_app_service()
        result = await service.set_default_app(app_id)
        async with get_async_session() as session:
            await self._append_audit(
                session,
                actor=actor,
                action="admin.set_default_developer_app",
                target_type="developer_app",
                target_id=str(app_id),
                developer_app_id=int(app_id),
                old_value={"default_developer_app_id": result.get("old_default_app_id")},
                new_value={"default_developer_app_id": result.get("new_default_app_id")},
                detail=result,
                ip_address=ip_address,
            )
            await session.commit()

    async def set_user_developer_app(
        self,
        user_id: int,
        developer_app_id: Optional[int],
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with get_async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id).limit(1))
            ).scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")

        service = get_developer_app_service()
        result = await service.set_user_preferred_app_id(user_id, developer_app_id)

        async with get_async_session() as session:
            await self._append_audit(
                session,
                actor=actor,
                action="admin.set_user_developer_app",
                target_type="user",
                target_id=str(user_id),
                developer_app_id=developer_app_id,
                old_value={"developer_app_id": result.get("old_app_id")},
                new_value={"developer_app_id": result.get("new_app_id")},
                detail={"developer_app_id": developer_app_id},
                ip_address=ip_address,
            )
            await session.commit()
        return {
            "user_id": int(user_id),
            "developer_app_id": developer_app_id,
            "old_developer_app_id": result.get("old_app_id"),
        }

    async def add_proxy(
        self,
        *,
        proxy_type: str,
        host: str,
        port: int,
        username: Optional[str] = None,
        password: Optional[str] = None,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        proxy_pool = get_proxy_pool()
        try:
            proxy = await proxy_pool.add_proxy(
                proxy_type=proxy_type,
                host=host.strip(),
                port=port,
                username=username.strip() if username else None,
                password=password or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"添加代理失败: {exc}") from exc

        async with get_async_session() as session:
            await self._append_audit(
                session,
                actor=actor,
                action="admin.add_proxy",
                target_type="proxy",
                target_id=str(proxy.proxy_id),
                detail={"proxy_type": proxy.proxy_type, "host": proxy.host, "port": proxy.port},
                ip_address=ip_address,
            )
            await session.commit()

        return self._serialize_proxy(proxy)

    async def check_proxy_health(
        self,
        proxy_id: int,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        proxy_pool = get_proxy_pool()
        status = await proxy_pool.check_health(proxy_id)
        async with get_async_session() as session:
            await self._append_audit(
                session,
                actor=actor,
                action="admin.check_proxy_health",
                target_type="proxy",
                target_id=str(proxy_id),
                detail={
                    "is_healthy": status.is_healthy,
                    "response_time_ms": status.response_time_ms,
                    "error": status.error or None,
                },
                ip_address=ip_address,
            )
            await session.commit()
        return {
            "is_healthy": status.is_healthy,
            "response_time_ms": status.response_time_ms,
            "error": status.error or None,
        }

    async def delete_proxy(
        self,
        proxy_id: int,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> None:
        proxy_pool = get_proxy_pool()
        deleted = await proxy_pool.delete_proxy(proxy_id)
        if not deleted:
            raise HTTPException(status_code=400, detail="代理删除失败（可能已分配到账号）")
        async with get_async_session() as session:
            await self._append_audit(
                session,
                actor=actor,
                action="admin.delete_proxy",
                target_type="proxy",
                target_id=str(proxy_id),
                detail={},
                ip_address=ip_address,
            )
            await session.commit()

    async def assign_proxy(
        self,
        proxy_id: int,
        account_id: str,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> None:
        async with get_async_session() as session:
            account = (
                await session.execute(select(Account).where(Account.account_id == account_id).limit(1))
            ).scalar_one_or_none()
            if not account:
                raise HTTPException(status_code=404, detail="账号不存在")

        proxy_pool = get_proxy_pool()
        assigned = await proxy_pool.assign_proxy(account_id, proxy_id)
        if not assigned:
            raise HTTPException(status_code=400, detail="代理分配失败（可能已被占用）")
        async with get_async_session() as session:
            await self._append_audit(
                session,
                actor=actor,
                action="admin.assign_proxy",
                target_type="proxy",
                target_id=str(proxy_id),
                detail={"account_id": account_id},
                ip_address=ip_address,
            )
            await session.commit()

    async def unassign_proxy(
        self,
        proxy_id: int,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> None:
        proxy_pool = get_proxy_pool()
        proxy = await proxy_pool.get_proxy(proxy_id)
        if not proxy:
            raise HTTPException(status_code=404, detail="代理不存在")
        if not proxy.assigned_account_id:
            raise HTTPException(status_code=400, detail="代理未分配账号")

        unassigned = await proxy_pool.unassign_proxy(proxy.assigned_account_id)
        if not unassigned:
            raise HTTPException(status_code=400, detail="代理解绑失败")
        async with get_async_session() as session:
            await self._append_audit(
                session,
                actor=actor,
                action="admin.unassign_proxy",
                target_type="proxy",
                target_id=str(proxy_id),
                detail={"account_id": proxy.assigned_account_id},
                ip_address=ip_address,
            )
            await session.commit()

    async def list_user_accounts(self, user_id: int) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id).limit(1))
            ).scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")

            accounts = (
                await session.execute(
                    select(Account).where(Account.user_id == user_id).order_by(Account.created_at.desc())
                )
            ).scalars().all()

            return [
                {
                    "account_id": a.account_id,
                    "tg_user_id": a.tg_user_id,
                    "username": a.username,
                    "first_name": a.first_name,
                    "phone": a.phone,
                    "developer_app_id": a.developer_app_id,
                    "is_active": a.is_active,
                    "is_banned": a.is_banned,
                    "health_status": a.health_status,
                    "is_flooding": a.is_flooding,
                    "messages_sent": a.messages_sent,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    **(await get_account_authorization_summary(a.account_id, session=session)).to_dict(),
                }
                for a in accounts
            ]

    async def admin_delete_account(
        self,
        account_id: str,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> None:
        from backend.bot.account.manager import get_account_manager

        account_manager = get_account_manager()
        ok = await account_manager.delete_account(account_id)
        if not ok:
            raise HTTPException(status_code=404, detail="账号不存在")

        async with get_async_session() as session:
            await self._append_audit(
                session,
                actor=actor,
                action="admin.delete_account",
                target_type="account",
                target_id=account_id,
                detail={},
                ip_address=ip_address,
            )
            await session.commit()

    async def reset_user_password(
        self,
        user_id: int,
        new_password: str,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> None:
        if len(new_password or "") < 6:
            raise HTTPException(status_code=400, detail="新密码至少 6 位")

        auth_service = get_auth_service()
        async with get_async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id).limit(1))
            ).scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")
            user.password_hash = auth_service.get_password_hash(new_password)
            user.bot_initial_password_viewable = False
            user.password_changed_after_bot_registration = True
            await self._append_audit(
                session,
                actor=actor,
                action="admin.reset_user_password",
                target_type="user",
                target_id=str(user_id),
                detail={},
                ip_address=ip_address,
            )
            await session.commit()

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

            await self._append_audit(
                session,
                actor=actor,
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
            return self._serialize_plan(plan)

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
            await self._append_audit(
                session,
                actor=actor,
                action="admin.update_plan",
                target_type="plan",
                target_id=normalized_code,
                old_value=None,
                new_value=self._serialize_plan(plan),
                detail={"created": True},
                ip_address=ip_address,
            )
            await session.commit()
            await session.refresh(plan)
            return self._serialize_plan(plan)

    async def generate_cards(
        self,
        plan_code: str,
        quantity: int,
        expires_at: Optional[datetime] = None,
        prefix: str = "",
        *,
        creator_account_id: Optional[int] = None,
        owner_account_id: Optional[int] = None,
        root_master_account_id: Optional[int] = None,
        direct_parent_account_id: Optional[int] = None,
        settlement_unit_price_cents: Optional[int] = None,
        card_source_type: str = "legacy",
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if quantity <= 0 or quantity > 500:
            raise HTTPException(status_code=400, detail="quantity 取值范围为 1~500")

        if expires_at and expires_at <= datetime.now():
            raise HTTPException(status_code=400, detail="expires_at 必须是未来时间")

        normalized_prefix = (prefix or "").strip().upper()
        if len(normalized_prefix) > 20:
            raise HTTPException(status_code=400, detail="prefix 最长 20 位")
        if normalized_prefix and not all(ch in CARD_ALPHABET for ch in normalized_prefix):
            raise HTTPException(status_code=400, detail="prefix 仅支持大写字母和数字")
        async with get_async_session() as session:
            try:
                plan_result = await session.execute(
                    select(PricingPlan).where(PricingPlan.plan_code == plan_code).limit(1)
                )
                plan = plan_result.scalar_one_or_none()
            except SQLAlchemyError as exc:
                logger.exception("查询套餐失败: plan_code={}, error={}", plan_code, exc)
                raise HTTPException(status_code=500, detail="查询套餐失败，请稍后重试") from exc
            if not plan:
                raise HTTPException(status_code=404, detail="套餐不存在")
            resolved_duration_days = int(plan.duration_days)
            if resolved_duration_days <= 0:
                raise HTTPException(status_code=400, detail="套餐时长无效，请检查卡密规格配置")
            generated_codes: set[str] = set()
            max_attempts = quantity * 20
            attempts = 0
            while len(generated_codes) < quantity and attempts < max_attempts:
                attempts += 1
                generated_codes.add(self._generate_card_code(prefix=normalized_prefix))

            if len(generated_codes) < quantity:
                raise HTTPException(status_code=500, detail="生成卡密失败，请重试")

            # 过滤数据库中已存在的编码（极低概率冲突，仍做防御）
            while True:
                existing_result = await session.execute(
                    select(ActivationCard.card_code).where(ActivationCard.card_code.in_(list(generated_codes)))
                )
                existing_codes = {row[0] for row in existing_result.all()}
                if not existing_codes:
                    break
                generated_codes -= existing_codes
                while len(generated_codes) < quantity:
                    generated_codes.add(self._generate_card_code(prefix=normalized_prefix))

            created_cards: List[ActivationCard] = [
                ActivationCard(
                    card_code=code,
                    plan_code=plan_code,
                    duration_days=resolved_duration_days,
                    is_active=True,
                    is_used=False,
                    expires_at=expires_at,
                    creator_account_id=creator_account_id,
                    owner_account_id=owner_account_id,
                    direct_parent_account_id=direct_parent_account_id,
                    root_master_account_id=root_master_account_id,
                    settlement_unit_price_cents=settlement_unit_price_cents if settlement_unit_price_cents is not None else int(plan.price_cents or 0),
                    card_source_type=(card_source_type or "").strip() or "legacy",
                )
                for code in sorted(generated_codes)
            ]
            session.add_all(created_cards)
            await self._append_audit(
                session,
                actor=actor,
                action="admin.generate_cards",
                target_type="plan",
                target_id=plan_code,
                detail={
                    "quantity": quantity,
                    "duration_days": resolved_duration_days,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                    "prefix": normalized_prefix,
                    "sample_card": created_cards[0].card_code if created_cards else None,
                },
                ip_address=ip_address,
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                logger.warning(
                    "生成卡密写入冲突: plan_code={}, quantity={}, prefix={}, error={}",
                    plan_code,
                    quantity,
                    normalized_prefix,
                    exc,
                )
                raise HTTPException(status_code=409, detail="生成卡密冲突，请稍后重试") from exc
            except SQLAlchemyError as exc:
                await session.rollback()
                logger.exception(
                    "生成卡密数据库异常: plan_code={}, quantity={}, prefix={}, error={}",
                    plan_code,
                    quantity,
                    normalized_prefix,
                    exc,
                )
                raise HTTPException(status_code=500, detail="生成卡密失败，请稍后重试") from exc
            for card in created_cards:
                await session.refresh(card)

        return [self._serialize_card(card) for card in created_cards]

    async def list_cards(
        self,
        plan_code: Optional[str] = None,
        is_used: Optional[bool] = None,
        is_active: Optional[bool] = None,
        keyword: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))

        stmt: Select[Any] = select(ActivationCard).options(
            selectinload(ActivationCard.slot_usages)
            .selectinload(UserAuthorizationCard.slot)
            .selectinload(UserAuthorization.current_account),
            selectinload(ActivationCard.used_by_user),
        )
        count_stmt: Select[Any] = select(func.count(ActivationCard.id))
        conditions = []
        if plan_code:
            conditions.append(ActivationCard.plan_code == plan_code)
        if is_used is not None:
            conditions.append(ActivationCard.is_used.is_(is_used))
        if is_active is not None:
            conditions.append(ActivationCard.is_active.is_(is_active))
        if keyword:
            keyword_value = f"%{keyword.strip()}%"
            conditions.append(
                ActivationCard.card_code.ilike(keyword_value)
                | ActivationCard.plan_code.ilike(keyword_value)
            )
        if conditions:
            stmt = stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))

        sortable_fields = {
            "created_at": ActivationCard.created_at,
            "used_at": ActivationCard.used_at,
            "expires_at": ActivationCard.expires_at,
        }
        sort_column = sortable_fields.get((sort_by or "").strip(), ActivationCard.created_at)
        sort_mode = (sort_order or "desc").strip().lower()
        if sort_mode == "asc":
            stmt = stmt.order_by(sort_column.asc().nullslast(), ActivationCard.id.desc())
        else:
            stmt = stmt.order_by(sort_column.desc().nullslast(), ActivationCard.id.desc())
        stmt = stmt.limit(limit).offset(offset)

        async with get_async_session() as session:
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            used_count_stmt: Select[Any] = select(func.count(ActivationCard.id))
            unused_count_stmt: Select[Any] = select(func.count(ActivationCard.id))
            used_conditions = list(conditions) + [ActivationCard.is_used.is_(True)]
            unused_conditions = list(conditions) + [ActivationCard.is_used.is_(False)]
            used_count_stmt = used_count_stmt.where(and_(*used_conditions))
            unused_count_stmt = unused_count_stmt.where(and_(*unused_conditions))
            used_total = int((await session.execute(used_count_stmt)).scalar_one() or 0)
            unused_total = int((await session.execute(unused_count_stmt)).scalar_one() or 0)
            result = await session.execute(stmt)
            cards = result.scalars().all()

        return {
            "items": [self._serialize_card(card) for card in cards],
            "total": total,
            "limit": limit,
            "offset": offset,
            "stats": {
                "total": total,
                "used": used_total,
                "unused": unused_total,
            },
        }

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

            plan_snapshot = self._serialize_plan(plan)
            await session.delete(plan)
            await self._append_audit(
                session,
                actor=actor,
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

    async def export_cards_xlsx(
        self,
        *,
        plan_code: Optional[str] = None,
        is_used: Optional[bool] = None,
        is_active: Optional[bool] = None,
        max_rows: int = MAX_CARD_EXPORT_ROWS,
    ) -> Tuple[bytes, int]:
        page_data = await self.list_cards(
            plan_code=plan_code,
            is_used=is_used,
            is_active=is_active,
            limit=max_rows + 1,
            offset=0,
        )
        rows = page_data["items"]
        if len(rows) > max_rows:
            raise HTTPException(
                status_code=400,
                detail=f"导出数量超过限制（最多 {max_rows} 条），请缩小筛选范围后重试",
            )

        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font
        except ModuleNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail="当前环境缺少 openpyxl，暂时无法导出 XLSX；但服务其他功能可正常使用。",
            ) from exc

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "卡密列表"

        headers = ["卡密", "套餐", "时长(天)", "状态", "激活用户", "激活时间", "创建时间", "失效时间"]
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)

        for row in rows:
            status = "已失效"
            if row.get("is_active"):
                status = "已使用" if row.get("is_used") else "可用"
            used_user = row.get("used_by_username") or (
                f"用户ID:{row['used_by_user_id']}" if row.get("used_by_user_id") is not None else ""
            )
            sheet.append(
                [
                    row.get("card_code") or "",
                    row.get("plan_code") or "",
                    row.get("duration_days") or "",
                    status,
                    used_user,
                    row.get("used_at") or "",
                    row.get("created_at") or "",
                    row.get("expires_at") or "",
                ]
            )

        sheet.column_dimensions["A"].width = 28
        sheet.column_dimensions["B"].width = 14
        sheet.column_dimensions["C"].width = 10
        sheet.column_dimensions["D"].width = 10
        sheet.column_dimensions["E"].width = 18
        sheet.column_dimensions["F"].width = 20
        sheet.column_dimensions["G"].width = 20
        sheet.column_dimensions["H"].width = 20

        buffer = BytesIO()
        workbook.save(buffer)
        workbook.close()
        return buffer.getvalue(), len(rows)

    async def list_authorizations(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))

        count_stmt: Select[Any] = select(func.count(UserAuthorization.authorization_id))
        stmt: Select[Any] = (
            select(UserAuthorization, User.username, Account.username, Account.phone, Account.tg_user_id)
            .join(User, User.id == UserAuthorization.user_id)
            .outerjoin(Account, Account.account_id == UserAuthorization.current_account_id)
            .order_by(UserAuthorization.end_at.asc(), UserAuthorization.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status:
            stmt = stmt.where(UserAuthorization.status == status)
            count_stmt = count_stmt.where(UserAuthorization.status == status)

        async with get_async_session() as session:
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (await session.execute(stmt)).all()

        data: List[Dict[str, Any]] = []
        for slot, owner_username, account_username, account_phone, account_tg_user_id in rows:
            data.append(
                {
                    "authorization_id": slot.authorization_id,
                    "user_id": slot.user_id,
                    "owner_username": owner_username,
                    "status": slot.status,
                    "current_account_id": slot.current_account_id,
                    "current_account_username": account_username,
                    "current_account_phone": account_phone,
                    "current_account_tg_user_id": account_tg_user_id,
                    "total_duration_days": slot.total_duration_days,
                    "start_at": slot.start_at.isoformat() if slot.start_at else None,
                    "end_at": slot.end_at.isoformat() if slot.end_at else None,
                    "created_at": slot.created_at.isoformat() if slot.created_at else None,
                    "updated_at": slot.updated_at.isoformat() if slot.updated_at else None,
                }
            )
        return {
            "items": data,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def set_card_active(
        self,
        card_code: str,
        is_active: bool,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_code = (card_code or "").strip().upper()
        async with get_async_session() as session:
            result = await session.execute(
                select(ActivationCard)
                .where(ActivationCard.card_code == normalized_code)
                .limit(1)
            )
            card = result.scalar_one_or_none()
            if not card:
                raise HTTPException(status_code=404, detail="卡密不存在")

            if card.is_used and is_active:
                raise HTTPException(status_code=400, detail="已使用卡密不能重新启用")

            card.is_active = is_active
            await self._append_audit(
                session,
                actor=actor,
                action="admin.set_card_active",
                target_type="card",
                target_id=normalized_code,
                detail={"is_active": is_active, "is_used": card.is_used},
                ip_address=ip_address,
            )
            await session.commit()
            await session.refresh(card)

        return self._serialize_card(card)

    async def create_single_card(
        self,
        plan_code: str,
        valid_days: Optional[int] = None,
        prefix: str = "",
        *,
        creator_account_id: Optional[int] = None,
        owner_account_id: Optional[int] = None,
        root_master_account_id: Optional[int] = None,
        direct_parent_account_id: Optional[int] = None,
        settlement_unit_price_cents: Optional[int] = None,
        card_source_type: str = "legacy",
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        expires_at = None
        if valid_days is not None:
            if valid_days <= 0:
                raise HTTPException(status_code=400, detail="valid_days 必须大于 0")
            expires_at = datetime.now() + timedelta(days=valid_days)

        cards = await self.generate_cards(
            plan_code=plan_code,
            quantity=1,
            expires_at=expires_at,
            prefix=prefix,
            creator_account_id=creator_account_id,
            owner_account_id=owner_account_id,
            root_master_account_id=root_master_account_id,
            direct_parent_account_id=direct_parent_account_id,
            settlement_unit_price_cents=settlement_unit_price_cents,
            card_source_type=card_source_type,
            actor=actor,
            ip_address=ip_address,
        )
        return cards[0]

    async def list_audit_logs(
        self,
        action: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        developer_app_id: Optional[int] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))

        stmt: Select[Any] = select(AdminAuditLog)
        count_stmt: Select[Any] = select(func.count(AdminAuditLog.id))
        conditions = []
        if action:
            conditions.append(AdminAuditLog.action == action)
        if target_type:
            conditions.append(AdminAuditLog.target_type == target_type)
        if target_id:
            conditions.append(AdminAuditLog.target_id == target_id)
        if developer_app_id is not None:
            conditions.append(AdminAuditLog.developer_app_id == int(developer_app_id))
        normalized_keyword = (keyword or "").strip()
        if normalized_keyword:
            keyword_condition = (
                AdminAuditLog.actor.ilike(f"%{normalized_keyword}%")
                | AdminAuditLog.action.ilike(f"%{normalized_keyword}%")
                | AdminAuditLog.target_id.ilike(f"%{normalized_keyword}%")
            )
            conditions.append(keyword_condition)
        if conditions:
            stmt = stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))
        stmt = stmt.order_by(AdminAuditLog.id.desc()).limit(limit).offset(offset)

        async with get_async_session() as session:
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (await session.execute(stmt)).scalars().all()

        items = [
            {
                "id": row.id,
                "actor": row.actor,
                "action": row.action,
                "action_label": AUDIT_ACTION_LABELS.get(row.action, row.action),
                "target_type": row.target_type,
                "target_type_label": (
                    AUDIT_TARGET_TYPE_LABELS.get(row.target_type, row.target_type)
                    if row.target_type
                    else None
                ),
                "target_id": row.target_id,
                "developer_app_id": row.developer_app_id,
                "old_value": row.old_value,
                "new_value": row.new_value,
                "detail": row.detail,
                "ip_address": row.ip_address,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }


_admin_license_service: Optional[AdminLicenseService] = None


def get_admin_license_service() -> AdminLicenseService:
    """Get singleton admin license service."""
    global _admin_license_service
    if _admin_license_service is None:
        _admin_license_service = AdminLicenseService()
    return _admin_license_service
