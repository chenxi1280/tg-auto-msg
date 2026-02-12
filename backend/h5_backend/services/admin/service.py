"""Admin-side billing and card management service."""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import Select, and_, func, select

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
    TelegramDeveloperApp,
    User,
    UserSubscription,
)
from backend.h5_backend.services.auth.service import get_auth_service


CARD_ALPHABET = string.ascii_uppercase + string.digits
AUDIT_ACTION_LABELS = {
    "admin.update_plan": "更新套餐配置",
    "admin.generate_cards": "批量生成卡密",
    "admin.set_card_active": "修改卡密状态",
    "admin.update_user_subscription": "更新用户订阅",
    "admin.reset_user_password": "重置用户密码",
    "admin.delete_account": "删除账号",
    "admin.add_proxy": "新增代理",
    "admin.check_proxy_health": "检测代理健康",
    "admin.delete_proxy": "删除代理",
    "admin.assign_proxy": "分配代理",
    "admin.unassign_proxy": "解绑代理",
    "admin.update_purchase_settings": "更新购买入口配置",
    "admin.create_developer_app": "新增开发者应用",
    "admin.update_developer_app": "更新开发者应用",
    "admin.set_default_developer_app": "设置默认开发者应用",
    "admin.set_user_developer_app": "设置用户开发者应用",
}
AUDIT_TARGET_TYPE_LABELS = {
    "user": "用户",
    "account": "账号",
    "plan": "套餐",
    "card": "卡密",
    "proxy": "代理",
    "settings": "配置",
    "developer_app": "开发者应用",
}

DEFAULT_PURCHASE_URL = "https://t.me/"
DEFAULT_PURCHASE_BUTTON_TEXT = "联系 Telegram 购买"


class AdminBillingService:
    """Admin-only operations for plans and activation cards."""

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
            "price_yuan": AdminBillingService._to_price_yuan(plan.price_cents),
            "duration_days": plan.duration_days,
            "is_active": plan.is_active,
            "sort_order": plan.sort_order,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
        }

    @staticmethod
    def _serialize_card(card: ActivationCard) -> Dict[str, Any]:
        return {
            "id": card.id,
            "card_code": card.card_code,
            "plan_code": card.plan_code,
            "duration_days": card.duration_days,
            "is_active": card.is_active,
            "is_used": card.is_used,
            "expires_at": card.expires_at.isoformat() if card.expires_at else None,
            "used_by_user_id": card.used_by_user_id,
            "used_at": card.used_at.isoformat() if card.used_at else None,
            "created_at": card.created_at.isoformat() if card.created_at else None,
            "updated_at": card.updated_at.isoformat() if card.updated_at else None,
        }

    @staticmethod
    def _serialize_proxy(proxy: Proxy) -> Dict[str, Any]:
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
            "last_check_at": proxy.last_check_at.isoformat() if proxy.last_check_at else None,
            "created_at": proxy.created_at.isoformat() if proxy.created_at else None,
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
                select(PricingPlan).order_by(PricingPlan.sort_order.asc(), PricingPlan.price_cents.asc())
            )
            plans = result.scalars().all()
        return [self._serialize_plan(plan) for plan in plans]

    async def _get_latest_active_subscription(
        self,
        user_id: int,
        session: Any,
    ) -> Optional[UserSubscription]:
        result = await session.execute(
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
        sub = result.scalar_one_or_none()
        if sub and sub.end_at <= datetime.now():
            sub.status = "expired"
            await session.flush()
            return None
        return sub

    async def list_users(self, search: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))

        async with get_async_session() as session:
            stmt = (
                select(
                    User.id,
                    User.username,
                    User.email,
                    User.is_active,
                    User.created_at,
                    func.count(Account.account_id).label("account_count"),
                )
                .outerjoin(Account, Account.user_id == User.id)
                .group_by(User.id)
                .order_by(User.id.desc())
                .limit(limit)
                .offset(offset)
            )

            if search:
                search_value = f"%{search.strip()}%"
                stmt = stmt.where(
                    (User.username.ilike(search_value)) | (User.email.ilike(search_value))
                )

            rows = (await session.execute(stmt)).all()
            user_ids = [row.id for row in rows]

            sub_map: Dict[int, UserSubscription] = {}
            if user_ids:
                sub_rows = await session.execute(
                    select(UserSubscription)
                    .where(
                        and_(
                            UserSubscription.user_id.in_(user_ids),
                            UserSubscription.status == "active",
                        )
                    )
                    .order_by(UserSubscription.user_id.asc(), UserSubscription.end_at.desc())
                )
                for sub in sub_rows.scalars().all():
                    if sub.user_id not in sub_map and sub.end_at > datetime.now():
                        sub_map[sub.user_id] = sub

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
                sub = sub_map.get(row.id)
                data.append(
                    {
                        "id": row.id,
                        "username": row.username,
                        "email": row.email,
                        "is_active": row.is_active,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                        "account_count": int(row.account_count or 0),
                        "developer_app_id": user_app_map.get(row.id),
                        "subscription": {
                            "plan_code": sub.plan_code if sub else None,
                            "start_at": sub.start_at.isoformat() if sub else None,
                            "end_at": sub.end_at.isoformat() if sub else None,
                            "status": sub.status if sub else None,
                        },
                    }
                )
            return data

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

    async def list_proxies(self) -> List[Dict[str, Any]]:
        proxy_pool = get_proxy_pool()
        proxies = await proxy_pool.get_proxies(is_active=False, is_healthy=None)
        return [self._serialize_proxy(proxy) for proxy in proxies]

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

    async def list_developer_apps(self) -> Dict[str, Any]:
        service = get_developer_app_service()
        apps = await service.list_apps()
        return {"apps": apps}

    async def create_developer_app(
        self,
        *,
        app_name: str,
        api_id: int,
        api_hash: str,
        is_active: bool = True,
        max_accounts: int = 0,
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
                    "credentials_version": data.get("credentials_version"),
                    "last_rotated_at": data.get("last_rotated_at"),
                },
                detail={
                    "app_name": data["app_name"],
                    "api_id": data["api_id"],
                    "is_active": data["is_active"],
                    "max_accounts": data["max_accounts"],
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
                    "notes": notes,
                    "rotated_accounts": data.get("rotated_accounts", 0),
                },
                ip_address=ip_address,
            )
            await session.commit()
        return data

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

    async def update_user_subscription(
        self,
        user_id: int,
        plan_code: Optional[str] = None,
        end_at: Optional[datetime] = None,
        extend_days: Optional[int] = None,
        set_inactive: bool = False,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if extend_days is not None and extend_days == 0:
            raise HTTPException(status_code=400, detail="extend_days 不能为 0")
        if end_at and end_at <= datetime.now():
            raise HTTPException(status_code=400, detail="end_at 必须是未来时间")

        async with get_async_session() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id).limit(1))
            ).scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="用户不存在")

            plan = None
            if plan_code:
                plan = (
                    await session.execute(
                        select(PricingPlan).where(PricingPlan.plan_code == plan_code).limit(1)
                    )
                ).scalar_one_or_none()
                if not plan:
                    raise HTTPException(status_code=404, detail="套餐不存在")

            sub = await self._get_latest_active_subscription(user_id, session)
            now = datetime.now()

            if set_inactive:
                if sub:
                    sub.status = "cancelled"
                    await self._append_audit(
                        session,
                        actor=actor,
                        action="admin.update_user_subscription",
                        target_type="user",
                        target_id=str(user_id),
                        detail={
                            "set_inactive": True,
                            "previous_end_at": sub.end_at.isoformat() if sub.end_at else None,
                        },
                        ip_address=ip_address,
                    )
                    await session.commit()
                return {"user_id": user_id, "subscription": None}

            if sub is None:
                resolved_end_at = end_at
                if resolved_end_at is None:
                    if extend_days:
                        resolved_end_at = now + timedelta(days=extend_days)
                    elif plan:
                        resolved_end_at = now + timedelta(days=plan.duration_days)
                if resolved_end_at is None:
                    raise HTTPException(status_code=400, detail="需要提供 end_at 或 extend_days 或 plan_code")

                new_sub = UserSubscription(
                    user_id=user_id,
                    plan_code=plan_code,
                    source="admin",
                    card_code=None,
                    start_at=now,
                    end_at=resolved_end_at,
                    status="active",
                )
                session.add(new_sub)
                await self._append_audit(
                    session,
                    actor=actor,
                    action="admin.update_user_subscription",
                    target_type="user",
                    target_id=str(user_id),
                    detail={
                        "created": True,
                        "plan_code": plan_code,
                        "end_at": resolved_end_at.isoformat() if resolved_end_at else None,
                        "extend_days": extend_days,
                    },
                    ip_address=ip_address,
                )
                await session.commit()
                await session.refresh(new_sub)
                return {
                    "user_id": user_id,
                    "subscription": {
                        "id": new_sub.id,
                        "plan_code": new_sub.plan_code,
                        "start_at": new_sub.start_at.isoformat(),
                        "end_at": new_sub.end_at.isoformat(),
                        "status": new_sub.status,
                    },
                }

            if plan_code:
                sub.plan_code = plan_code
            if end_at:
                sub.end_at = end_at
            elif extend_days:
                sub.end_at = sub.end_at + timedelta(days=extend_days)
            elif plan:
                sub.end_at = sub.end_at + timedelta(days=plan.duration_days)

            sub.source = "admin"
            sub.card_code = None
            if sub.end_at <= now:
                sub.status = "expired"

            await self._append_audit(
                session,
                actor=actor,
                action="admin.update_user_subscription",
                target_type="user",
                target_id=str(user_id),
                detail={
                    "plan_code": sub.plan_code,
                    "end_at": sub.end_at.isoformat() if sub.end_at else None,
                    "extend_days": extend_days,
                },
                ip_address=ip_address,
            )
            await session.commit()
            await session.refresh(sub)
            return {
                "user_id": user_id,
                "subscription": {
                    "id": sub.id,
                    "plan_code": sub.plan_code,
                    "start_at": sub.start_at.isoformat() if sub.start_at else None,
                    "end_at": sub.end_at.isoformat() if sub.end_at else None,
                    "status": sub.status,
                },
            }

    async def update_plan(
        self,
        plan_code: str,
        display_name: Optional[str] = None,
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

            if display_name is not None:
                plan.display_name = display_name.strip() or plan.display_name
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
                detail={
                    "display_name": display_name,
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

    async def generate_cards(
        self,
        plan_code: str,
        quantity: int,
        duration_days: Optional[int] = None,
        expires_at: Optional[datetime] = None,
        prefix: str = "",
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if quantity <= 0 or quantity > 500:
            raise HTTPException(status_code=400, detail="quantity 取值范围为 1~500")

        if expires_at and expires_at <= datetime.now():
            raise HTTPException(status_code=400, detail="expires_at 必须是未来时间")

        async with get_async_session() as session:
            plan_result = await session.execute(
                select(PricingPlan).where(PricingPlan.plan_code == plan_code).limit(1)
            )
            plan = plan_result.scalar_one_or_none()
            if not plan:
                raise HTTPException(status_code=404, detail="套餐不存在")
            generated_codes: set[str] = set()
            max_attempts = quantity * 20
            attempts = 0
            while len(generated_codes) < quantity and attempts < max_attempts:
                attempts += 1
                generated_codes.add(self._generate_card_code(prefix=prefix))

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
                    generated_codes.add(self._generate_card_code(prefix=prefix))

            created_cards: List[ActivationCard] = [
                ActivationCard(
                    card_code=code,
                    plan_code=plan_code,
                    duration_days=duration_days,
                    is_active=True,
                    is_used=False,
                    expires_at=expires_at,
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
                    "duration_days": duration_days,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                    "prefix": prefix,
                    "sample_card": created_cards[0].card_code if created_cards else None,
                },
                ip_address=ip_address,
            )
            await session.commit()
            for card in created_cards:
                await session.refresh(card)

        return [self._serialize_card(card) for card in created_cards]

    async def list_cards(
        self,
        plan_code: Optional[str] = None,
        is_used: Optional[bool] = None,
        is_active: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))

        stmt: Select[Any] = select(ActivationCard)
        conditions = []
        if plan_code:
            conditions.append(ActivationCard.plan_code == plan_code)
        if is_used is not None:
            conditions.append(ActivationCard.is_used.is_(is_used))
        if is_active is not None:
            conditions.append(ActivationCard.is_active.is_(is_active))
        if conditions:
            stmt = stmt.where(and_(*conditions))

        stmt = stmt.order_by(ActivationCard.id.desc()).limit(limit).offset(offset)

        async with get_async_session() as session:
            result = await session.execute(stmt)
            cards = result.scalars().all()

        return [self._serialize_card(card) for card in cards]

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
        duration_days: Optional[int] = None,
        valid_days: Optional[int] = None,
        prefix: str = "",
        *,
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
            duration_days=duration_days,
            expires_at=expires_at,
            prefix=prefix,
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
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))

        stmt: Select[Any] = select(AdminAuditLog)
        conditions = []
        if action:
            conditions.append(AdminAuditLog.action == action)
        if target_type:
            conditions.append(AdminAuditLog.target_type == target_type)
        if target_id:
            conditions.append(AdminAuditLog.target_id == target_id)
        if developer_app_id is not None:
            conditions.append(AdminAuditLog.developer_app_id == int(developer_app_id))
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.order_by(AdminAuditLog.id.desc()).limit(limit).offset(offset)

        async with get_async_session() as session:
            rows = (await session.execute(stmt)).scalars().all()

        return [
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


_admin_billing_service: Optional[AdminBillingService] = None


def get_admin_billing_service() -> AdminBillingService:
    """Get singleton admin billing service."""
    global _admin_billing_service
    if _admin_billing_service is None:
        _admin_billing_service = AdminBillingService()
    return _admin_billing_service
