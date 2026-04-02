"""Resource synchronization operations for ResourceManager."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.schema.models import Resource
from backend.database.runtime.session import get_async_session
from backend.utils.security.crypto import decrypt_string_session
from backend.bot.resources.peer_utils import (
    EMPTY_PEER_TYPES,
    get_peer_type,
    get_title,
    has_resource_changed,
)


async def diagnose_client_unavailable(account_manager, account_id: str) -> str:
    """Diagnose common reasons why account client cannot be created."""
    account = await account_manager.get_account(account_id)
    if not account:
        return "账号不存在"
    if not account.is_active:
        return "账号已禁用，请先启用账号"
    try:
        decrypt_string_session(account.string_session_encrypted)
    except Exception:
        return "StringSession 解密失败，请重新在 Bot 中绑定该账号"
    return "无法获取客户端，请确认账号仍在线并检查代理配置"


async def sync_peer(
    *,
    account_id: str,
    peer: Any,
    existing: Dict[int, Resource],
    session: Optional[AsyncSession] = None,
) -> str:
    """Synchronize one peer row. Returns new/updated/unchanged."""
    if EMPTY_PEER_TYPES and isinstance(peer, EMPTY_PEER_TYPES):
        return "unchanged"

    peer_id = peer.id
    access_hash = getattr(peer, "access_hash", None)
    peer_type = get_peer_type(peer)
    if not peer_type:
        return "unchanged"

    resource_data = {
        "account_id": account_id,
        "peer_id": peer_id,
        "peer_type": peer_type,
        "access_hash": access_hash,
        "title": get_title(peer),
        "username": getattr(peer, "username", None),
        "description": getattr(peer, "about", None) or getattr(peer, "description", None),
        "is_muted": getattr(peer, "muted", False),
        "is_archived": False,
        "is_verified": getattr(peer, "verified", False),
        "is_scam": getattr(peer, "scam", False),
        "participants_count": getattr(peer, "participants_count", None),
        "is_active": True,
        "last_sync_at": datetime.now(),
    }

    if peer_id in existing:
        resource = existing[peer_id]
        existing.pop(peer_id)
        changed = has_resource_changed(resource, resource_data) or (not resource.is_active)

        for key, value in resource_data.items():
            if key != "account_id":
                setattr(resource, key, value)

        if session is None:
            async with get_async_session() as sess:
                result = await sess.execute(
                    select(Resource).where(Resource.resource_id == resource.resource_id)
                )
                row = result.scalar_one_or_none()
                if row:
                    for key, value in resource_data.items():
                        if key != "account_id":
                            setattr(row, key, value)
                    await sess.commit()
        return "updated" if changed else "unchanged"

    new_resource = Resource(**resource_data)
    if session is not None:
        session.add(new_resource)
    else:
        async with get_async_session() as sess:
            sess.add(new_resource)
            await sess.commit()
    return "new"


async def full_sync(manager, *, account_id: str, result_factory):
    """Perform full resource synchronization for one account."""
    logger.info(f"开始全量同步: {account_id}")

    client = await manager._account_manager.get_client(account_id)
    if not client:
        error_message = await diagnose_client_unavailable(manager._account_manager, account_id)
        return result_factory(0, 0, 0, 0, 0, error_message)

    result = result_factory(0, 0, 0, 0, 0)
    try:
        dialogs = await client.get_dialogs()
        logger.info(f"获取到 {len(dialogs)} 个 Dialogs")
        first_peer_error = ""

        async with get_async_session() as session:
            existing_resources = await session.execute(
                select(Resource).where(Resource.account_id == account_id)
            )
            existing = {r.peer_id: r for r in existing_resources.scalars().all()}

            for dialog in dialogs:
                try:
                    sync_result = await sync_peer(
                        account_id=account_id,
                        peer=dialog.entity,
                        existing=existing,
                        session=session,
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

            for _, resource in existing.items():
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
        return result_factory(0, 0, 0, 0, 0, str(e))
