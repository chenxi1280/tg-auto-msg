"""
代理池管理模块

管理 SOCKS5/HTTP 代理，包括：
- 代理添加和删除
- 代理健康检查
- 代理分配给账号
- 代理统计
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from loguru import logger
import asyncio

import socket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.session import get_async_session
from backend.database.models import Proxy, ProxyType
from backend.utils.crypto import encrypt_proxy_password, decrypt_proxy_password


@dataclass
class HealthStatus:
    """代理健康状态"""
    is_healthy: bool
    response_time_ms: int
    error: str = ""


class ProxyPool:
    """
    代理池管理器

    功能：
    - 添加和删除代理
    - 代理健康检查
    - 代理分配
    - 代理统计
    """

    def __init__(self):
        self._health_cache: Dict[int, HealthStatus] = {}
        self._cache_ttl = 300  # 5 分钟缓存

    # ==================== 代理 CRUD ====================

    async def add_proxy(
        self,
        proxy_type: str,
        host: str,
        port: int,
        username: Optional[str] = None,
        password: Optional[str] = None
    ) -> Proxy:
        """
        添加新代理（密码加密存储）

        Args:
            proxy_type: 代理类型 (socks5/http)
            host: 代理主机
            port: 代理端口
            username: 认证用户名
            password: 认证密码

        Returns:
            Proxy 对象
        """
        async with get_async_session() as session:
            # 检查是否已存在
            existing = await session.execute(
                select(Proxy).where(
                    Proxy.proxy_type == proxy_type,
                    Proxy.host == host,
                    Proxy.port == port
                )
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"代理已存在: {host}:{port}")

            # 加密密码
            password_encrypted = None
            if password:
                password_encrypted = encrypt_proxy_password(password)

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

    async def get_proxy(self, proxy_id: int) -> Optional[Proxy]:
        """
        获取代理信息

        Args:
            proxy_id: 代理 ID

        Returns:
            Proxy 对象
        """
        async with get_async_session() as session:
            result = await session.execute(
                select(Proxy).where(Proxy.proxy_id == proxy_id)
            )
            return result.scalar_one_or_none()

    async def get_proxies(
        self,
        is_active: bool = True,
        is_healthy: Optional[bool] = True
    ) -> List[Proxy]:
        """
        获取代理列表

        Args:
            is_active: 是否只获取启用的代理
            is_healthy: 是否只获取健康的代理

        Returns:
            Proxy 列表
        """
        async with get_async_session() as session:
            query = select(Proxy)

            if is_active:
                query = query.where(Proxy.is_active == True)
            if is_healthy is not None:
                query = query.where(Proxy.is_healthy == is_healthy)

            query = query.order_by(Proxy.created_at.desc())

            result = await session.execute(query)
            return result.scalars().all()

    async def delete_proxy(self, proxy_id: int) -> bool:
        """
        删除代理

        Args:
            proxy_id: 代理 ID

        Returns:
            是否删除成功
        """
        async with get_async_session() as session:
            result = await session.execute(
                select(Proxy).where(Proxy.proxy_id == proxy_id)
            )
            proxy = result.scalar_one_or_none()

            if not proxy:
                return False

            # 检查是否被分配
            if proxy.assigned_account_id:
                logger.warning(f"代理 {proxy_id} 已分配给账号，无法删除")
                return False

            await session.delete(proxy)
            await session.commit()

            # 清除缓存
            if proxy_id in self._health_cache:
                del self._health_cache[proxy_id]

            logger.info(f"删除代理: {proxy_id}")
            return True

    async def update_proxy(
        self,
        proxy_id: int,
        **kwargs
    ) -> Optional[Proxy]:
        """
        更新代理信息

        Args:
            proxy_id: 代理 ID
            **kwargs: 要更新的字段

        Returns:
            更新后的 Proxy 对象
        """
        async with get_async_session() as session:
            result = await session.execute(
                select(Proxy).where(Proxy.proxy_id == proxy_id)
            )
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

    # ==================== 代理分配 ====================

    async def get_available_proxy(self) -> Optional[Proxy]:
        """
        获取可用代理（优先未分配的）

        Returns:
            Proxy 对象
        """
        # 先获取未分配的代理
        async with get_async_session() as session:
            result = await session.execute(
                select(Proxy).where(
                    Proxy.is_active == True,
                    Proxy.is_healthy == True,
                    Proxy.assigned_account_id.is_(None)
                ).order_by(Proxy.usage_count.asc())
            )
            proxy = result.scalar_one_or_none()

            if proxy:
                return proxy

            # 如果没有未分配的，获取使用次数最少的
            result = await session.execute(
                select(Proxy).where(
                    Proxy.is_active == True,
                    Proxy.is_healthy == True
                ).order_by(Proxy.usage_count.asc())
            )
            return result.scalar_one_or_none()

    async def assign_proxy(
        self,
        account_id: str,
        proxy_id: int
    ) -> bool:
        """
        将代理分配给账号

        Args:
            account_id: 账号 ID
            proxy_id: 代理 ID

        Returns:
            是否分配成功
        """
        async with get_async_session() as session:
            from backend.database.models import Account

            # 检查代理是否存在
            result = await session.execute(
                select(Proxy).where(Proxy.proxy_id == proxy_id)
            )
            proxy = result.scalar_one_or_none()

            if not proxy:
                logger.error(f"代理不存在: {proxy_id}")
                return False

            # 检查是否已被其他账号分配
            if proxy.assigned_account_id and proxy.assigned_account_id != account_id:
                logger.warning(f"代理 {proxy_id} 已被分配给其他账号")
                return False

            # 检查账号是否存在
            account_result = await session.execute(
                select(Account).where(Account.account_id == account_id)
            )
            account = account_result.scalar_one_or_none()
            if not account:
                logger.error(f"账号不存在: {account_id}")
                return False

            # 如账号已有其他代理，先解绑旧代理占用关系
            if account.proxy_id and account.proxy_id != proxy_id:
                old_proxy_result = await session.execute(
                    select(Proxy).where(Proxy.proxy_id == account.proxy_id)
                )
                old_proxy = old_proxy_result.scalar_one_or_none()
                if old_proxy and old_proxy.assigned_account_id == account_id:
                    old_proxy.assigned_account_id = None

            # 分配代理
            proxy.assigned_account_id = account_id
            proxy.usage_count += 1
            account.proxy_id = proxy_id

            await session.commit()

            logger.info(f"分配代理: {proxy_id} -> {account_id}")
            return True

    async def unassign_proxy(self, account_id: str) -> bool:
        """
        解除账号的代理分配

        Args:
            account_id: 账号 ID

        Returns:
            是否解除成功
        """
        async with get_async_session() as session:
            from backend.database.models import Account
            result = await session.execute(
                select(Account).where(Account.account_id == account_id)
            )
            account = result.scalar_one_or_none()

            if not account or not account.proxy_id:
                return False

            # 解除分配
            result = await session.execute(
                select(Proxy).where(Proxy.proxy_id == account.proxy_id)
            )
            proxy = result.scalar_one_or_none()

            if proxy:
                old_proxy_id = proxy.proxy_id
                proxy.assigned_account_id = None
                account.proxy_id = None
                await session.commit()

                logger.info(f"解除代理分配: {old_proxy_id} <- {account_id}")
                return True

            return False

    # ==================== 健康检查 ====================

    async def check_health(self, proxy_id: int, timeout: int = 10) -> HealthStatus:
        """
        检查代理健康状态（连接测试）

        Args:
            proxy_id: 代理 ID
            timeout: 超时时间（秒）

        Returns:
            HealthStatus 对象
        """
        # 检查缓存
        if proxy_id in self._health_cache:
            cached = self._health_cache[proxy_id]
            # 简单的缓存机制（5分钟）
            if cached.is_healthy:
                return cached

        # 获取代理信息
        proxy = await self.get_proxy(proxy_id)
        if not proxy:
            return HealthStatus(False, 0, "代理不存在")

        # 测试连接
        start_time = datetime.now()
        is_healthy = False
        error = ""

        try:
            # 解密密码
            password = None
            if proxy.password_encrypted:
                try:
                    password = decrypt_proxy_password(proxy.password_encrypted)
                except Exception:
                    pass

            # 创建 socket 测试连接
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)

            # 连接到代理
            sock.connect((proxy.host, proxy.port))

            # 如果有认证，发送认证信息（简化版）
            # 实际应用中需要完整的 SOCKS5/HTTP 握手

            sock.close()
            is_healthy = True

        except socket.timeout:
            error = "连接超时"
        except ConnectionRefusedError:
            error = "连接被拒绝"
        except Exception as e:
            error = str(e)

        # 计算响应时间
        response_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # 更新数据库
        await self.update_proxy(
            proxy_id,
            is_healthy=is_healthy,
            last_check_at=datetime.now(),
            response_time_ms=response_time_ms if is_healthy else None
        )

        # 更新缓存
        status = HealthStatus(is_healthy, response_time_ms if is_healthy else 0, error)
        self._health_cache[proxy_id] = status

        return status

    async def check_all_proxies(self) -> Dict[int, HealthStatus]:
        """
        检查所有代理的健康状态

        Returns:
            {proxy_id: HealthStatus} 字典
        """
        proxies = await self.get_proxies(is_active=True, is_healthy=None)
        results = {}

        # 并发检查
        tasks = [self.check_health(p.proxy_id) for p in proxies]
        health_statuses = await asyncio.gather(*tasks)

        for proxy, status in zip(proxies, health_statuses):
            results[proxy.proxy_id] = status

        return results

    async def get_healthy_proxies(self) -> List[Proxy]:
        """
        获取所有健康的代理

        Returns:
            Proxy 列表
        """
        return await self.get_proxies(is_active=True, is_healthy=True)

    async def get_proxy_config(
        self,
        proxy_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        获取代理配置（用于 Telethon）

        Args:
            proxy_id: 代理 ID

        Returns:
            代理配置字典
        """
        proxy = await self.get_proxy(proxy_id)
        if not proxy:
            return None

        # 解密密码
        password = None
        if proxy.password_encrypted:
            try:
                password = decrypt_proxy_password(proxy.password_encrypted)
            except Exception:
                pass

        # 构造配置
        if proxy.proxy_type == ProxyType.SOCKS5:
            return {
                "proxy_type": "socks5",
                "addr": proxy.host,
                "port": proxy.port,
                "username": proxy.username,
                "password": password,
                "rdns": True,
            }
        elif proxy.proxy_type == ProxyType.HTTP:
            return {
                "proxy_type": "http",
                "addr": proxy.host,
                "port": proxy.port,
                "username": proxy.username,
                "password": password,
            }

        return None

    # ==================== 缓存管理 ====================

    def clear_health_cache(self):
        """清除健康状态缓存"""
        self._health_cache.clear()


# 全局单例
_proxy_pool: Optional[ProxyPool] = None


def get_proxy_pool() -> ProxyPool:
    """获取全局代理池实例"""
    global _proxy_pool
    if _proxy_pool is None:
        _proxy_pool = ProxyPool()
    return _proxy_pool
