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
from enum import Enum
from loguru import logger

from telethon import TelegramClient
from sqlalchemy import select, delete, update
from sqlalchemy.exc import IntegrityError

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    Account,
    HealthStatus,
    ScheduledMessageTask,
    TaskLog,
    Proxy,
    AccountBindLog,
    TelegramDeveloperApp,
)
from backend.utils.security.crypto import (
    encrypt_string_session,
)
from backend.bot.developer_apps import get_developer_app_service
from backend.bot.developer_apps.service import ASSIGNMENT_CONTEXT_NEW


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
        weight: int = 100,
        developer_app_id: Optional[int] = None,
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
            resolved_developer_app_id = developer_app_id
            if resolved_developer_app_id is None:
                try:
                    resolved_developer_app_id = await get_developer_app_service().resolve_assignable_app_id(
                        user_id=int(user_id),
                        preferred_app_id=None,
                        exclude_account_id=None,
                        assignment_context=ASSIGNMENT_CONTEXT_NEW,
                        existing_app_id=None,
                    )
                except Exception as e:
                    raise RuntimeError(f"开发者凭证分配失败: {e}") from e
            resolved_app_version = 1
            if resolved_developer_app_id is not None:
                app_row = await session.get(TelegramDeveloperApp, int(resolved_developer_app_id))
                if app_row is not None:
                    resolved_app_version = int(app_row.credentials_version or 1)

            account = Account(
                user_id=user_id,
                tg_user_id=tg_user_id,
                username=username or f"user_{tg_user_id}",
                first_name=first_name,
                phone=phone,
                string_session_encrypted=string_session_encrypted,
                developer_app_id=resolved_developer_app_id,
                developer_app_version=resolved_app_version,
                reauth_required=False,
                reauth_reason=None,
                reauth_required_at=None,
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
        ip_address: str = "",
        actor_tg_user_id: Optional[int] = None,
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
        from backend.bot.account.binding_service import bind_account as _bind_account

        return await _bind_account(
            self,
            user_id=user_id,
            bind_code=bind_code,
            ip_address=ip_address,
            actor_tg_user_id=actor_tg_user_id,
        )

    async def issue_bind_code(
        self,
        account_id: str,
        refresh: bool = True,
        ttl_seconds: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        为已绑定账号签发可用于 /bind 的短期绑定码。

        绑定码写入 Redis login:bind:*，以兼容现有 bind_account 流程。
        """
        from backend.bot.account.binding_service import issue_bind_code as _issue_bind_code

        return await _issue_bind_code(
            self,
            account_id=account_id,
            refresh=refresh,
            ttl_seconds=ttl_seconds,
        )

    async def _sync_resources_after_bind(self, account_id: str):
        """绑定后自动同步资源"""
        from backend.bot.account.binding_service import sync_resources_after_bind
        await sync_resources_after_bind(account_id)

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

            nullable_fields = {
                "username",
                "first_name",
                "phone",
                "developer_app_id",
                "bind_code",
                "bind_code_expires_at",
                "proxy_id",
                "flood_until",
                "last_used_at",
                "reauth_reason",
                "reauth_required_at",
            }
            for key, value in kwargs.items():
                if not hasattr(account, key):
                    continue
                if value is not None or key in nullable_fields:
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
            try:
                result = await session.execute(
                    select(Account).where(Account.account_id == account_id)
                )
                account = result.scalar_one_or_none()

                if not account:
                    return False

                # 关闭并清理客户端
                await self._close_client(account_id)

                # 清理任务与任务日志（避免 account_id 外键阻塞删除）
                task_id_rows = await session.execute(
                    select(ScheduledMessageTask.task_id).where(
                        ScheduledMessageTask.account_id == account_id
                    )
                )
                task_ids = [row[0] for row in task_id_rows.all()]
                if task_ids:
                    await session.execute(
                        delete(TaskLog).where(TaskLog.task_id.in_(task_ids))
                    )

                await session.execute(
                    delete(ScheduledMessageTask).where(
                        ScheduledMessageTask.account_id == account_id
                    )
                )

                # 清理绑定日志（历史库外键可能不是 ON DELETE SET NULL/CASCADE）
                await session.execute(
                    delete(AccountBindLog).where(AccountBindLog.account_id == account_id)
                )

                from backend.h5_backend.services.licensing.service import release_slots_for_account
                await release_slots_for_account(
                    account_id=account_id,
                    session=session,
                    reason="account_deleted",
                )

                from backend.bot.handlers.core.user_link import cleanup_active_account_refs, cleanup_scoped_account_refs
                await cleanup_active_account_refs(session, account_id)
                await cleanup_scoped_account_refs(session, account_id)

                # 解绑占用中的代理，避免留下脏的 assigned_account_id
                await session.execute(
                    update(Proxy)
                    .where(Proxy.assigned_account_id == account_id)
                    .values(assigned_account_id=None)
                )

                await session.delete(account)
                await session.commit()

                logger.info(
                    f"删除账号: {account_id}, 清理任务 {len(task_ids)} 条, "
                    f"绑定日志已清理, 代理占用已解绑"
                )
                return True
            except IntegrityError as e:
                await session.rollback()
                logger.error(f"删除账号失败（外键约束）: {account_id}, error={e}")
                raise RuntimeError("删除账号失败：仍存在关联数据，请联系管理员检查外键配置")

    # ==================== TelegramClient 管理 ====================

    async def get_client(self, account_id: str) -> Optional[TelegramClient]:
        """
        获取账号的 TelegramClient（带缓存）

        Args:
            account_id: 账号 ID

        Returns:
            TelegramClient 对象
        """
        from backend.bot.account.client_runtime import get_client as _get_client
        return await _get_client(self, account_id)

    async def _close_client(self, account_id: str):
        """关闭并清理客户端"""
        from backend.bot.account.client_runtime import close_client
        await close_client(self, account_id)

    async def _get_proxy_config(self, proxy_id: int) -> Optional[Dict[str, Any]]:
        """获取代理配置"""
        from backend.bot.account.client_runtime import get_proxy_config
        return await get_proxy_config(proxy_id)

    async def ensure_account_proxy(self, account_id: str) -> Optional[int]:
        """
        确保账号绑定健康代理：
        - 若当前代理失效，自动从池中替换并更新账号
        - 若当前无代理，尝试自动分配一个健康代理
        """
        from backend.bot.account.client_runtime import ensure_account_proxy
        return await ensure_account_proxy(self, account_id)

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
        from backend.bot.account.health_selection import select_account
        return await select_account(
            self,
            user_id=user_id,
            peer_id=peer_id,
            strategy=strategy,
        )

    # ==================== 健康检查 ====================

    async def health_check(self, account_id: str) -> HealthStatus:
        """
        检查账号健康状态（执行 get_me）

        Args:
            account_id: 账号 ID

        Returns:
            健康状态
        """
        from backend.bot.account.health_selection import health_check
        return await health_check(self, account_id)

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
        from backend.bot.account.health_selection import update_health_status
        await update_health_status(self, account_id, status)

    async def get_health_status(self, account_id: str) -> Optional[Dict[str, Any]]:
        """
        从 Redis 缓存获取健康状态

        Args:
            account_id: 账号 ID

        Returns:
            健康状态字典
        """
        from backend.bot.account.health_selection import get_health_status
        return await get_health_status(account_id)

    # ==================== 统计更新 ====================

    async def increment_messages_sent(self, account_id: str):
        """增加消息发送计数"""
        from backend.bot.account.health_selection import increment_messages_sent
        await increment_messages_sent(account_id)

    async def close_all(self):
        """关闭所有客户端连接"""
        from backend.bot.account.client_runtime import close_all_clients
        await close_all_clients(self)


# 全局单例
_account_manager: Optional[AccountManager] = None


def get_account_manager() -> AccountManager:
    """获取全局账号管理器实例"""
    global _account_manager
    if _account_manager is None:
        _account_manager = AccountManager()
    return _account_manager
