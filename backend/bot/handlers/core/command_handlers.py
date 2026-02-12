"""Command handlers and command dispatch for Telegram bot."""
from __future__ import annotations

from typing import Optional
import re

from loguru import logger
from telethon import Button

from backend.bot.state.fsm import fsm_storage
from backend.bot.handlers.core.auth_gate import require_db_user_id
from backend.bot.handlers.core.helpers import build_login_buttons as _build_login_buttons
from backend.bot.handlers.task.management import show_task_list
from backend.bot.handlers.task.queries import resolve_db_user_id as _resolve_db_user_id
from backend.bot.handlers.account.management import (
    bind_account,
    show_accounts_list,
    show_proxy_management,
    sync_account_resources,
)
from backend.database.runtime.session import get_async_session


async def handle_start_command(event):
    """Handle /start command."""
    actor_user_id = event.sender_id
    fsm_storage.reset_state(actor_user_id)

    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, actor_user_id)

    from backend.bot.account.manager import get_account_manager

    account_manager = get_account_manager()
    accounts = await account_manager.get_accounts(db_user_id, is_active=False) if db_user_id else []

    if not accounts:
        text = """👋 欢迎使用 **定时消息推送管理系统**！

⚠️ **需要先登录 Userbot**

Userbot 负责实际发送消息到群组/频道。请先完成登录：

**登录步骤：**
1. 点击下方「🔐 扫码登录」按钮
2. 在打开的页面中使用 Telegram 扫描二维码
3. 登录成功后返回 Bot 即可

💡 Userbot 登录一次即可长期使用，无需重复登录。
"""
        keyboard = _build_login_buttons("🔐 扫码登录")
        await event.respond(text, buttons=keyboard, parse_mode="markdown")
        return

    text = """👋 欢迎使用 **定时消息推送管理系统**！

本系统可以帮助你在 Telegram 群组/频道中自动发送定时消息。

**主要功能：**
• 📢 定时推送消息（支持文本、媒体、按钮）
• ⏰ 灵活的时间控制（重复间隔、时段限制、起止日期）
• 🗑️ 自动删除上一条消息
• 📌 自动置顶新消息
• 🌐 H5 控制台（高级编辑）

点击下方按钮开始使用：
"""
    await event.respond(text, buttons=[[Button.inline("📢 进入任务列表", data="task_list")]], parse_mode="markdown")


async def handle_bind_command(event):
    """Handle /bind command if current message is /bind; otherwise return silently."""
    try:
        actor_tg_user_id = event.sender_id
        text = (event.raw_text or event.message.message or "")
        normalized = text.replace("／", "/").strip()
        if not normalized:
            return
        if not normalized.lower().startswith("/bind"):
            return

        logger.info(f"收到 /bind 命令: sender={actor_tg_user_id}, text={normalized!r}")

        match = re.match(r"(?i)^/bind(?:@[\w\d_]+)?(?:\s+([0-9]{6}))?(?:\s+.*)?$", normalized)
        if not match:
            await event.respond(
                "📝 **使用方法：**`/bind <6位绑定码>`\n\n"
                "示例：`/bind 123456`",
                parse_mode="markdown",
            )
            return

        bind_code = (match.group(1) or "").strip()
        if not bind_code:
            await event.respond("❌ 请输入 6 位绑定码，例如：`/bind 123456`", parse_mode="markdown")
            return

        bind_user_id = actor_tg_user_id
        async with get_async_session() as session:
            mapped_db_user_id = await _resolve_db_user_id(session, actor_tg_user_id)
            if mapped_db_user_id is not None:
                bind_user_id = int(mapped_db_user_id)

        await bind_account(event, bind_user_id, bind_code, actor_tg_user_id=actor_tg_user_id)
    except Exception as exc:
        logger.exception(f"/bind 处理失败: {type(exc).__name__}: {exc!r}")
        await event.respond("❌ 绑定处理异常，请稍后重试")


def _parse_short_command(raw_text: str) -> tuple[Optional[str], str]:
    text = (raw_text or "").replace("／", "/").strip()
    match = re.match(r"(?i)^/([a-z_]+)(?:@[\w\d_]+)?(?:\s+(.*))?$", text)
    if not match:
        return None, ""
    cmd = (match.group(1) or "").lower()
    args = (match.group(2) or "").strip()
    return cmd, args


async def _run_tasks_command(event, user_id: int, args: str):
    del args
    fsm_storage.reset_state(user_id)
    if await require_db_user_id(event, user_id) is None:
        return
    await show_task_list(event, user_id)


async def _run_accounts_command(event, user_id: int, args: str):
    del args
    if await require_db_user_id(event, user_id) is None:
        return
    await show_accounts_list(event, user_id)


async def _run_sync_command(event, user_id: int, args: str):
    account_id = args.split()[0] if args else None
    if await require_db_user_id(event, user_id) is None:
        return
    await sync_account_resources(event, user_id, account_id)


async def _run_proxy_command(event, user_id: int, args: str):
    del args
    if await require_db_user_id(event, user_id) is None:
        return
    await show_proxy_management(event, user_id)


_SHORT_COMMAND_HANDLERS = {
    "tasks": _run_tasks_command,
    "accounts": _run_accounts_command,
    "sync": _run_sync_command,
    "proxy": _run_proxy_command,
}


async def dispatch_short_command(event):
    """Dispatch /tasks /accounts /sync /proxy commands."""
    user_id = event.sender_id
    cmd, args = _parse_short_command(event.raw_text or event.message.message or "")
    if not cmd:
        return
    handler = _SHORT_COMMAND_HANDLERS.get(cmd)
    if not handler:
        return
    await handler(event, user_id, args)
