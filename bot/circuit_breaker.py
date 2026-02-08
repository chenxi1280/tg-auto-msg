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
    SessionPasswordNeededError,
    RPCError,
)
from telethon import TelegramClient

from database.session import get_async_session
from database.models import Account, HealthStatus
from bot.account_manager import get_account_manager
from config.settings import settings


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

    def _start_recovery_task(self, account_id: str, delay_seconds: int):
        """启动恢复任务"""
        # 取消现有任务
        if account_id in self._health_check_tasks:
            self._health_check_tasks[account_id].cancel()

        # 创建新任务
        async def recovery_task():
            try:
                await asyncio.sleep(delay_seconds)
                await self.recover_account(account_id)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"恢复任务失败: {e}")

        task = asyncio.create_task(recovery_task())
        self._health_check_tasks[account_id] = task

    async def recover_account(self, account_id: str):
        """
        恢复账号（FloodWait 解除后）

        Args:
            account_id: 账号 ID
        """
        logger.info(f"尝试恢复账号: {account_id}")

        # 检查是否可以恢复
        account = await self._account_manager.get_account(account_id)
        if not account:
            return

        now = datetime.now()
        if account.flood_until and now < account.flood_until:
            # 还未到解除时间
            remaining = (account.flood_until - now).total_seconds()
            logger.info(f"账号 {account_id} 还需等待 {remaining:.0f} 秒")
            # 重新启动恢复任务
            self._start_recovery_task(account_id, int(remaining) + 1)
            return

        # 恢复账号
        await self._account_manager.update_account(
            account_id,
            is_flooding=False,
            flood_until=None
        )

        # 健康检查
        health = await self._account_manager.health_check(account_id)

        if health == HealthStatus.ONLINE:
            logger.info(f"账号 {account_id} 已恢复")
            # 通知用户
            await self._notify_account_recovered(account_id)
        else:
            logger.warning(f"账号 {account_id} 恢复失败，状态为 {health}")

    # ==================== Session 健康检查 ====================

    async def check_session_health(self, account_id: str) -> bool:
        """
        检查 Session 是否有效

        Args:
            account_id: 账号 ID

        Returns:
            Session 是否有效
        """
        client = await self._account_manager.get_client(account_id)
        if not client:
            return False

        try:
            me = await client.get_me()
            if me:
                await self._account_manager.update_health_status(
                    account_id, HealthStatus.ONLINE
                )
                return True
        except SessionPasswordNeededError:
            logger.error(f"账号 {account_id} 需要两步验证密码")
            await self._account_manager.update_health_status(
                account_id, HealthStatus.OFFLINE
            )
            return False
        except RPCError as e:
            logger.error(f"账号 {account_id} 健康检查失败: {e}")
            await self._account_manager.update_health_status(
                account_id, HealthStatus.OFFLINE
            )
            return False
        except Exception as e:
            logger.error(f"账号 {account_id} 健康检查异常: {e}")
            await self._account_manager.update_health_status(
                account_id, HealthStatus.OFFLINE
            )
            return False

        return False

    async def start_health_check(self, account_id: str):
        """
        启动账号健康检查循环

        Args:
            account_id: 账号 ID
        """
        # 取消现有任务
        if account_id in self._health_check_tasks:
            self._health_check_tasks[account_id].cancel()

        async def health_check_loop():
            while True:
                try:
                    await self.check_session_health(account_id)
                    await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"健康检查循环异常: {e}")
                    await asyncio.sleep(60)  # 出错后等待1分钟

        task = asyncio.create_task(health_check_loop())
        self._health_check_tasks[account_id] = task

    async def stop_health_check(self, account_id: str):
        """停止账号健康检查"""
        if account_id in self._health_check_tasks:
            self._health_check_tasks[account_id].cancel()
            del self._health_check_tasks[account_id]

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
        # 获取账号信息
        account = await self._account_manager.get_account(account_id)
        if not account or not account.user_id:
            return

        # 格式化等待时间
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60

        if hours > 0:
            time_str = f"{hours}小时{minutes}分钟"
        else:
            time_str = f"{minutes}分钟"

        # 构造消息
        if is_banned:
            message = (
                f"⚠️ <b>账号已被限制</b>\n\n"
                f"账号：@{account.username or account.account_id}\n"
                f"限制时长：{time_str}\n"
                f"解除时间：{account.flood_until.strftime('%Y-%m-%d %H:%M')}\n\n"
                f"系统将自动检测并在解除后恢复账号。"
            )
        else:
            message = (
                f"⏳ <b>账号触发速率限制</b>\n\n"
                f"账号：@{account.username or account.account_id}\n"
                f"等待时长：{time_str}\n\n"
                f"系统将自动等待后重试。"
            )

        # 发送通知到 Bot
        await self._send_notification(account.user_id, message)

    async def _notify_session_invalid(self, account_id: str):
        """
        通知用户 Session 失效

        Args:
            account_id: 账号 ID
        """
        account = await self._account_manager.get_account(account_id)
        if not account or not account.user_id:
            return

        message = (
            f"❌ <b>账号会话已失效</b>\n\n"
            f"账号：@{account.username or account.account_id}\n\n"
            f"可能原因：\n"
            f"• 您在手机端登出了账号\n"
            f"• Session 已过期\n\n"
            f"请重新扫码登录该账号。"
        )

        await self._send_notification(account.user_id, message)

    async def _notify_account_recovered(self, account_id: str):
        """
        通知用户账号已恢复

        Args:
            account_id: 账号 ID
        """
        account = await self._account_manager.get_account(account_id)
        if not account or not account.user_id:
            return

        message = (
            f"✅ <b>账号已恢复</b>\n\n"
            f"账号：@{account.username or account.account_id}\n\n"
            f"FloodWait 限制已解除，账号可以正常使用。"
        )

        await self._send_notification(account.user_id, message)

    async def _send_notification(self, user_id: int, message: str):
        """
        发送通知给用户

        Args:
            user_id: 用户 ID
            message: 消息内容
        """
        try:
            from bot.client import bot_client

            await bot_client.send_message(
                user_id,
                message,
                parse_mode='html'
            )
        except Exception as e:
            logger.error(f"发送通知失败: {e}")

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
                raise FloodWaitError(request=None, seconds=int(remaining))
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
