"""Proxy management service extracted from AdminLicenseService."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy import select

from backend.bot.proxy.pool import get_proxy_pool
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account, Proxy, User
from backend.h5_backend.services.shared.audit import append_audit_log, mask_actor_name
from backend.h5_backend.services.shared.pagination import paginate_items


class ProxiesService:
    """Standalone proxy CRUD / health / assignment service."""

    # ------------------------------------------------------------------
    # Serializers
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_proxy(proxy: Proxy, assigned_account_name: Optional[str] = None) -> Dict[str, Any]:
        return {
            "proxy_id": proxy.proxy_id,
            "proxy_type": proxy.proxy_type,
            "host": proxy.host,
            "port": proxy.port,
            "display_name": getattr(proxy, "display_name", None),
            "region_code": getattr(proxy, "region_code", None),
            "is_system_gateway": bool(getattr(proxy, "is_system_gateway", False)),
            "is_shared": bool(getattr(proxy, "is_shared", False)),
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

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

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
        return paginate_items(items, limit=limit, offset=offset)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

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
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
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
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
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
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
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
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
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
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
                action="admin.unassign_proxy",
                target_type="proxy",
                target_id=str(proxy_id),
                detail={"account_id": proxy.assigned_account_id},
                ip_address=ip_address,
            )
            await session.commit()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_proxy_service: ProxiesService | None = None


def get_proxy_service() -> ProxiesService:
    global _proxy_service
    if _proxy_service is None:
        _proxy_service = ProxiesService()
    return _proxy_service
