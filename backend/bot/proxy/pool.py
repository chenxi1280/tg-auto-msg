"""Proxy pool facade for CRUD/assignment/health operations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from backend.bot.proxy.health import (
    check_all_proxies as _check_all_proxies,
    check_health as _check_health,
    get_proxy_config as _get_proxy_config,
)
from backend.bot.proxy.ops import (
    add_proxy as _add_proxy,
    assign_proxy as _assign_proxy,
    delete_proxy as _delete_proxy,
    get_available_proxy as _get_available_proxy,
    get_proxies as _get_proxies,
    get_proxy as _get_proxy,
    unassign_proxy as _unassign_proxy,
    update_proxy as _update_proxy,
)


HEALTH_CACHE_TTL_SECONDS = 60


@dataclass
class HealthStatus:
    """Proxy health status payload."""
    is_healthy: bool
    response_time_ms: int
    error: str = ""


class ProxyPool:
    """Proxy pool manager facade."""

    def __init__(self):
        self._health_cache: Dict[int, HealthStatus] = {}
        self._health_cache_checked_at: Dict[int, float] = {}
        self._cache_ttl = HEALTH_CACHE_TTL_SECONDS

    async def add_proxy(
        self,
        proxy_type: str,
        host: str,
        port: int,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        return await _add_proxy(
            proxy_type=proxy_type,
            host=host,
            port=port,
            username=username,
            password=password,
        )

    async def get_proxy(self, proxy_id: int):
        return await _get_proxy(proxy_id)

    async def get_proxies(
        self,
        is_active: bool = True,
        is_healthy: Optional[bool] = True,
    ):
        return await _get_proxies(is_active=is_active, is_healthy=is_healthy)

    async def delete_proxy(self, proxy_id: int) -> bool:
        return await _delete_proxy(self, proxy_id)

    async def update_proxy(self, proxy_id: int, **kwargs):
        return await _update_proxy(proxy_id, **kwargs)

    async def get_available_proxy(self):
        return await _get_available_proxy()

    async def assign_proxy(self, account_id: str, proxy_id: int) -> bool:
        return await _assign_proxy(account_id, proxy_id)

    async def unassign_proxy(self, account_id: str) -> bool:
        return await _unassign_proxy(account_id)

    async def check_health(self, proxy_id: int, timeout: int = 10) -> HealthStatus:
        return await _check_health(
            self,
            proxy_id=proxy_id,
            timeout=timeout,
            status_factory=HealthStatus,
        )

    async def check_all_proxies(self) -> Dict[int, HealthStatus]:
        return await _check_all_proxies(self, status_factory=HealthStatus)

    async def get_healthy_proxies(self):
        return await self.get_proxies(is_active=True, is_healthy=True)

    async def get_proxy_config(self, proxy_id: int) -> Optional[Dict[str, Any]]:
        return await _get_proxy_config(self, proxy_id=proxy_id)

    def clear_health_cache(self):
        self._health_cache.clear()
        self._health_cache_checked_at.clear()


_proxy_pool: Optional[ProxyPool] = None


def get_proxy_pool() -> ProxyPool:
    """Get singleton proxy pool instance."""
    global _proxy_pool
    if _proxy_pool is None:
        _proxy_pool = ProxyPool()
    return _proxy_pool
