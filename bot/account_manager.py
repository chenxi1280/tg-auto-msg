"""
账号管理模块

管理多个 Userbot 账号，支持：
- 账号 CRUD 操作
- 绑定码生成和验证
- TelegramClient 缓存和管理
- 基于权重的账号选择
- 健康检查
"""
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from enum import Enum
from loguru import logger

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, RPCError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_async_session
from database.models import Account, HealthStatus
from bot.redis_login_manager import get_redis_login_manager, LoginStatus
from utils.crypto import (
    encrypt_string_session,
    decrypt_string_session,
    generate_bind_code,
)
from config.settings import settings


class AccountSelectionStrategy(str, Enum):
    """账号选择策略"""
    WEIGHT = "weight"        # 权重优先
    LEAST_USED = "least_used"  # 最少使用
    ROUND_ROBIN = "round_robin"  # 轮询


class AccountManager:
    """
    多 Userbot 账号管理器

    功能：
    - 创建和绑定账号
    - 获取和管理 TelegramClient
    - 基于策略选择账号
    - 健康检查
    """

    def __init__(self):
        # TelegramClient 缓存: account_id -> TelegramClient
        self._clients: Dict[str, TelegramClient] = {}
        # 客户端锁：防止并发创建
        self._locks: Dict[str, asyncio.Lock] = {}
        # 轮询计数器
        self._round_robin_counter: Dict[str, int] = {}

    async def get_client_lock(self, account_id: str) -> asyncio.Lock:
        """获取账号的锁"""
        if account_id not in self._locks:
            self._locks[account_id] = asyncio.Lock()
        return self._locks[account_id]

    # ==================== 账号 CRUD ====================

    async def create_account(
        self,
        user_id: int,
        tg_user_id: int,
        string_session: str,
        username: str = "",
        first_name: str = "",
        phone: str = "",
        proxy_id: Optional[int] = None,
        weight: int = 100
    ) -> Account:
        """
        创建新账号

        Args:
            user_id: 归属用户 UID
            tg_user_id: Telegram UID
            string_session: StringSession（明文，将被加密存储）
            username: Telegram 用户名
            first_name: 名字
            phone: 手机号
            proxy_id: 代理 ID
            weight: 权重

        Returns:
            Account 对象
        """
        async with get_async_session() as session:
            # 加密 StringSession
            string_session_encrypted = encrypt_string_session(string_session)

            account = Account(
                user_id=user_id,
                tg_user_id=tg_user_id,
                username=username or f"user_{tg_user_id}",
                first_name=first_name,
                phone=phone,
                string_session_encrypted=string_session_encrypted,
                proxy_id=proxy_id,
                weight=weight,
                health_status=HealthStatus.ONLINE,
            )

            session.add(account)
            await session.commit()
            await session.refresh(account)

            logger.info(f"创建账号: {account.account_id} (@{username})")
            return account

    async def bind_account(
        self,
        user_id: int,
        bind_code: str,
        ip_address: str = ""
    ) -> Optional[Account]:
        """
        通过绑定码绑定账号到用户

        Args:
            user_id: Telegram 用户 ID
            bind_code: 6 位绑定码
            ip_address: IP 地址（用于日志）

        Returns:
            Account 对象，如果绑定码无效返回 None
        """
        login_manager = get_redis_login_manager()

        # 获取绑定码信息
        bind_data = await login_manager.get_account_by_bind_code(bind_code)
        if not bind_data:
            logger.warning(f"无效的绑定码: {bind_code}")
            return None

        async with get_async_session() as session:
            # 检查是否已有账号（避免重复绑定）
            existing = await session.execute(
                select(Account).where(
                    Account.user_id == user_id,
                    Account.tg_user_id == int(bind_data["tg_user_id"])
                )
            )
            if existing.scalar_one_or_none():
                logger.warning(f"用户 {user_id} 已绑定该账号")
                return None

            # 创建账号
            account = Account(
                user_id=user_id,
                tg_user_id=int(bind_data["tg_user_id"]),
                username=bind_data.get("username", ""),
                phone=bind_data.get("phone", ""),
                string_session_encrypted=bind_data["string_session_encrypted"],
                health_status=HealthStatus.ONLINE,
            )

            session.add(account)
            await session.commit()
            await session.refresh(account)

            # 记录绑定日志
            from database.models import AccountBindLog
            log = AccountBindLog(
                account_id=account.account_id,
                user_id=user_id,
                bind_code=bind_code,
                ip_address=ip_address
            )
            session.add(log)
            await session.commit()

            # 消费绑定码
            await login_manager.consume_bind_code(bind_code)

            # 设置用户登录状态
            await login_manager.set_user_logged_in(user_id)

            logger.info(f"绑定账号成功: {account.account_id} -> user {user_id}")

            # 触发资源同步（后台任务）
            asyncio.create_task(self._sync_resources_after_bind(account.account_id))

            return account

    async def _sync_resources_after_bind(self, account_id: str):
        """绑定后自动同步资源"""
        try:
            from bot.resource_manager import get_resource_manager
            resource_manager = get_resource_manager()
            await resource_manager.full_sync(account_id)
        except Exception as e:
            logger.error(f"绑定后资源同步失败: {e}")

    async def get_accounts(
        self,
        user_id: int,
        is_active: bool = True
    ) -> List[Account]:
        """
        获取用户的所有账号

        Args:
            user_id: 用户 ID
            is_active: 是否只获取启用的账号

        Returns:
            Account 列表
        """
        async with get_async_session() as session:
            query = select(Account).where(Account.user_id == user_id)
            if is_active:
                query = query.where(Account.is_active == True)

            result = await session.execute(
                query.order_by(Account.created_at.desc())
            )
            return result.scalars().all()

    async def get_account(self, account_id: str) -> Optional[Account]:
        """
        获取账号信息

        Args:
            account_id: 账号 ID

        Returns:
            Account 对象
        """
        async with get_async_session() as session:
            result = await session.execute(
                select(Account).where(Account.account_id == account_id)
            )
            return result.scalar_one_or_none()

    async def update_account(
        self,
        account_id: str,
        **kwargs
    ) -> Optional[Account]:
        """
        更新账号信息

        Args:
            account_id: 账号 ID
            **kwargs: 要更新的字段

        Returns:
            更新后的 Account 对象
        """
        async with get_async_session() as session:
            result = await session.execute(
                select(Account).where(Account.account_id == account_id)
            )
            account = result.scalar_one_or_none()

            if not account:
                return None

            for key, value in kwargs.items():
                if hasattr(account, key) and value is not None:
                    setattr(account, key, value)

            await session.commit()
            await session.refresh(account)

            logger.info(f"更新账号: {account_id}")
            return account

    async def delete_account(self, account_id: str) -> bool:
        """
        删除账号

        Args:
            account_id: 账号 ID

        Returns:
            是否删除成功
        """
        async with get_async_session() as session:
            result = await session.execute(
                select(Account).where(Account.account_id == account_id)
            )
            account = result.scalar_one_or_none()

            if not account:
                return False

            # 关闭并清理客户端
            await self._close_client(account_id)

            await session.delete(account)
            await session.commit()

            logger.info(f"删除账号: {account_id}")
            return True

    # ==================== TelegramClient 管理 ====================

    async def get_client(self, account_id: str) -> Optional[TelegramClient]:
        """
        获取账号的 TelegramClient（带缓存）

        Args:
            account_id: 账号 ID

        Returns:
            TelegramClient 对象
        """
        # 检查缓存
        if account_id in self._clients:
            client = self._clients[account_id]
            if client.is_connected():
                return client
            else:
                # 移除断开的客户端
                del self._clients[account_id]

        # 获取账号信息
        account = await self.get_account(account_id)
        if not account:
            logger.error(f"账号不存在: {account_id}")
            return None

        # 解密 StringSession
        try:
            string_session = decrypt_string_session(account.string_session_encrypted)
        except Exception as e:
            logger.error(f"解密 StringSession 失败: {e}")
            return None

        # 获取代理配置
        proxy = None
        if account.proxy_id:
            proxy = await self._get_proxy_config(account.proxy_id)

        # 创建客户端
        async with await self.get_client_lock(account_id):
            # 双重检查
            if account_id in self._clients:
                return self._clients[account_id]

            session_path = f"sessions/account_{account_id}"
            client = TelegramClient(
                session_path,
                api_id=settings.api_id,
                api_hash=settings.api_hash,
                proxy=proxy,
            )

            # 连接
            await client.connect()

            # 验证授权
            if not await client.is_user_authorized():
                logger.error(f"账号 {account_id} 未授权，可能已登出")
                await client.disconnect()
                await self.update_health_status(account_id, HealthStatus.OFFLINE)
                return None

            # 缓存客户端
            self._clients[account_id] = client

            logger.info(f"创建 TelegramClient: {account_id}")
            return client

    async def _close_client(self, account_id: str):
        """关闭并清理客户端"""
        if account_id in self._clients:
            try:
                await self._clients[account_id].disconnect()
            except Exception as e:
                logger.error(f"关闭客户端失败: {e}")
            del self._clients[account_id]

        if account_id in self._locks:
            del self._locks[account_id]

    async def _get_proxy_config(self, proxy_id: int) -> Optional[Dict[str, Any]]:
        """获取代理配置"""
        from bot.proxy_pool import get_proxy_pool
        proxy_pool = get_proxy_pool()
        proxy = await proxy_pool.get_proxy(proxy_id)
        if not proxy:
            return None

        # 解密密码
        from utils.crypto import decrypt_proxy_password
        password = None
        if proxy.password_encrypted:
            try:
                password = decrypt_proxy_password(proxy.password_encrypted)
            except Exception:
                pass

        # 构造 Telethon 代理配置
        if proxy.proxy_type == "socks5":
            return {
                "proxy_type": "socks5",
                "addr": proxy.host,
                "port": proxy.port,
                "username": proxy.username,
                "password": password,
                "rdns": True,
            }
        elif proxy.proxy_type == "http":
            return {
                "proxy_type": "http",
                "addr": proxy.host,
                "port": proxy.port,
                "username": proxy.username,
                "password": password,
            }

        return None

    # ==================== 账号选择 ====================

    async def select_account(
        self,
        user_id: int,
        peer_id: Optional[int] = None,
        strategy: AccountSelectionStrategy = AccountSelectionStrategy.WEIGHT
    ) -> Optional[Account]:
        """
        选择可用账号

        Args:
            user_id: 用户 ID
            peer_id: 目标 Peer ID（可选，用于避免重复）
            strategy: 选择策略

        Returns:
            选中的 Account 对象
        """
        accounts = await self.get_accounts(user_id, is_active=True)

        if not accounts:
            return None

        # 过滤健康的账号
        healthy_accounts = [
            acc for acc in accounts
            if acc.health_status == HealthStatus.ONLINE
            and not acc.is_flooding
            and not acc.is_banned
        ]

        if not healthy_accounts:
            logger.warning(f"用户 {user_id} 没有可用的健康账号")
            return None

        if peer_id:
            # 避免选择最近发送过该 Peer 的账号（简单去重）
            # TODO: 可以添加更复杂的逻辑
            pass

        # 根据策略选择
        if strategy == AccountSelectionStrategy.WEIGHT:
            # 按权重随机选择
            import random
            weights = [acc.weight for acc in healthy_accounts]
            total_weight = sum(weights)
            if total_weight == 0:
                return healthy_accounts[0]

            rand = random.randint(0, total_weight - 1)
            current = 0
            for i, acc in enumerate(healthy_accounts):
                current += acc.weight
                if rand < current:
                    return acc

        elif strategy == AccountSelectionStrategy.LEAST_USED:
            # 选择使用次数最少的
            return min(healthy_accounts, key=lambda acc: acc.messages_sent)

        elif strategy == AccountSelectionStrategy.ROUND_ROBIN:
            # 轮询
            if user_id not in self._round_robin_counter:
                self._round_robin_counter[user_id] = 0

            index = self._round_robin_counter[user_id] % len(healthy_accounts)
            self._round_robin_counter[user_id] += 1
            return healthy_accounts[index]

        return healthy_accounts[0]

    # ==================== 健康检查 ====================

    async def health_check(self, account_id: str) -> HealthStatus:
        """
        检查账号健康状态（执行 get_me）

        Args:
            account_id: 账号 ID

        Returns:
            健康状态
        """
        client = await self.get_client(account_id)
        if not client:
            return HealthStatus.OFFLINE

        try:
            me = await client.get_me()
            if me:
                await self.update_health_status(account_id, HealthStatus.ONLINE)
                return HealthStatus.ONLINE
        except Exception as e:
            logger.error(f"健康检查失败 {account_id}: {e}")
            await self.update_health_status(account_id, HealthStatus.OFFLINE)
            return HealthStatus.OFFLINE

    async def update_health_status(
        self,
        account_id: str,
        status: HealthStatus
    ):
        """
        更新健康状态到数据库和 Redis 缓存

        Args:
            account_id: 账号 ID
            status: 健康状态
        """
        # 更新数据库
        await self.update_account(account_id, health_status=status.value)

        # 更新 Redis 缓存
        r = await get_redis_login_manager()._get_redis()
        key = f"health:account:{account_id}"
        await r.hset(key, mapping={
            "status": status.value,
            "last_check": datetime.now().isoformat()
        })
        await r.expire(key, 300)  # 5 分钟缓存

    async def get_health_status(self, account_id: str) -> Optional[Dict[str, Any]]:
        """
        从 Redis 缓存获取健康状态

        Args:
            account_id: 账号 ID

        Returns:
            健康状态字典
        """
        r = await get_redis_login_manager()._get_redis()
        key = f"health:account:{account_id}"
        data = await r.hgetall(key)

        if data:
            return {
                "status": data.get("status"),
                "last_check": data.get("last_check")
            }

        return None

    # ==================== 统计更新 ====================

    async def increment_messages_sent(self, account_id: str):
        """增加消息发送计数"""
        async with get_async_session() as session:
            result = await session.execute(
                select(Account).where(Account.account_id == account_id)
            )
            account = result.scalar_one_or_none()

            if account:
                account.messages_sent += 1
                account.last_used_at = datetime.now()
                await session.commit()

    async def close_all(self):
        """关闭所有客户端连接"""
        for account_id in list(self._clients.keys()):
            await self._close_client(account_id)


# 全局单例
_account_manager: Optional[AccountManager] = None


def get_account_manager() -> AccountManager:
    """获取全局账号管理器实例"""
    global _account_manager
    if _account_manager is None:
        _account_manager = AccountManager()
    return _account_manager
