"""Shared helpers for account rebind-required prompts in Telegram bot flows."""
from __future__ import annotations

from typing import Any


REAUTH_REQUIRED_TITLE = "系统已更新，请先重新绑定"
REAUTH_REQUIRED_GUIDE = (
    "点击“重新绑定”或回到主菜单选择“绑定账号”继续。"
    "即使只掉线 1 次，也可能是 Telegram 风控触发。"
    "重新绑定前请确认主要账号日常登录区域与服务器/梯子/代理区域尽量一致且稳定，避免 Telegram 拦截新登录。"
)

_REAUTH_REASON_SET = {
    "session_unauthorized",
}

_REAUTH_KEYWORDS = (
    "系统已更新，请先重新绑定",
    "StringSession 解密失败",
    "需要重新绑定",
    "session_unauthorized",
)


def get_reauth_required_message(*, multiline: bool = True) -> str:
    if multiline:
        return f"{REAUTH_REQUIRED_TITLE}\n{REAUTH_REQUIRED_GUIDE}"
    return REAUTH_REQUIRED_TITLE


def is_reauth_required_reason(reason: str | None) -> bool:
    normalized = str(reason or "").strip().lower()
    return normalized in _REAUTH_REASON_SET


def is_reauth_required_account(account: Any) -> bool:
    if account is None:
        return False
    if bool(getattr(account, "reauth_required", False)):
        return True
    return is_reauth_required_reason(getattr(account, "reauth_reason", None))


def is_reauth_required_error_message(message: str | None) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    return any(keyword in text for keyword in _REAUTH_KEYWORDS)
