"""Proxy domain service for H5 API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import or_, select

from backend.bot.proxy_pool import get_proxy_pool
from backend.database.models import Account, Proxy
from backend.database.session import get_async_session
from backend.h5_backend.dependencies import check_account_permission, check_proxy_permission


class ProxyService:
    """Proxy management service."""

    async def list_proxies(self, user_id: int) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            owned_accounts_result = await session.execute(select(Account.account_id).where(Account.user_id == user_id))
            owned_account_ids = [row[0] for row in owned_accounts_result.all()]

            query = select(Proxy)
            if owned_account_ids:
                query = query.where(
                    or_(
                        Proxy.assigned_account_id.is_(None),
                        Proxy.assigned_account_id.in_(owned_account_ids),
                    )
                )
            else:
                query = query.where(Proxy.assigned_account_id.is_(None))

            result = await session.execute(query.order_by(Proxy.created_at.desc()))
            proxies = result.scalars().all()

        return [self._serialize_proxy(proxy) for proxy in proxies]

    async def add_proxy(self, proxy_data: dict) -> Dict[str, Any]:
        proxy_pool = get_proxy_pool()
        proxy = await proxy_pool.add_proxy(
            proxy_type=proxy_data.get("proxy_type", "socks5"),
            host=proxy_data["host"],
            port=proxy_data["port"],
            username=proxy_data.get("username"),
            password=proxy_data.get("password"),
        )
        return {
            "proxy_id": proxy.proxy_id,
            "proxy_type": proxy.proxy_type,
            "host": proxy.host,
            "port": proxy.port,
        }

    async def check_health(self, proxy_id: int, user_id: int) -> Dict[str, Any]:
        await check_proxy_permission(proxy_id, user_id)
        proxy_pool = get_proxy_pool()
        status = await proxy_pool.check_health(proxy_id)
        return {
            "is_healthy": status.is_healthy,
            "response_time_ms": status.response_time_ms,
            "error": status.error or None,
        }

    async def delete_proxy(self, proxy_id: int, user_id: int) -> None:
        await check_proxy_permission(proxy_id, user_id)
        proxy_pool = get_proxy_pool()
        deleted = await proxy_pool.delete_proxy(proxy_id)
        if not deleted:
            raise HTTPException(status_code=400, detail="代理删除失败（可能已分配到账号）")

    async def assign_proxy(self, proxy_id: int, account_id: str, user_id: int) -> None:
        await check_account_permission(account_id, user_id)
        proxy_pool = get_proxy_pool()

        proxy = await proxy_pool.get_proxy(proxy_id)
        if not proxy:
            raise HTTPException(status_code=404, detail="代理不存在")
        if proxy.assigned_account_id and proxy.assigned_account_id != account_id:
            await check_account_permission(proxy.assigned_account_id, user_id)

        assigned = await proxy_pool.assign_proxy(account_id, proxy_id)
        if not assigned:
            raise HTTPException(status_code=400, detail="代理分配失败（可能已被占用或账号不存在）")

    async def unassign_proxy(self, proxy_id: int, user_id: int) -> None:
        proxy = await check_proxy_permission(proxy_id, user_id)
        if not proxy.assigned_account_id:
            raise HTTPException(status_code=400, detail="代理未分配账号")

        proxy_pool = get_proxy_pool()
        unassigned = await proxy_pool.unassign_proxy(proxy.assigned_account_id)
        if not unassigned:
            raise HTTPException(status_code=400, detail="代理解绑失败")

    def _serialize_proxy(self, proxy: Proxy) -> Dict[str, Any]:
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


_proxy_service: Optional[ProxyService] = None


def get_proxy_service() -> ProxyService:
    """Get singleton proxy service instance."""
    global _proxy_service
    if _proxy_service is None:
        _proxy_service = ProxyService()
    return _proxy_service
