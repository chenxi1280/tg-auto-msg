"""Recovery and health-check helpers for circuit breaker."""
from __future__ import annotations

import asyncio
from datetime import datetime

from loguru import logger
from telethon.errors import RPCError, SessionPasswordNeededError

from backend.bot.circuit.notify import (
    notify_account_recovered,
)
from backend.database.models import HealthStatus


def start_recovery_task(breaker, account_id: str, delay_seconds: int) -> None:
    """Start/replace delayed recovery task for account."""
    if account_id in breaker._health_check_tasks:
        breaker._health_check_tasks[account_id].cancel()

    async def recovery_task():
        try:
            await asyncio.sleep(delay_seconds)
            await recover_account(breaker, account_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"恢复任务失败: {e}")

    breaker._health_check_tasks[account_id] = asyncio.create_task(recovery_task())


async def recover_account(breaker, account_id: str) -> None:
    """Recover account after flood wait window expires."""
    logger.info(f"尝试恢复账号: {account_id}")
    account = await breaker._account_manager.get_account(account_id)
    if not account:
        return

    now = datetime.now()
    if account.flood_until and now < account.flood_until:
        remaining = (account.flood_until - now).total_seconds()
        logger.info(f"账号 {account_id} 还需等待 {remaining:.0f} 秒")
        start_recovery_task(breaker, account_id, int(remaining) + 1)
        return

    await breaker._account_manager.update_account(
        account_id,
        is_flooding=False,
        flood_until=None,
    )

    health = await breaker._account_manager.health_check(account_id)
    if health == HealthStatus.ONLINE:
        logger.info(f"账号 {account_id} 已恢复")
        await notify_account_recovered(breaker._account_manager, account_id)
    else:
        logger.warning(f"账号 {account_id} 恢复失败，状态为 {health}")


async def check_session_health(breaker, account_id: str) -> bool:
    """Check if one account session is still valid."""
    client = await breaker._account_manager.get_client(account_id)
    if not client:
        return False

    try:
        me = await client.get_me()
        if me:
            await breaker._account_manager.update_health_status(account_id, HealthStatus.ONLINE)
            return True
    except SessionPasswordNeededError:
        logger.error(f"账号 {account_id} 需要两步验证密码")
        await breaker._account_manager.update_health_status(account_id, HealthStatus.OFFLINE)
        return False
    except RPCError as e:
        logger.error(f"账号 {account_id} 健康检查失败: {e}")
        await breaker._account_manager.update_health_status(account_id, HealthStatus.OFFLINE)
        return False
    except Exception as e:
        logger.error(f"账号 {account_id} 健康检查异常: {e}")
        await breaker._account_manager.update_health_status(account_id, HealthStatus.OFFLINE)
        return False
    return False


async def start_health_check(breaker, account_id: str) -> None:
    """Start periodic health-check loop for account."""
    if account_id in breaker._health_check_tasks:
        breaker._health_check_tasks[account_id].cancel()

    async def health_check_loop():
        while True:
            try:
                await check_session_health(breaker, account_id)
                await asyncio.sleep(breaker.HEALTH_CHECK_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"健康检查循环异常: {e}")
                await asyncio.sleep(60)

    breaker._health_check_tasks[account_id] = asyncio.create_task(health_check_loop())


async def stop_health_check(breaker, account_id: str) -> None:
    """Stop periodic health-check loop for account."""
    if account_id in breaker._health_check_tasks:
        breaker._health_check_tasks[account_id].cancel()
        del breaker._health_check_tasks[account_id]
