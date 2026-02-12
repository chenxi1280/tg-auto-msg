"""Bot package."""

from backend.bot.account.manager import get_account_manager
from backend.bot.circuit.breaker import get_circuit_breaker
from backend.bot.client_runtime.manager import bot_client, userbot_client
from backend.bot.proxy.pool import get_proxy_pool
from backend.bot.resources.manager import get_resource_manager

__all__ = [
    "bot_client",
    "userbot_client",
    "get_account_manager",
    "get_proxy_pool",
    "get_resource_manager",
    "get_circuit_breaker",
]
