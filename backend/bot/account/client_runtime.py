"""Telegram client/proxy runtime helpers for AccountManager."""
from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger
from telethon import TelegramClient
from telethon.sessions import StringSession

from backend.config.settings import settings
from backend.database.models import HealthStatus
from backend.utils.crypto import decrypt_proxy_password, decrypt_string_session


async def get_proxy_config(proxy_id: int) -> Optional[Dict[str, Any]]:
    """Build Telethon proxy config from proxy pool record."""
    from backend.bot.proxy_pool import get_proxy_pool

    proxy_pool = get_proxy_pool()
    proxy = await proxy_pool.get_proxy(proxy_id)
    if not proxy:
        return None

    password = None
    if proxy.password_encrypted:
        try:
            password = decrypt_proxy_password(proxy.password_encrypted)
        except Exception:
            password = None

    if proxy.proxy_type == "socks5":
        return {
            "proxy_type": "socks5",
            "addr": proxy.host,
            "port": proxy.port,
            "username": proxy.username,
            "password": password,
            "rdns": True,
        }
    if proxy.proxy_type == "http":
        return {
            "proxy_type": "http",
            "addr": proxy.host,
            "port": proxy.port,
            "username": proxy.username,
            "password": password,
        }
    return None


async def close_client(manager, account_id: str) -> None:
    """Disconnect cached client and clear lock/cache entries."""
    if account_id in manager._clients:
        try:
            await manager._clients[account_id].disconnect()
        except Exception as e:
            logger.error(f"关闭客户端失败: {e}")
        del manager._clients[account_id]

    if account_id in manager._locks:
        del manager._locks[account_id]


async def get_client(manager, account_id: str) -> Optional[TelegramClient]:
    """Get connected Telegram client for account with cache and authorization checks."""
    if account_id in manager._clients:
        client = manager._clients[account_id]
        if client.is_connected():
            return client
        del manager._clients[account_id]

    account = await manager.get_account(account_id)
    if not account:
        logger.error(f"账号不存在: {account_id}")
        return None

    try:
        string_session = decrypt_string_session(account.string_session_encrypted)
    except Exception as e:
        logger.error(
            f"解密 StringSession 失败: {e} | account_id={account_id}。"
            "可能是 ENCRYPTION_KEY 变更或历史会话使用了旧密钥，请重新扫码绑定。"
        )
        try:
            await manager.update_health_status(account_id, HealthStatus.OFFLINE)
        except Exception as status_err:
            logger.warning(f"更新账号健康状态失败: {status_err}")
        return None

    proxy = None
    if account.proxy_id:
        proxy = await get_proxy_config(account.proxy_id)

    async with await manager.get_client_lock(account_id):
        if account_id in manager._clients:
            return manager._clients[account_id]

        client = TelegramClient(
            StringSession(string_session),
            api_id=settings.api_id,
            api_hash=settings.api_hash,
            proxy=proxy,
        )
        await client.connect()

        if not await client.is_user_authorized():
            logger.error(f"账号 {account_id} 未授权，可能已登出")
            await client.disconnect()
            await manager.update_health_status(account_id, HealthStatus.OFFLINE)
            return None

        manager._clients[account_id] = client
        logger.info(f"创建 TelegramClient: {account_id}")
        return client


async def ensure_account_proxy(manager, account_id: str) -> Optional[int]:
    """Ensure one healthy proxy is bound to account; replace when unhealthy."""
    from backend.bot.proxy_pool import get_proxy_pool

    account = await manager.get_account(account_id)
    if not account:
        return None

    proxy_pool = get_proxy_pool()

    async def _assign_replacement() -> Optional[int]:
        replacement = await proxy_pool.get_available_proxy()
        if not replacement:
            return None
        assigned = await proxy_pool.assign_proxy(account_id, replacement.proxy_id)
        if not assigned:
            return None
        await manager.update_account(account_id, proxy_id=replacement.proxy_id)
        await close_client(manager, account_id)
        logger.info(f"账号 {account_id} 已切换代理 -> {replacement.proxy_id}")
        return replacement.proxy_id

    if not account.proxy_id:
        return await _assign_replacement()

    status = await proxy_pool.check_health(account.proxy_id)
    if status.is_healthy:
        return account.proxy_id

    logger.warning(
        f"账号 {account_id} 的代理 {account.proxy_id} 不健康({status.error or 'unknown'})，尝试替换"
    )
    await proxy_pool.unassign_proxy(account_id)
    await manager.update_account(account_id, proxy_id=None)

    replacement_id = await _assign_replacement()
    if replacement_id is not None:
        return replacement_id

    await close_client(manager, account_id)
    logger.warning(f"账号 {account_id} 未找到可用代理，将使用直连")
    return None


async def close_all_clients(manager) -> None:
    """Close all cached Telegram clients."""
    for account_id in list(manager._clients.keys()):
        await close_client(manager, account_id)
