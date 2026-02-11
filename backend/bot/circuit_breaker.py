"""
熔断器模块

处理 Telegram API 错误和健康监控：
- FloodWait 错误处理
- Session 失效检测
- 自动熔断和恢复
- 用户通知
"""
from enum import Enum
from typing import Optional, Callable, Any
from datetime import datetime, timedelta
from loguru import logger
import asyncio

from telethon.errors import (
    FloodWaitError,
)
from backend.database.models import HealthStatus
from backend.bot.account_manager import get_account_manager
from backend.bot.circuit.notify import (
    notify_account_recovered,
    notify_flood_wait,
    notify_session_invalid,
    send_notification,
)
from backend.bot.circuit.recovery import (
    check_session_health,
    recover_account,
    start_health_check,
    start_recovery_task,
    stop_health_check,
)


class FloodWaitAction(str, Enum):
    """FloodWait 处理动作"""
    RETRY = "retry"        # 等待后重试
    SKIP = "skip"          # 跳过本次发送
    BAN = "ban"            # 标记账号封禁


class CircuitBreaker:
    """
    熔断器 - 处理 FloodWait 和 Session 失效

    功能：
    - FloodWait 错误自动处理
    - Session 健康检查
    - 账号自动熔断和恢复
    - 用户通知
    """

    # FloodWait 阈值（秒）
    FLOOD_WAIT_BAN_THRESHOLD = 24 * 3600  # 24 小时以上标记为封禁
    PEER_FLOOD_BAN_SECONDS = 24 * 3600     # PeerFlood 固定熔断 24 小时

    # 健康检查间隔
    HEALTH_CHECK_INTERVAL = 3600  # 1 小时

    def __init__(self):
        self._account_manager = get_account_manager()
        self._health_check_tasks: dict[str, asyncio.Task] = {}

    # ==================== FloodWait 处理 ====================

    async def handle_flood_wait(
        self,
        account_id: str,
        error: FloodWaitError
    ) -> FloodWaitAction:
        """
        处理 FloodWait 错误

        Args:
            account_id: 账号 ID
            error: FloodWaitError 异常

        Returns:
            处理动作
        """
        seconds = error.seconds

        logger.warning(
            f"账号 {account_id} 触发 FloodWait: {seconds}秒"
        )

        # 计算解除时间
        flood_until = datetime.now() + timedelta(seconds=seconds)

        # 判断是否需要封禁
        if seconds >= self.FLOOD_WAIT_BAN_THRESHOLD:
            # 24小时以上，标记为封禁
            await self._account_manager.update_account(
                account_id,
                is_banned=True,
                flood_until=flood_until
            )

            logger.error(
                f"账号 {account_id} FloodWait 超过 24 小时，"
                f"标记为封禁，解除时间: {flood_until}"
            )

            # 通知用户
            await self._notify_flood_wait(account_id, seconds, is_banned=True)

            return FloodWaitAction.BAN

        # 更新 FloodWait 状态
        await self._account_manager.update_account(
            account_id,
            is_flooding=True,
            flood_until=flood_until
        )

        # 判断是否等待重试
        if seconds <= 300:  # 5 分钟以内可以等待
            logger.info(f"账号 {account_id} FloodWait 较短，将等待重试")

            # 启动恢复任务
            self._start_recovery_task(account_id, seconds)

            return FloodWaitAction.RETRY
        else:
            # 较长时间，跳过本次
            logger.info(f"账号 {account_id} FloodWait 较长，跳过本次发送")

            # 启动恢复任务
            self._start_recovery_task(account_id, seconds)

            # 通知用户
            await self._notify_flood_wait(account_id, seconds, is_banned=False)

            return FloodWaitAction.SKIP

    async def handle_peer_flood(self, account_id: str) -> datetime:
        """
        处理 PeerFloodError：
        按账号级别熔断 24 小时，避免账号进一步受限。
        """
        flood_until = datetime.now() + timedelta(seconds=self.PEER_FLOOD_BAN_SECONDS)
        await self._account_manager.update_account(
            account_id,
            is_flooding=True,
            flood_until=flood_until
        )
        logger.error(f"账号 {account_id} 触发 PeerFlood，已熔断至 {flood_until}")
        await self._notify_flood_wait(account_id, self.PEER_FLOOD_BAN_SECONDS, is_banned=False)
        return flood_until

    def _start_recovery_task(self, account_id: str, delay_seconds: int):
        """启动恢复任务"""
        start_recovery_task(self, account_id, delay_seconds)

    async def recover_account(self, account_id: str):
        """
        恢复账号（FloodWait 解除后）

        Args:
            account_id: 账号 ID
        """
        await recover_account(self, account_id)

    # ==================== Session 健康检查 ====================

    async def check_session_health(self, account_id: str) -> bool:
        """
        检查 Session 是否有效

        Args:
            account_id: 账号 ID

        Returns:
            Session 是否有效
        """
        return await check_session_health(self, account_id)

    async def start_health_check(self, account_id: str):
        """
        启动账号健康检查循环

        Args:
            account_id: 账号 ID
        """
        await start_health_check(self, account_id)

    async def stop_health_check(self, account_id: str):
        """停止账号健康检查"""
        await stop_health_check(self, account_id)

    # ==================== 用户通知 ====================

    async def _notify_flood_wait(
        self,
        account_id: str,
        seconds: int,
        is_banned: bool
    ):
        """
        通知用户 FloodWait 事件

        Args:
            account_id: 账号 ID
            seconds: 等待秒数
            is_banned: 是否被标记为封禁
        """
        await notify_flood_wait(self._account_manager, account_id, seconds, is_banned)

    async def _notify_session_invalid(self, account_id: str):
        """
        通知用户 Session 失效

        Args:
            account_id: 账号 ID
        """
        await notify_session_invalid(self._account_manager, account_id)

    async def _notify_account_recovered(self, account_id: str):
        """
        通知用户账号已恢复

        Args:
            account_id: 账号 ID
        """
        await notify_account_recovered(self._account_manager, account_id)

    async def _send_notification(self, user_id: int, message: str):
        """
        发送通知给用户

        Args:
            user_id: 用户 ID
            message: 消息内容
        """
        await send_notification(user_id, message)

    # ==================== 错误处理包装器 ====================

    async def execute_with_circuit_breaker(
        self,
        account_id: str,
        func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        使用熔断器执行函数

        Args:
            account_id: 账号 ID
            func: 要执行的函数
            *args, **kwargs: 函数参数

        Returns:
            函数返回值

        Raises:
            Exception: 如果无法恢复的错误
        """
        # 检查账号状态
        account = await self._account_manager.get_account(account_id)
        if not account:
            raise ValueError(f"账号不存在: {account_id}")

        # 检查是否被禁用
        if account.is_banned:
            raise ValueError(f"账号已被封禁: {account_id}")

        # 检查是否在 FloodWait 中
        if account.is_flooding and account.flood_until:
            now = datetime.now()
            if now < account.flood_until:
                # 还在等待期
                remaining = (account.flood_until - now).total_seconds()
                logger.warning(f"账号 {account_id} 还在 FloodWait 中，剩余 {remaining:.0f} 秒")
                # Telethon FloodWaitError 构造参数为 (request, capture)，
                # capture 会被解析为 seconds
                raise FloodWaitError(request=None, capture=int(remaining))
            else:
                # FloodWait 已过，尝试恢复
                await self.recover_account(account_id)

        try:
            # 执行函数
            result = await func(*args, **kwargs)
            return result

        except FloodWaitError as e:
            # 处理 FloodWait
            action = await self.handle_flood_wait(account_id, e)

            if action == FloodWaitAction.RETRY:
                # 等待后重试
                await asyncio.sleep(e.seconds)
                return await func(*args, **kwargs)
            elif action == FloodWaitAction.SKIP:
                raise  # 跳过本次
            elif action == FloodWaitAction.BAN:
                raise  # 标记为封禁

        except Exception as e:
            # 其他错误，检查是否是 Session 失效
            error_str = str(e).lower()
            if any(keyword in error_str for keyword in [
                'session', 'authorized', 'key', 'deactivated'
            ]):
                await self._account_manager.update_health_status(
                    account_id, HealthStatus.OFFLINE
                )
                await self._notify_session_invalid(account_id)

            raise


# 全局单例
_circuit_breaker: Optional[CircuitBreaker] = None


def get_circuit_breaker() -> CircuitBreaker:
    """获取全局熔断器实例"""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker
