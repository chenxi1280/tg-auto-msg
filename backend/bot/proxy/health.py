"""Telegram MTProto proxy health checks and proxy configuration helpers."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import time
from typing import Any, Dict, Optional

from loguru import logger
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.help import GetConfigRequest

from backend.config.core.settings import settings
from backend.database.schema.models import ProxyType
from backend.utils.security.crypto import decrypt_proxy_password


def _cached_health(manager, proxy_id: int):
    checked_at = manager._health_cache_checked_at.get(proxy_id)
    cached = manager._health_cache.get(proxy_id)
    if checked_at is None or cached is None:
        return None
    if time.monotonic() - checked_at < manager._cache_ttl:
        return cached
    manager._health_cache.pop(proxy_id, None)
    manager._health_cache_checked_at.pop(proxy_id, None)
    return None


def _proxy_config(proxy) -> Dict[str, Any]:
    password = None
    if proxy.password_encrypted:
        password = decrypt_proxy_password(proxy.password_encrypted)

    proxy_type = getattr(proxy, "proxy_type", None)
    if proxy_type == ProxyType.SOCKS5 or str(proxy_type).lower() == "socks5":
        return {
            "proxy_type": "socks5",
            "addr": proxy.host,
            "port": proxy.port,
            "username": proxy.username,
            "password": password,
            "rdns": True,
        }
    if proxy_type == ProxyType.HTTP or str(proxy_type).lower() == "http":
        return {
            "proxy_type": "http",
            "addr": proxy.host,
            "port": proxy.port,
            "username": proxy.username,
            "password": password,
        }
    raise ValueError(f"不支持的代理类型: {proxy_type}")


async def probe_telegram_proxy(
    proxy_config: Dict[str, Any], *, api_id: int, api_hash: str, timeout: int
) -> int:
    """Return MTProto probe latency after a real Telegram configuration request."""
    client = TelegramClient(
        StringSession(),
        api_id=api_id,
        api_hash=api_hash,
        proxy=proxy_config,
        timeout=timeout,
        connection_retries=1,
        request_retries=1,
        retry_delay=1,
        auto_reconnect=False,
    )
    started_at = time.monotonic()
    try:
        async with asyncio.timeout(timeout):
            await client.connect()
            await client(GetConfigRequest())
        return int((time.monotonic() - started_at) * 1000)
    finally:
        with suppress(Exception):
            await client.disconnect()


async def check_health(
    manager,
    *,
    proxy_id: int,
    timeout: int,
    status_factory,
    api_id: Optional[int] = None,
    api_hash: Optional[str] = None,
):
    """Check proxy availability with Telegram MTProto, not only a TCP socket."""
    cached = _cached_health(manager, proxy_id)
    if cached is not None:
        return cached

    proxy = await manager.get_proxy(proxy_id)
    if not proxy:
        return status_factory(False, 0, "代理不存在")

    started_at = time.monotonic()
    try:
        resolved_api_id = int(api_id if api_id is not None else settings.api_id or 0)
        resolved_api_hash = str(api_hash if api_hash is not None else settings.api_hash or "")
        if resolved_api_id <= 0 or not resolved_api_hash:
            raise ValueError("缺少 Telegram API 凭证，无法验证代理")
        latency_ms = await probe_telegram_proxy(
            _proxy_config(proxy),
            api_id=resolved_api_id,
            api_hash=resolved_api_hash,
            timeout=timeout,
        )
        is_healthy = True
        error = ""
    except Exception as exc:
        latency_ms = int((time.monotonic() - started_at) * 1000)
        is_healthy = False
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("代理 {} MTProto 健康检查失败: {}", proxy_id, error)

    await manager.update_proxy(
        proxy_id,
        is_healthy=is_healthy,
        last_check_at=time_to_datetime(),
        response_time_ms=latency_ms if is_healthy else None,
    )
    status = status_factory(is_healthy, latency_ms if is_healthy else 0, error)
    manager._health_cache[proxy_id] = status
    manager._health_cache_checked_at[proxy_id] = time.monotonic()
    return status


def time_to_datetime():
    """Keep database timestamps wall-clock based while cache timestamps stay monotonic."""
    from datetime import datetime

    return datetime.now()


async def check_all_proxies(manager, *, status_factory) -> Dict[int, Any]:
    """Check all active proxies concurrently with the Telegram protocol probe."""
    proxies = await manager.get_proxies(is_active=True, is_healthy=None)
    tasks = [
        check_health(manager, proxy_id=proxy.proxy_id, timeout=10, status_factory=status_factory)
        for proxy in proxies
    ]
    health_statuses = await asyncio.gather(*tasks)
    return {proxy.proxy_id: status for proxy, status in zip(proxies, health_statuses)}


async def get_proxy_config(manager, *, proxy_id: int) -> Optional[Dict[str, Any]]:
    """Get Telethon configuration for one proxy record."""
    proxy = await manager.get_proxy(proxy_id)
    return _proxy_config(proxy) if proxy else None
