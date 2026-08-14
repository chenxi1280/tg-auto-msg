"""Redis-backed cooldowns for login-related user actions."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional


BIND_START_KEY_PREFIX = "login:bind-start:"
PHONE_CODE_SEND_KEY_PREFIX = "login:phone-code-send:"
LUA_KEY_COUNT = 1
LEASE_UPDATED = 1

_COMPARE_AND_EXPIRE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""
_COMPARE_AND_DELETE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class LoginCooldownStore:
    """Owns short-lived login cooldown keys without exposing Redis details."""

    def __init__(self, redis_provider: Callable[[], Awaitable[Any]]):
        self._redis_provider = redis_provider

    async def acquire_bind_start(self, user_id: int, *, ttl_seconds: int) -> int:
        key = BIND_START_KEY_PREFIX + str(int(user_id))
        return await self._acquire(key, value="1", ttl_seconds=ttl_seconds)

    async def acquire_phone_code_send(
        self,
        login_id: str,
        token: str,
        *,
        ttl_seconds: int,
    ) -> int:
        key = self._phone_code_key(login_id)
        return await self._acquire(key, value=token, ttl_seconds=ttl_seconds)

    async def refresh_phone_code_send(
        self,
        login_id: str,
        token: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        return await self._run_owner_script(
            _COMPARE_AND_EXPIRE,
            self._phone_code_key(login_id),
            token,
            ttl_seconds,
        )

    async def release_phone_code_send(self, login_id: str, token: str) -> bool:
        return await self._run_owner_script(
            _COMPARE_AND_DELETE,
            self._phone_code_key(login_id),
            token,
        )

    async def phone_code_send_retry_after(self, login_id: str) -> int:
        redis_client = await self._redis_provider()
        return await self._remaining_ttl(redis_client, self._phone_code_key(login_id))

    async def _acquire(self, key: str, *, value: str, ttl_seconds: int) -> int:
        redis_client = await self._redis_provider()
        ttl = max(1, int(ttl_seconds))
        acquired = await redis_client.set(key, value, nx=True, ex=ttl)
        if acquired:
            return 0
        remaining = await self._remaining_ttl(redis_client, key)
        return remaining or ttl

    async def _run_owner_script(
        self,
        script: str,
        key: str,
        token: str,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        args = [key, token]
        if ttl_seconds is not None:
            args.append(str(max(1, int(ttl_seconds))))
        redis_client = await self._redis_provider()
        result = await redis_client.eval(script, LUA_KEY_COUNT, *args)
        return int(result or 0) == LEASE_UPDATED

    @staticmethod
    async def _remaining_ttl(redis_client: Any, key: str) -> int:
        return max(0, int(await redis_client.ttl(key) or 0))

    @staticmethod
    def _phone_code_key(login_id: str) -> str:
        return PHONE_CODE_SEND_KEY_PREFIX + str(login_id)
