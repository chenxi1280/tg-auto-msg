"""Telegram client/proxy runtime helpers for AccountManager."""
from __future__ import annotations

from contextlib import suppress
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


async def discard_client(manager, account_id: str, expected_client: TelegramClient) -> bool:
    """Remove and disconnect one exact cached client instance."""
    async with await manager.get_client_lock(account_id):
        cached_client = manager._clients.get(account_id)
        if cached_client is not expected_client:
            return False
        del manager._clients[account_id]

    try:
        await expected_client.disconnect()
    except Exception as exc:
        logger.error(
            "丢弃 TelegramClient 时断开失败: account_id={}, error={}",
            account_id,
            exc,
        )
    return True


async def _mark_account_offline(manager, account_id: str) -> None:
    try:
        await manager.update_health_status(account_id, HealthStatus.OFFLINE)
    except Exception as exc:
        logger.warning("更新账号健康状态失败: {}", exc)


async def _prepare_account(manager, account, account_id: str) -> bool:
    legacy_rotation = bool(getattr(account, "reauth_required", False)) and (
        str(getattr(account, "reauth_reason", "") or "") == "api_hash_rotated"
    )
    if legacy_rotation:
        logger.warning("账号 {} 带有历史 api_hash_rotated 标记，尝试刷新凭证版本", account_id)
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
        except Exception as exc:
            logger.warning("清理账号 api_hash_rotated 状态失败，将继续尝试连接: {}", exc)
    if not is_reauth_required_account(account):
        return True
    reason = getattr(account, "reauth_reason", "") or "unknown"
    logger.warning("账号 {} 需要重新绑定后才能继续使用: reason={}", account_id, reason)
    await _mark_account_offline(manager, account_id)
    return False


async def _decrypt_account_session(manager, account, account_id: str) -> Optional[str]:
    try:
        return decrypt_string_session(account.string_session_encrypted)
    except Exception as exc:
        logger.error(
            "解密 StringSession 失败: {} | account_id={}。可能是密钥变更或历史会话已损坏",
            exc,
            account_id,
        )
        await _mark_account_offline(manager, account_id)
        return None


async def _resolve_credentials(manager, account, account_id: str) -> Optional[tuple[int, str, int]]:
    api_id = int(settings.api_id) if settings.api_id else 0
    api_hash = str(settings.api_hash or "")
    version = 1
    try:
        credentials = await get_developer_app_service().resolve_credentials_for_account(account_id)
        api_id = int(credentials.api_id)
        api_hash = str(credentials.api_hash)
        version = int(getattr(credentials, "credentials_version", None) or 1)
    except Exception as exc:
        if account.developer_app_id is not None:
            logger.error(
                "按账号开发者凭证创建客户端失败: account_id={}, developer_app_id={}, error={}",
                account_id,
                account.developer_app_id,
                exc,
            )
            await _mark_account_offline(manager, account_id)
            return None
        logger.warning("账号未绑定开发者凭证，回退环境凭证: account_id={}, error={}", account_id, exc)
    if api_id > 0 and api_hash:
        return api_id, api_hash, version
    logger.error("账号 {} 缺少可用 API_ID/API_HASH，无法创建客户端", account_id)
    await _mark_account_offline(manager, account_id)
    return None


async def _connect_client(
    manager,
    *,
    account_id: str,
    string_session: str,
    proxy: Optional[Dict[str, Any]],
    credentials: tuple[int, str, int],
) -> Optional[TelegramClient]:
    api_id, api_hash, version = credentials
    client = TelegramClient(
        StringSession(string_session),
        api_id=api_id,
        api_hash=api_hash,
        proxy=proxy,
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.error("账号 {} 未授权，可能已登出", account_id)
            await client.disconnect()
            await mark_account_reauth_required(account_id, "session_unauthorized")
            return None
        await manager.update_account(
            account_id,
            developer_app_version=version,
            reauth_required=False,
            reauth_reason=None,
            reauth_required_at=None,
            health_status=HealthStatus.ONLINE,
        )
    except BaseException:
        with suppress(Exception):
            await client.disconnect()
        raise
    manager._clients[account_id] = client
    logger.info("创建 TelegramClient: {}", account_id)
    return client


async def get_client(manager, account_id: str) -> Optional[TelegramClient]:
    """Get connected Telegram client for account with cache and authorization checks."""
    cached_client = manager._clients.get(account_id)
    if cached_client is not None and cached_client.is_connected():
        return cached_client
    if cached_client is not None:
        await discard_client(manager, account_id, cached_client)

    account = await manager.get_account(account_id)
    if not account:
        logger.error("账号不存在: {}", account_id)
        return None
    if not await _prepare_account(manager, account, account_id):
        return None
    string_session = await _decrypt_account_session(manager, account, account_id)
    if string_session is None:
        return None
    proxy = await get_proxy_config(account.proxy_id) if account.proxy_id else None
    async with await manager.get_client_lock(account_id):
        cached_client = manager._clients.get(account_id)
        if cached_client is not None:
            return cached_client
        credentials = await _resolve_credentials(manager, account, account_id)
        if credentials is None:
            return None
        return await _connect_client(
            manager,
            account_id=account_id,
            string_session=string_session,
            proxy=proxy,
            credentials=credentials,
        )


async def ensure_account_proxy(manager, account_id: str) -> Optional[int]:
    """Keep a verified bound proxy or permanently fall back to direct routing."""
    from backend.bot.proxy.pool import get_proxy_pool

    account = await manager.get_account(account_id)
    if not account:
        return None

    proxy_pool = get_proxy_pool()

    if not account.proxy_id:
        return None

    current_proxy = await proxy_pool.get_proxy(account.proxy_id)
    if not current_proxy or not bool(getattr(current_proxy, "is_active", True)):
        error = "代理不存在或已停用"
    else:
        status = await proxy_pool.check_health(account.proxy_id)
        if status.is_healthy:
            return account.proxy_id
        error = status.error or "unknown"

    logger.warning(
        "账号 {} 的代理 {} 无法完成 Telegram 通信({})，永久解除绑定后使用直连",
        account_id,
        account.proxy_id,
        error,
    )
    await proxy_pool.unassign_proxy(account_id)
    await manager.update_account(account_id, proxy_id=None)

    await close_client(manager, account_id)
    return None


async def close_all_clients(manager) -> None:
    """Close all cached Telegram clients."""
    for account_id in list(manager._clients.keys()):
        await close_client(manager, account_id)
