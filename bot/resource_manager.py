"""
资源管理模块

管理 Telegram Dialogs 资源同步，包括：
- 全量同步：扫描所有 Dialogs
- 增量同步：只同步新增/更新的资源
- 资源搜索和查询
- InputPeer 构造
"""
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from dataclasses import dataclass
from loguru import logger

from telethon import TelegramClient
from telethon.tl import types as tl_types
from telethon.tl.types import (
    User, Chat, Channel,
    InputPeerUser, InputPeerChat, InputPeerChannel,
)
from sqlalchemy import select, or_, cast, String as SQLString, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_async_session
from database.models import Resource, Account, PeerType
from bot.account_manager import get_account_manager
from utils.crypto import decrypt_string_session

# Telethon 不同版本可用的空实体类型不同（如 1.42 无 ChannelEmpty）
_EMPTY_PEER_TYPES = tuple(
    t for t in (
        getattr(tl_types, "UserEmpty", None),
        getattr(tl_types, "ChatEmpty", None),
        getattr(tl_types, "ChannelEmpty", None),
    )
    if t is not None
)


@dataclass
class SyncResult:
    """同步结果"""
    synced: int           # 同步总数
    new: int              # 新增数量
    updated: int          # 更新数量
    deleted: int          # 删除数量
    failed: int           # 失败数量
    error: str = ""       # 错误信息


class ResourceManager:
    """
    Dialogs 资源管理器

    功能：
    - 全量/增量同步 Dialogs
    - 资源搜索和查询
    - 构造 InputPeer 对象
    """

    def __init__(self):
        self._account_manager = get_account_manager()

    # ==================== 资源同步 ====================

    async def full_sync(self, account_id: str) -> SyncResult:
        """
        全量同步：扫描所有 Dialogs 并存储

        Args:
            account_id: 账号 ID

        Returns:
            SyncResult 对象
        """
        logger.info(f"开始全量同步: {account_id}")

        # 获取客户端
        client = await self._account_manager.get_client(account_id)
        if not client:
            error_message = await self._diagnose_client_unavailable(account_id)
            return SyncResult(0, 0, 0, 0, 0, error_message)

        result = SyncResult(0, 0, 0, 0, 0)

        try:
            # 获取所有 Dialogs
            dialogs = await client.get_dialogs()
            logger.info(f"获取到 {len(dialogs)} 个 Dialogs")
            first_peer_error = ""

            # 在同一会话中完成 upsert 与失活标记，避免脱离会话对象导致更新丢失
            async with get_async_session() as session:
                existing_resources = await session.execute(
                    select(Resource).where(Resource.account_id == account_id)
                )
                existing = {r.peer_id: r for r in existing_resources.scalars().all()}

                # 处理每个 Dialog
                for dialog in dialogs:
                    try:
                        peer = dialog.entity
                        sync_result = await self._sync_peer(
                            account_id=account_id,
                            peer=peer,
                            existing=existing,
                            session=session
                        )
                        result.synced += 1
                        if sync_result == "new":
                            result.new += 1
                        elif sync_result == "updated":
                            result.updated += 1
                    except Exception as e:
                        logger.error(f"同步 Peer 失败: {e}")
                        if not first_peer_error:
                            first_peer_error = str(e)
                        result.failed += 1

                # remaining existing 即“本次未扫描到”的资源，标记为 inactive
                for peer_id, resource in existing.items():
                    if resource.is_active:
                        resource.is_active = False
                        result.deleted += 1

                await session.commit()

            if result.synced == 0 and result.failed > 0 and first_peer_error:
                result.error = first_peer_error

            logger.info(f"全量同步完成: {result}")
            return result

        except Exception as e:
            logger.error(f"全量同步失败: {e}")
            return SyncResult(0, 0, 0, 0, 0, str(e))

    async def _diagnose_client_unavailable(self, account_id: str) -> str:
        """
        诊断无法创建客户端的常见原因，返回可执行的错误提示。
        """
        account = await self._account_manager.get_account(account_id)
        if not account:
            return "账号不存在"

        if not account.is_active:
            return "账号已禁用，请先启用账号"

        try:
            decrypt_string_session(account.string_session_encrypted)
        except Exception:
            return "StringSession 解密失败，请重新扫码绑定该账号"

        return "无法获取客户端，请确认账号仍在线并检查代理配置"

    async def _sync_peer(
        self,
        account_id: str,
        peer: Any,
        existing: Dict[int, Resource],
        session: Optional[AsyncSession] = None
    ) -> str:
        """
        同步单个 Peer

        Returns:
            "new", "updated", 或 "unchanged"
        """
        # 跳过空的 Peer
        if _EMPTY_PEER_TYPES and isinstance(peer, _EMPTY_PEER_TYPES):
            return "unchanged"

        # 提取 Peer 信息
        peer_id = peer.id
        access_hash = getattr(peer, 'access_hash', None)
        peer_type = self._get_peer_type(peer)

        if not peer_type:
            return "unchanged"

        # 构建资源数据
        resource_data = {
            "account_id": account_id,
            "peer_id": peer_id,
            "peer_type": peer_type,
            "access_hash": access_hash,
            "title": self._get_title(peer),
            "username": getattr(peer, 'username', None),
            "description": getattr(peer, 'about', None) or getattr(peer, 'description', None),
            "is_muted": getattr(peer, 'muted', False),
            "is_archived": False,  # TODO: 从 dialog 获取
            "is_verified": getattr(peer, 'verified', False),
            "is_scam": getattr(peer, 'scam', False),
            "participants_count": getattr(peer, 'participants_count', None),
            "is_active": True,
            "last_sync_at": datetime.now(),
        }

        # 检查是否已存在
        if peer_id in existing:
            resource = existing[peer_id]
            existing.pop(peer_id)  # 从待删除列表移除

            # inactive -> active 也算更新
            changed = self._has_resource_changed(resource, resource_data) or (not resource.is_active)

            # 每次同步都覆盖元数据，保证可重新激活并刷新 last_sync_at
            for key, value in resource_data.items():
                if key != "account_id":  # 不更新 account_id
                    setattr(resource, key, value)

            if session is None:
                # 兜底：未传会话时显式落库
                async with get_async_session() as sess:
                    result = await sess.execute(
                        select(Resource).where(Resource.resource_id == resource.resource_id)
                    )
                    r = result.scalar_one_or_none()
                    if r:
                        for key, value in resource_data.items():
                            if key != "account_id":
                                setattr(r, key, value)
                        await sess.commit()

            return "updated" if changed else "unchanged"
        else:
            # 新增
            new_resource = Resource(**resource_data)
            if session is not None:
                session.add(new_resource)
            else:
                async with get_async_session() as sess:
                    sess.add(new_resource)
                    await sess.commit()
            return "new"

    def _get_peer_type(self, peer: Any) -> Optional[str]:
        """获取 Peer 类型"""
        from telethon.tl.types import User, Chat, Channel
        if isinstance(peer, User):
            return PeerType.USER
        elif isinstance(peer, Chat):
            return PeerType.CHAT
        elif isinstance(peer, Channel):
            if peer.broadcast:
                return PeerType.CHANNEL
            return PeerType.SUPERGROUP
        return None

    def _get_title(self, peer: Any) -> str:
        """获取 Peer 标题"""
        if hasattr(peer, 'title') and peer.title:
            return str(peer.title).strip()

        if hasattr(peer, 'first_name'):
            first_name = str(peer.first_name or "").strip()
            last_name = str(getattr(peer, 'last_name', "") or "").strip()
            full_name = f"{first_name} {last_name}".strip()
            if full_name:
                return full_name

        username = str(getattr(peer, 'username', "") or "").strip()
        if username:
            return f"@{username}"

        peer_id = getattr(peer, 'id', None)
        peer_type = self._get_peer_type(peer)
        if peer_type == PeerType.USER:
            return f"用户 {peer_id}"
        if peer_type in (PeerType.CHAT, PeerType.SUPERGROUP):
            return f"群组 {peer_id}"
        if peer_type == PeerType.CHANNEL:
            return f"频道 {peer_id}"
        return f"会话 {peer_id}"

    def _has_resource_changed(self, resource: Resource, data: Dict[str, Any]) -> bool:
        """检查资源是否有变化"""
        return (
            resource.title != data.get("title") or
            resource.username != data.get("username") or
            resource.description != data.get("description") or
            resource.is_verified != data.get("is_verified") or
            resource.is_scam != data.get("is_scam")
        )

    async def incremental_sync(self, account_id: str) -> SyncResult:
        """
        增量同步：只同步新增/更新的资源

        Args:
            account_id: 账号 ID

        Returns:
            SyncResult 对象
        """
        # 简化实现：调用全量同步
        # TODO: 可以优化为只同步最近活跃的 Dialogs
        return await self.full_sync(account_id)

    # ==================== 资源查询 ====================

    async def get_resources(
        self,
        account_id: str,
        peer_type: Optional[str] = None,
        is_active: bool = True,
        limit: int = 1000
    ) -> List[Resource]:
        """
        获取资源列表

        Args:
            account_id: 账号 ID
            peer_type: Peer 类型筛选
            is_active: 是否只获取活跃资源
            limit: 最大返回数量

        Returns:
            Resource 列表
        """
        async with get_async_session() as session:
            query = select(Resource).where(Resource.account_id == account_id)

            if peer_type:
                query = query.where(Resource.peer_type == peer_type)
            if is_active:
                query = query.where(Resource.is_active == True)

            query = query.order_by(func.coalesce(Resource.title, "")).limit(limit)

            result = await session.execute(query)
            return result.scalars().all()

    async def search_resources(
        self,
        account_id: str,
        query: str,
        peer_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Resource]:
        """
        搜索资源（标题/用户名模糊匹配）

        Args:
            account_id: 账号 ID
            query: 搜索关键词
            peer_type: Peer 类型筛选
            limit: 最大返回数量

        Returns:
            Resource 列表
        """
        async with get_async_session() as session:
            q = select(Resource).where(
                Resource.account_id == account_id,
                Resource.is_active == True
            )

            # 模糊搜索标题或用户名
            q = q.where(
                or_(
                    Resource.title.ilike(f"%{query}%"),
                    Resource.username.ilike(f"%{query}%"),
                    cast(Resource.peer_id, SQLString).ilike(f"%{query}%")
                )
            )

            if peer_type:
                q = q.where(Resource.peer_type == peer_type)

            q = q.order_by(func.coalesce(Resource.title, "")).limit(limit)

            result = await session.execute(q)
            return result.scalars().all()

    async def get_resource(
        self,
        account_id: str,
        peer_id: int
    ) -> Optional[Resource]:
        """
        获取单个资源

        Args:
            account_id: 账号 ID
            peer_id: Peer ID

        Returns:
            Resource 对象
        """
        async with get_async_session() as session:
            result = await session.execute(
                select(Resource).where(
                    Resource.account_id == account_id,
                    Resource.peer_id == peer_id,
                    Resource.is_active == True
                )
            )
            return result.scalar_one_or_none()

    # ==================== InputPeer 构造 ====================

    async def get_input_peer(
        self,
        account_id: str,
        peer_id: int,
        peer_type: str,
        access_hash: Optional[int] = None
    ):
        """
        构造 InputPeer 对象

        Args:
            account_id: 账号 ID
            peer_id: Peer ID
            peer_type: Peer 类型
            access_hash: Access Hash（可选，会从数据库查询）

        Returns:
            InputPeerUser/InputPeerChat/InputPeerChannel 对象
        """
        # 如果没有提供 access_hash，从数据库查询
        if access_hash is None:
            resource = await self.get_resource(account_id, peer_id)
            if not resource:
                logger.error(f"资源不存在: {account_id}/{peer_id}")
                return None
            access_hash = resource.access_hash
            peer_type = resource.peer_type

        if access_hash is None:
            logger.error(f"缺少 access_hash: {account_id}/{peer_id}")
            return None

        # 构造 InputPeer
        if peer_type == PeerType.USER:
            return InputPeerUser(user_id=peer_id, access_hash=access_hash)
        elif peer_type == PeerType.CHAT:
            return InputPeerChat(chat_id=peer_id)
        elif peer_type == PeerType.SUPERGROUP or peer_type == PeerType.CHANNEL:
            return InputPeerChannel(channel_id=peer_id, access_hash=access_hash)

        logger.error(f"未知的 Peer 类型: {peer_type}")
        return None

    async def get_input_peer_by_resource_id(
        self,
        account_id: str,
        resource_id: int
    ):
        """
        通过资源 ID 获取 InputPeer

        Args:
            account_id: 账号 ID
            resource_id: 资源 ID

        Returns:
            InputPeer 对象
        """
        async with get_async_session() as session:
            result = await session.execute(
                select(Resource).where(
                    Resource.account_id == account_id,
                    Resource.resource_id == resource_id,
                    Resource.is_active == True
                )
            )
            resource = result.scalar_one_or_none()

            if not resource:
                return None

            return await self.get_input_peer(
                account_id,
                resource.peer_id,
                resource.peer_type,
                resource.access_hash
            )


# 全局单例
_resource_manager: Optional[ResourceManager] = None


def get_resource_manager() -> ResourceManager:
    """获取全局资源管理器实例"""
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = ResourceManager()
    return _resource_manager
