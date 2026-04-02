"""Shared auth/ownership gate for bot handlers."""
from __future__ import annotations

from typing import Optional

from telethon import Button

from backend.bot.handlers.task.queries import resolve_db_user_id as _resolve_db_user_id
from backend.database.runtime.session import get_async_session


async def require_db_user_id(event, actor_user_id: int, *, alert: bool = False) -> Optional[int]:
    """Resolve and validate mapped system user ID for current Telegram actor."""
    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, actor_user_id)

    if db_user_id is not None:
        return db_user_id

    msg = (
        "当前 Telegram 账号还未绑定系统账号。\n"
        "请先发送 /start，或回到 Web 首页点击“系统账号绑定到 TG Bot”完成绑定。"
    )
    if alert and hasattr(event, "answer"):
        await event.answer(msg, alert=True)
    else:
        await event.respond(
            "⚠️ 当前 Telegram 账号还未绑定系统账号。\n\n"
            "请先发送 `/start`，或回到 Web 首页点击“系统账号绑定到 TG Bot”完成绑定。",
            parse_mode="markdown",
            buttons=[[Button.inline("🚀 开始使用", data="bot_home")]],
        )
    return None
