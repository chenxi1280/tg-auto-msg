"""Proxy domain package."""

from backend.bot.proxy.pool import HealthStatus, ProxyPool, get_proxy_pool

__all__ = ["HealthStatus", "ProxyPool", "get_proxy_pool"]
