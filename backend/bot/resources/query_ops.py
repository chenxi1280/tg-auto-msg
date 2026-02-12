"""Resource query and InputPeer construction helpers."""
from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy import String as SQLString, cast, func, or_, select
from telethon.tl.types import InputPeerChannel, InputPeerChat, InputPeerUser

from backend.database.schema.models import PeerType, Resource
from backend.database.runtime.session import get_async_session


async def get_resources(
    *,
    account_id: str,
    peer_type: Optional[str],
    is_active: bool,
    limit: int,
):
    """List resources by filters."""
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
    *,
    account_id: str,
    query_text: str,
    peer_type: Optional[str],
    limit: int,
):
    """Search resources by title/username/peer_id."""
    async with get_async_session() as session:
        query = select(Resource).where(
            Resource.account_id == account_id,
            Resource.is_active == True,
        )
        query = query.where(
            or_(
                Resource.title.ilike(f"%{query_text}%"),
                Resource.username.ilike(f"%{query_text}%"),
                cast(Resource.peer_id, SQLString).ilike(f"%{query_text}%"),
            )
        )
        if peer_type:
            query = query.where(Resource.peer_type == peer_type)
        query = query.order_by(func.coalesce(Resource.title, "")).limit(limit)
        result = await session.execute(query)
        return result.scalars().all()


async def get_resource(*, account_id: str, peer_id: int):
    """Get one active resource by peer id."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Resource).where(
                Resource.account_id == account_id,
                Resource.peer_id == peer_id,
                Resource.is_active == True,
            )
        )
        return result.scalar_one_or_none()


async def get_input_peer(
    *,
    account_id: str,
    peer_id: int,
    peer_type: str,
    access_hash: Optional[int],
):
    """Build Telethon InputPeer from resource metadata."""
    if access_hash is None:
        resource = await get_resource(account_id=account_id, peer_id=peer_id)
        if not resource:
            logger.error(f"资源不存在: {account_id}/{peer_id}")
            return None
        access_hash = resource.access_hash
        peer_type = resource.peer_type

    if access_hash is None:
        logger.error(f"缺少 access_hash: {account_id}/{peer_id}")
        return None

    if peer_type == PeerType.USER:
        return InputPeerUser(user_id=peer_id, access_hash=access_hash)
    if peer_type == PeerType.CHAT:
        return InputPeerChat(chat_id=peer_id)
    if peer_type in (PeerType.SUPERGROUP, PeerType.CHANNEL):
        return InputPeerChannel(channel_id=peer_id, access_hash=access_hash)

    logger.error(f"未知的 Peer 类型: {peer_type}")
    return None


async def get_input_peer_by_resource_id(*, account_id: str, resource_id: int):
    """Build InputPeer by resource primary key."""
    async with get_async_session() as session:
        result = await session.execute(
            select(Resource).where(
                Resource.account_id == account_id,
                Resource.resource_id == resource_id,
                Resource.is_active == True,
            )
        )
        resource = result.scalar_one_or_none()
        if not resource:
            return None

    return await get_input_peer(
        account_id=account_id,
        peer_id=resource.peer_id,
        peer_type=resource.peer_type,
        access_hash=resource.access_hash,
    )
