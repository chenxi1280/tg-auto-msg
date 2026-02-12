"""Proxy health checking and Telethon config helpers."""
from __future__ import annotations

import asyncio
import socket
from datetime import datetime
from typing import Any, Dict, Optional

from backend.database.schema.models import ProxyType
from backend.utils.security.crypto import decrypt_proxy_password


async def check_health(manager, *, proxy_id: int, timeout: int, status_factory):
    """Check one proxy health with simple TCP connectivity test."""
    if proxy_id in manager._health_cache:
        cached = manager._health_cache[proxy_id]
        if cached.is_healthy:
            return cached

    proxy = await manager.get_proxy(proxy_id)
    if not proxy:
        return status_factory(False, 0, "代理不存在")

    start_time = datetime.now()
    is_healthy = False
    error = ""

    try:
        if proxy.password_encrypted:
            try:
                decrypt_proxy_password(proxy.password_encrypted)
            except Exception:
                pass

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((proxy.host, proxy.port))
        sock.close()
        is_healthy = True
    except socket.timeout:
        error = "连接超时"
    except ConnectionRefusedError:
        error = "连接被拒绝"
    except Exception as e:
        error = str(e)

    response_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
    await manager.update_proxy(
        proxy_id,
        is_healthy=is_healthy,
        last_check_at=datetime.now(),
        response_time_ms=response_time_ms if is_healthy else None,
    )

    status = status_factory(is_healthy, response_time_ms if is_healthy else 0, error)
    manager._health_cache[proxy_id] = status
    return status


async def check_all_proxies(manager, *, status_factory) -> Dict[int, Any]:
    """Check health of all active proxies concurrently."""
    proxies = await manager.get_proxies(is_active=True, is_healthy=None)
    tasks = [
        check_health(manager, proxy_id=proxy.proxy_id, timeout=10, status_factory=status_factory)
        for proxy in proxies
    ]
    health_statuses = await asyncio.gather(*tasks)
    return {proxy.proxy_id: status for proxy, status in zip(proxies, health_statuses)}


async def get_proxy_config(manager, *, proxy_id: int) -> Optional[Dict[str, Any]]:
    """Get Telethon proxy config for one proxy id."""
    proxy = await manager.get_proxy(proxy_id)
    if not proxy:
        return None

    password = None
    if proxy.password_encrypted:
        try:
            password = decrypt_proxy_password(proxy.password_encrypted)
        except Exception:
            password = None

    if proxy.proxy_type == ProxyType.SOCKS5:
        return {
            "proxy_type": "socks5",
            "addr": proxy.host,
            "port": proxy.port,
            "username": proxy.username,
            "password": password,
            "rdns": True,
        }
    if proxy.proxy_type == ProxyType.HTTP:
        return {
            "proxy_type": "http",
            "addr": proxy.host,
            "port": proxy.port,
            "username": proxy.username,
            "password": password,
        }
    return None
