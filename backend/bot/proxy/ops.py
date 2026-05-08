"""Proxy pool CRUD and assignment operations."""
from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy import select

from backend.database.schema.models import Proxy
from backend.database.runtime.session import get_async_session
from backend.utils.security.crypto import encrypt_proxy_password


async def add_proxy(
    *,
    proxy_type: str,
    host: str,
    port: int,
    username: Optional[str],
    password: Optional[str],
):
    """Create one proxy entry with encrypted password."""
    async with get_async_session() as session:
        existing = await session.execute(
            select(Proxy).where(
                Proxy.proxy_type == proxy_type,
                Proxy.host == host,
                Proxy.port == port,
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"代理已存在: {host}:{port}")

        password_encrypted = encrypt_proxy_password(password) if password else None
        proxy = Proxy(
            proxy_type=proxy_type,
            host=host,
            port=port,
            username=username,
            password_encrypted=password_encrypted,
            is_active=True,
            is_healthy=True,
        )
        session.add(proxy)
        await session.commit()
        await session.refresh(proxy)
        logger.info(f"添加代理: {proxy_type}://{host}:{port}")
        return proxy


async def get_proxy(proxy_id: int):
    """Fetch proxy by id."""
    async with get_async_session() as session:
        result = await session.execute(select(Proxy).where(Proxy.proxy_id == proxy_id))
        return result.scalar_one_or_none()


async def get_proxies(*, is_active: bool, is_healthy: Optional[bool]):
    """List proxies by status filters."""
    async with get_async_session() as session:
        query = select(Proxy)
        if is_active:
            query = query.where(Proxy.is_active == True)
        if is_healthy is not None:
            query = query.where(Proxy.is_healthy == is_healthy)
        query = query.order_by(Proxy.created_at.desc())
        result = await session.execute(query)
        return result.scalars().all()


async def delete_proxy(manager, proxy_id: int) -> bool:
    """Delete unassigned proxy."""
    async with get_async_session() as session:
        result = await session.execute(select(Proxy).where(Proxy.proxy_id == proxy_id))
        proxy = result.scalar_one_or_none()
        if not proxy:
            return False
        if proxy.assigned_account_id:
            logger.warning(f"代理 {proxy_id} 已分配给账号，无法删除")
            return False

        await session.delete(proxy)
        await session.commit()

    manager._health_cache.pop(proxy_id, None)
    logger.info(f"删除代理: {proxy_id}")
    return True


async def update_proxy(proxy_id: int, **kwargs):
    """Update proxy fields."""
    async with get_async_session() as session:
        result = await session.execute(select(Proxy).where(Proxy.proxy_id == proxy_id))
        proxy = result.scalar_one_or_none()
        if not proxy:
            return None

        for key, value in kwargs.items():
            if hasattr(proxy, key) and value is not None:
                setattr(proxy, key, value)

        await session.commit()
        await session.refresh(proxy)
        logger.info(f"更新代理: {proxy_id}")
        return proxy


async def get_available_proxy():
    """Get one available healthy proxy, prefer unassigned then least-used."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Proxy)
            .where(
                Proxy.is_active == True,
                Proxy.is_healthy == True,
                Proxy.assigned_account_id.is_(None),
            )
            .order_by(Proxy.usage_count.asc())
        )
        proxy = result.scalar_one_or_none()
        if proxy:
            return proxy

        result = await session.execute(
            select(Proxy)
            .where(
                Proxy.is_active == True,
                Proxy.is_healthy == True,
            )
            .order_by(Proxy.usage_count.asc())
        )
        return result.scalar_one_or_none()


async def assign_proxy(account_id: str, proxy_id: int) -> bool:
    """Assign one proxy to account."""
    async with get_async_session() as session:
        from backend.database.schema.models import Account

        result = await session.execute(select(Proxy).where(Proxy.proxy_id == proxy_id))
        proxy = result.scalar_one_or_none()
        if not proxy:
            logger.error(f"代理不存在: {proxy_id}")
            return False
        is_shared = bool(getattr(proxy, "is_shared", False))
        if not is_shared and proxy.assigned_account_id and proxy.assigned_account_id != account_id:
            logger.warning(f"代理 {proxy_id} 已被分配给其他账号")
            return False

        account_result = await session.execute(
            select(Account).where(Account.account_id == account_id)
        )
        account = account_result.scalar_one_or_none()
        if not account:
            logger.error(f"账号不存在: {account_id}")
            return False

        if account.proxy_id and account.proxy_id != proxy_id:
            old_proxy_result = await session.execute(
                select(Proxy).where(Proxy.proxy_id == account.proxy_id)
            )
            old_proxy = old_proxy_result.scalar_one_or_none()
            if old_proxy and old_proxy.assigned_account_id == account_id:
                old_proxy.assigned_account_id = None

        if is_shared:
            proxy.assigned_account_id = None
        else:
            proxy.assigned_account_id = account_id
        proxy.usage_count += 1
        account.proxy_id = proxy_id
        await session.commit()

    logger.info(f"分配代理: {proxy_id} -> {account_id}")
    return True


async def unassign_proxy(account_id: str) -> bool:
    """Unassign account's current proxy."""
    async with get_async_session() as session:
        from backend.database.schema.models import Account

        result = await session.execute(
            select(Account).where(Account.account_id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account or not account.proxy_id:
            return False

        result = await session.execute(
            select(Proxy).where(Proxy.proxy_id == account.proxy_id)
        )
        proxy = result.scalar_one_or_none()
        if not proxy:
            return False

        old_proxy_id = proxy.proxy_id
        if proxy.assigned_account_id == account_id:
            proxy.assigned_account_id = None
        account.proxy_id = None
        await session.commit()

    logger.info(f"解除代理分配: {old_proxy_id} <- {account_id}")
    return True
