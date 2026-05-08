"""Admin service for managing developer apps."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy import func, select

from backend.bot.developer_apps import get_developer_app_service
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account, ScheduledMessageTask, User
from backend.h5_backend.services.shared.audit import append_audit_log, mask_actor_name
from backend.h5_backend.services.shared.pagination import paginate_items


class DeveloperAppsService:
    """Encapsulates admin CRUD and management of developer apps."""

    @staticmethod
    def _account_display_name(account: Account) -> str:
        if account.username:
            return f"@{account.username}"
        if account.first_name:
            return account.first_name
        if account.phone:
            return account.phone
        return str(account.account_id)

    async def _enrich_apps_with_accounts(self, apps: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        app_ids = [int(item["id"]) for item in apps if item.get("id") is not None]
        if not app_ids:
            return apps

        account_items_by_app: Dict[int, list[Dict[str, Any]]] = {app_id: [] for app_id in app_ids}
        task_counts_by_account: Dict[str, Dict[str, int]] = {}
        async with get_async_session() as session:
            accounts = (
                await session.execute(
                    select(Account, User.username.label("owner_username"))
                    .join(User, User.id == Account.user_id)
                    .where(Account.developer_app_id.in_(app_ids))
                    .order_by(Account.developer_app_id.asc(), Account.created_at.desc())
                )
            ).all()
            account_ids = [str(account.account_id) for account, _owner_username in accounts]
            if account_ids:
                task_rows = (
                    await session.execute(
                        select(
                            ScheduledMessageTask.account_id,
                            func.count(ScheduledMessageTask.task_id).label("task_count"),
                            func.count(ScheduledMessageTask.task_id)
                            .filter(ScheduledMessageTask.enabled.is_(True))
                            .label("enabled_task_count"),
                        )
                        .where(ScheduledMessageTask.account_id.in_(account_ids))
                        .group_by(ScheduledMessageTask.account_id)
                    )
                ).all()
                task_counts_by_account = {
                    str(row.account_id): {
                        "task_count": int(row.task_count or 0),
                        "enabled_task_count": int(row.enabled_task_count or 0),
                    }
                    for row in task_rows
                }

            for account, owner_username in accounts:
                app_id = int(account.developer_app_id or 0)
                if app_id not in account_items_by_app:
                    continue
                task_counts = task_counts_by_account.get(
                    str(account.account_id),
                    {"task_count": 0, "enabled_task_count": 0},
                )
                account_items_by_app[app_id].append(
                    {
                        "account_id": account.account_id,
                        "tg_user_id": account.tg_user_id,
                        "username": account.username,
                        "tg_account_name": self._account_display_name(account),
                        "first_name": account.first_name,
                        "phone": account.phone,
                        "owner_user_id": account.user_id,
                        "owner_username": owner_username,
                        "is_active": account.is_active,
                        "health_status": account.health_status,
                        "messages_sent": account.messages_sent,
                        "task_count": task_counts["task_count"],
                        "enabled_task_count": task_counts["enabled_task_count"],
                        "created_at": account.created_at.isoformat() if account.created_at else None,
                    }
                )

        enriched = []
        for app in apps:
            app_id = int(app.get("id") or 0)
            account_items = account_items_by_app.get(app_id, [])
            enriched.append(
                {
                    **app,
                    "account_count": len(account_items),
                    "active_account_count": sum(1 for item in account_items if item["is_active"]),
                    "account_items": account_items,
                }
            )
        return enriched

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
        apps = await self._enrich_apps_with_accounts(apps)
        page = paginate_items(apps, limit=limit, offset=offset)
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
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
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
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
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
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
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
            actor=mask_actor_name(actor),
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
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
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
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
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


_developer_app_svc: DeveloperAppsService | None = None


def get_developer_app_admin_service() -> DeveloperAppsService:
    global _developer_app_svc
    if _developer_app_svc is None:
        _developer_app_svc = DeveloperAppsService()
    return _developer_app_svc
