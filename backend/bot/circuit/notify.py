"""Notification helpers for circuit breaker."""
from __future__ import annotations

from loguru import logger


async def send_notification(user_id: int, message: str) -> None:
    """Send notification message through manager bot."""
    try:
        from backend.bot.client_runtime.manager import bot_client

        await bot_client.send_message(user_id, message, parse_mode="html")
    except Exception as e:
        logger.error(f"发送通知失败: {e}")


async def notify_flood_wait(account_manager, account_id: str, seconds: int, is_banned: bool) -> None:
    """Notify account owner about FloodWait event."""
    account = await account_manager.get_account(account_id)
    if not account or not account.user_id:
        return

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    time_str = f"{hours}小时{minutes}分钟" if hours > 0 else f"{minutes}分钟"

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
    await send_notification(account.user_id, message)


async def notify_session_invalid(account_manager, account_id: str) -> None:
    """Notify account owner when session becomes invalid."""
    account = await account_manager.get_account(account_id)
    if not account or not account.user_id:
        return

    message = (
        f"❌ <b>账号会话已失效</b>\n\n"
        f"账号：@{account.username or account.account_id}\n\n"
        f"可能原因：\n"
        f"• 您在手机端登出了账号\n"
        f"• Session 已过期\n\n"
        f"请重新在 Bot 中绑定该账号。"
    )
    await send_notification(account.user_id, message)


async def notify_account_recovered(account_manager, account_id: str) -> None:
    """Notify account owner when account is recovered from flood state."""
    account = await account_manager.get_account(account_id)
    if not account or not account.user_id:
        return

    message = (
        f"✅ <b>账号已恢复</b>\n\n"
        f"账号：@{account.username or account.account_id}\n\n"
        f"FloodWait 限制已解除，账号可以正常使用。"
    )
    await send_notification(account.user_id, message)
