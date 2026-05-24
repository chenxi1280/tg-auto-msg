"""Telegram client/proxy runtime helpers for AccountManager."""
from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger
from telethon import TelegramClient
from telethon.sessions import StringSession

from backend.bot.account.reauth import is_reauth_required_account
from backend.bot.account.reauth_notifier import mark_account_reauth_required
from backend.config.core.settings import settings
from backend.bot.developer_apps import get_developer_app_service
from backend.database.schema.models import HealthStatus
from backend.utils.security.crypto import decrypt_proxy_password, decrypt_string_session


async def get_proxy_config(proxy_id: int) -> Optional[Dict[str, Any]]:
    """Build Telethon proxy config from proxy pool record."""
    from backend.bot.proxy.pool import get_proxy_pool

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

    if bool(getattr(account, "reauth_required", False)) and str(getattr(account, "reauth_reason", "") or "") == "api_hash_rotated":
        logger.warning(
            "账号 {} 带有历史 api_hash_rotated 标记，按兼容策略尝试继续连接并刷新凭证版本",
            account_id,
        )
        try:
            await manager.update_account(
                account_id,
                reauth_required=False,
                reauth_reason=None,
                reauth_required_at=None,
            )
            account.reauth_required = False
            account.reauth_reason = None
            account.reauth_required_at = None
        except Exception as status_err:
            logger.warning(f"清理账号 api_hash_rotated 状态失败，将继续尝试连接: {status_err}")

    if is_reauth_required_account(account):
        reason = getattr(account, "reauth_reason", "") or "unknown"
        logger.warning(f"账号 {account_id} 需要重新绑定后才能继续使用: reason={reason}")
        try:
            await manager.update_health_status(account_id, HealthStatus.OFFLINE)
        except Exception as status_err:
            logger.warning(f"更新账号健康状态失败: {status_err}")
        return None

    try:
        string_session = decrypt_string_session(account.string_session_encrypted)
    except Exception as e:
        logger.error(
            f"解密 StringSession 失败: {e} | account_id={account_id}。"
            "可能是 ENCRYPTION_KEY 变更且未配置 ENCRYPTION_KEY_FALLBACKS，"
            "或历史会话密文已损坏，请先恢复旧密钥回退配置再判断是否需要重新绑定。"
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

        api_id = int(settings.api_id) if settings.api_id else 0
        api_hash = str(settings.api_hash or "")
        try:
            developer_service = get_developer_app_service()
            credentials = await developer_service.resolve_credentials_for_account(account_id)
            api_id = int(credentials.api_id)
            api_hash = str(credentials.api_hash)
        except Exception as e:
            if account.developer_app_id is not None:
                logger.error(
                    f"按账号开发者凭证创建客户端失败: account_id={account_id}, "
                    f"developer_app_id={account.developer_app_id}, error={e}"
                )
                try:
                    await manager.update_health_status(account_id, HealthStatus.OFFLINE)
                except Exception as status_err:
                    logger.warning(f"更新账号健康状态失败: {status_err}")
                return None
            logger.warning(f"账号未绑定开发者凭证，回退环境凭证: account_id={account_id}, error={e}")

        if api_id <= 0 or not api_hash:
            logger.error(f"账号 {account_id} 缺少可用 API_ID/API_HASH，无法创建客户端")
            try:
                await manager.update_health_status(account_id, HealthStatus.OFFLINE)
            except Exception as status_err:
                logger.warning(f"更新账号健康状态失败: {status_err}")
            return None
        client = TelegramClient(
            StringSession(string_session),
            api_id=api_id,
            api_hash=api_hash,
            proxy=proxy,
        )
        await client.connect()

        if not await client.is_user_authorized():
            logger.error(f"账号 {account_id} 未授权，可能已登出")
            await client.disconnect()
            await mark_account_reauth_required(account_id, "session_unauthorized")
            return None

        await manager.update_account(
            account_id,
            developer_app_version=int(credentials.credentials_version or 1),
            reauth_required=False,
            reauth_reason=None,
            reauth_required_at=None,
            health_status=HealthStatus.ONLINE,
        )
        manager._clients[account_id] = client
        logger.info(f"创建 TelegramClient: {account_id}")
        return client


async def ensure_account_proxy(manager, account_id: str) -> Optional[int]:
    """Ensure one healthy proxy is bound to account; replace when unhealthy."""
    from backend.bot.proxy.pool import get_proxy_pool

    account = await manager.get_account(account_id)
    if not account:
        return None

    proxy_pool = get_proxy_pool()
    if account.proxy_id:
        current_proxy = await proxy_pool.get_proxy(account.proxy_id)
        if current_proxy and bool(getattr(current_proxy, "is_system_gateway", False)):
            return account.proxy_id

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
