"""Shared auth/ownership gate for bot handlers."""
from __future__ import annotations

from typing import Optional

from backend.bot.handlers.core.helpers import build_login_buttons as _build_login_buttons
from backend.bot.handlers.task.queries import resolve_db_user_id as _resolve_db_user_id
from backend.database.runtime.session import get_async_session


async def require_db_user_id(event, actor_user_id: int, *, alert: bool = False) -> Optional[int]:
    """Resolve and validate mapped system user ID for current Telegram actor."""
    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, actor_user_id)

    if db_user_id is not None:
        return db_user_id

    msg = (
        "当前 Telegram 账号还未绑定系统用户。\n"
        "请先打开 H5 完成系统登录与扫码绑定，再发送 /bind <绑定码>。"
    )
    if alert and hasattr(event, "answer"):
        await event.answer(msg, alert=True)
    else:
        await event.respond(
            "⚠️ 当前 Telegram 账号还未绑定系统用户。\n\n"
            "请先在 H5 登录并扫码绑定，然后发送 `/bind <绑定码>`。",
            parse_mode="markdown",
            buttons=_build_login_buttons("🔐 前往 H5 登录"),
        )
    return None
