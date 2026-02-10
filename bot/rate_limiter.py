"""
速率限制模块

实现多级速率限制：
- 账号级别：1秒内只能发1条消息
- 群组级别：同一目标维持2秒以上间隔
- 零宽字符自动添加（去重）
"""
import asyncio
import random
import time
from typing import Optional
from loguru import logger

import redis.asyncio as redis

from config.settings import settings


class RateLimiter:
    """
    多级速率限制器

    Redis 数据结构：
    - lock:account:{account_id} - String，账号发送锁（TTL: 1秒）
    - lock:peer:{peer_id} - String，群组发送锁（TTL: 2秒）
    - rate:account:{account_id}:msg - String，发送计数
    - rate:peer:{peer_id}:last - String，最后发送时间
    """

    # Redis Key 前缀
    ACCOUNT_LOCK_PREFIX = "lock:account:"
    PEER_LOCK_PREFIX = "lock:peer:"

    # 速率限制配置
    ACCOUNT_LOCK_TTL = 1      # 账号级别：1秒
    PEER_LOCK_TTL = 2         # 群组级别：2秒

    # 零宽字符列表（用于去重）
    ZERO_WIDTH_CHARS = ['\u200B', '\u200C', '\u200D', '\uFEFF']

    def __init__(self, redis_url: str | None = None):
        """
        初始化速率限制器

        Args:
            redis_url: Redis 连接 URL
        """
        self._redis_url = redis_url or settings.redis_url
        self._redis_client: Optional[redis.Redis] = None

    async def _get_redis(self) -> redis.Redis:
        """获取 Redis 客户端"""
        if self._redis_client is None:
            self._redis_client = await redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        return self._redis_client

    # ==================== 锁机制 ====================

    async def acquire_account_lock(self, account_id: str) -> bool:
        """
        获取账号发送锁（1秒内只能发1条）

        Args:
            account_id: 账号 ID

        Returns:
            是否获取成功
        """
        r = await self._get_redis()
        key = self.ACCOUNT_LOCK_PREFIX + account_id

        # 尝试设置锁（NX：不存在时才设置）
        lock_acquired = await r.set(key, "1", nx=True, ex=self.ACCOUNT_LOCK_TTL)

        if lock_acquired:
            logger.debug(f"获取账号锁: {account_id}")
        else:
            logger.debug(f"账号锁已被占用: {account_id}")

        return lock_acquired

    async def acquire_peer_lock(self, peer_id: int) -> bool:
        """
        获取群组发送锁（同一目标2秒间隔）

        Args:
            peer_id: Peer ID

        Returns:
            是否获取成功
        """
        r = await self._get_redis()
        key = self.PEER_LOCK_PREFIX + str(peer_id)

        # 尝试设置锁
        lock_acquired = await r.set(key, "1", nx=True, ex=self.PEER_LOCK_TTL)

        if lock_acquired:
            logger.debug(f"获取群组锁: {peer_id}")
        else:
            logger.debug(f"群组锁已被占用: {peer_id}")

        return lock_acquired

    async def release_account_lock(self, account_id: str):
        """
        释放账号锁（通常不需要，锁会自动过期）

        Args:
            account_id: 账号 ID
        """
        r = await self._get_redis()
        key = self.ACCOUNT_LOCK_PREFIX + account_id
        await r.delete(key)

    async def release_peer_lock(self, peer_id: int):
        """
        释放群组锁

        Args:
            peer_id: Peer ID
        """
        r = await self._get_redis()
        key = self.PEER_LOCK_PREFIX + str(peer_id)
        await r.delete(key)

    # ==================== 等待时间槽 ====================

    async def wait_for_slot(
        self,
        account_id: str,
        peer_id: int,
        max_wait: float = 10.0
    ) -> float:
        """
        等待可用时间槽

        Args:
            account_id: 账号 ID
            peer_id: Peer ID
            max_wait: 最大等待时间（秒）

        Returns:
            实际等待时间（秒）
        """
        start_time = time.time()
        waited = 0.0

        while waited < max_wait:
            # 检查账号锁
            account_locked = not await self.acquire_account_lock(account_id)
            if account_locked:
                await asyncio.sleep(0.1)
                waited = time.time() - start_time
                continue

            # 检查群组锁
            peer_locked = not await self.acquire_peer_lock(peer_id)
            if peer_locked:
                # 释放账号锁
                await self.release_account_lock(account_id)
                await asyncio.sleep(0.1)
                waited = time.time() - start_time
                continue

            # 两个锁都获取成功
            logger.debug(f"获取时间槽成功: account={account_id}, peer={peer_id}, 等待={waited:.2f}s")
            return waited

        # 超时后抛错，调用方必须显式处理，避免继续发送导致破限
        logger.warning(f"等待时间槽超时: account={account_id}, peer={peer_id}")
        raise TimeoutError(f"等待发送时间槽超时: account={account_id}, peer={peer_id}")

    # ==================== 零宽字符去重 ====================

    def add_zero_width_chars(self, text: str, max_chars: int = 5) -> str:
        """
        添加零宽字符实现去重

        Args:
            text: 原始文本
            max_chars: 最多添加的零宽字符数

        Returns:
            添加了零宽字符的文本
        """
        if not text:
            return text

        # 随机添加 1-3 个零宽字符
        num_chars = random.randint(1, min(3, max_chars))
        chars_to_add = random.sample(self.ZERO_WIDTH_CHARS, num_chars)

        # 在文本末尾添加
        result = text + ''.join(chars_to_add)

        return result

    def add_invisible_variation(self, text: str) -> str:
        """
        添加不可见变体（更高级的去重）

        Args:
            text: 原始文本

        Returns:
            添加了变体的文本
        """
        if not text:
            return text

        # 方案1：零宽字符
        result = self.add_zero_width_chars(text)

        # 方案2：在随机位置插入零宽字符
        chars = list(result)
        insert_positions = random.sample(
            range(len(chars)),
            min(2, len(chars))
        )
        zero_width = random.choice(self.ZERO_WIDTH_CHARS)
        for pos in sorted(insert_positions, reverse=True):
            chars.insert(pos, zero_width)

        return ''.join(chars)

    # ==================== 发送统计 ====================

    async def record_send(
        self,
        account_id: str,
        peer_id: int
    ):
        """
        记录发送（用于统计）

        Args:
            account_id: 账号 ID
            peer_id: Peer ID
        """
        # 这里可以添加发送统计逻辑
        # 例如：记录到 Redis 或数据库
        pass

    async def get_send_count(
        self,
        account_id: str,
        window_seconds: int = 60
    ) -> int:
        """
        获取账号在指定时间窗口内的发送次数

        Args:
            account_id: 账号 ID
            window_seconds: 时间窗口（秒）

        Returns:
            发送次数
        """
        r = await self._get_redis()
        key = f"rate:account:{account_id}:msg"

        # 获取计数
        count = await r.get(key)
        return int(count) if count else 0


# 全局单例
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """获取全局速率限制器实例"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


async def acquire_locks_and_send(
    account_id: str,
    peer_id: int,
    send_func,
    *args,
    **kwargs
):
    """
    获取锁并发送消息的便捷函数

    Args:
        account_id: 账号 ID
        peer_id: Peer ID
        send_func: 发送函数
        *args, **kwargs: 传递给 send_func 的参数

    Returns:
        发送函数的返回值
    """
    rate_limiter = get_rate_limiter()

    # 等待时间槽
    await rate_limiter.wait_for_slot(account_id, peer_id)

    try:
        # 执行发送
        result = await send_func(*args, **kwargs)

        # 记录发送
        await rate_limiter.record_send(account_id, peer_id)

        return result

    finally:
        # 释放锁（让锁自动过期也可以，但主动释放更及时）
        await rate_limiter.release_account_lock(account_id)
        await rate_limiter.release_peer_lock(peer_id)
