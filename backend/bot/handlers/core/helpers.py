"""Shared helper functions for bot handlers."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
import ipaddress
from urllib.parse import urlparse

from telethon import Button

from backend.config.core.settings import settings
from backend.database.schema.models import Resource, ScheduledMessageTask

_LOCAL_BUTTON_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
_SUPPORTED_PEER_TYPES = {"user", "chat", "supergroup", "channel"}
_TARGET_FILTER_TYPES = {"all", "user", "group", "channel"}


def normalize_h5_base_url() -> str:
    """Normalize H5 base URL from settings."""
    base = (settings.h5_base_url or "").strip()
    if not base:
        return ""
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    return base.rstrip("/")


def build_h5_login_url() -> str:
    """Build H5 login URL."""
    base = normalize_h5_base_url()
    return f"{base}/login" if base else ""


def is_valid_button_url(url: str) -> bool:
    """Validate URL for Telegram button."""
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = (parsed.hostname or "").lower()
    if host in _LOCAL_BUTTON_HOSTS:
        return False
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    except ValueError:
        pass
    return True


def build_login_buttons(label: str = "🔐 扫码登录"):
    """Build login button keyboard."""
    login_url = build_h5_login_url()
    if is_valid_button_url(login_url):
        return [[Button.url(label, login_url)]]
    return [[Button.inline("🔐 登录指引", data="show_login_help")]]


def login_help_text() -> str:
    """Build login help text."""
    login_url = build_h5_login_url() or "http://localhost:8000/login"
    return (
        "当前 H5 地址不可作为 Telegram URL 按钮（本地/内网地址）。\n"
        f"请在浏览器手动打开: {login_url}"
    )


def peer_meta(peer_type: str) -> tuple[str, str]:
    """Map peer type to icon and Chinese label."""
    peer_type = str(peer_type or "").lower()
    if peer_type == "user":
        return "👤", "个人"
    if peer_type in {"chat", "supergroup"}:
        return "👥", "群组"
    if peer_type == "channel":
        return "📢", "频道"
    return "💬", peer_type or "未知"


def truncate_text(text: str, max_len: int = 24) -> str:
    """Truncate text with ellipsis."""
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def normalize_target_filter(value: Optional[str]) -> str:
    """Normalize target filter value."""
    filter_value = str(value or "").strip().lower()
    return filter_value if filter_value in _TARGET_FILTER_TYPES else "all"


def target_filter_label(filter_value: str) -> str:
    """Render target filter label."""
    filter_value = normalize_target_filter(filter_value)
    if filter_value == "user":
        return "👤 个人"
    if filter_value == "group":
        return "👥 群聊"
    if filter_value == "channel":
        return "📢 频道"
    return "🌐 全部"


def resource_matches_filter(resource: Resource, peer_filter: str) -> bool:
    """Check if resource matches selected filter."""
    peer_filter = normalize_target_filter(peer_filter)
    peer_type = str(resource.peer_type or "").lower()
    if peer_filter == "all":
        return True
    if peer_filter == "user":
        return peer_type == "user"
    if peer_filter == "group":
        return peer_type in {"chat", "supergroup"}
    if peer_filter == "channel":
        return peer_type == "channel"
    return True


def filter_target_resources(
    resources: list[Resource],
    *,
    peer_filter: str,
    search_query: str,
) -> list[Resource]:
    """Filter resources by type and keyword."""
    peer_filter = normalize_target_filter(peer_filter)
    keyword = (search_query or "").strip().lower()
    normalized_keyword = keyword.lstrip("@")

    filtered: list[Resource] = []
    for resource in resources:
        if not resource_matches_filter(resource, peer_filter):
            continue
        if keyword:
            title = str(resource.title or "").lower()
            username = str(resource.username or "").lower()
            peer_id_str = str(resource.peer_id)
            if (
                keyword not in title
                and keyword not in username
                and normalized_keyword not in username
                and keyword not in peer_id_str
            ):
                continue
        filtered.append(resource)
    return filtered


def escape_markdown(text: str) -> str:
    """Escape markdown-sensitive characters."""
    text = str(text or "")
    return (
        text.replace("\\", "\\\\")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("`", "\\`")
    )


def normalize_task_targets(task: ScheduledMessageTask) -> list[dict[str, Any]]:
    """Normalize task target peers from legacy/new schema."""
    targets: list[dict[str, Any]] = []

    raw_targets = getattr(task, "target_peers", None)
    if isinstance(raw_targets, list):
        for item in raw_targets:
            if not isinstance(item, dict):
                continue
            try:
                peer_id = int(item.get("peer_id"))
            except Exception:
                continue
            peer_type = str(item.get("peer_type") or "").strip().lower()
            if peer_type not in _SUPPORTED_PEER_TYPES:
                continue
            access_hash = item.get("access_hash")
            if access_hash not in (None, ""):
                try:
                    access_hash = int(access_hash)
                except Exception:
                    access_hash = None
            targets.append(
                {
                    "peer_id": peer_id,
                    "peer_type": peer_type,
                    "access_hash": access_hash,
                }
            )

    if not targets:
        raw_peer_id = task.target_peer_id or task.chat_id
        if raw_peer_id:
            peer_type = str(task.target_peer_type or "user").strip().lower()
            if peer_type not in _SUPPORTED_PEER_TYPES:
                peer_type = "user"
            targets.append(
                {
                    "peer_id": int(raw_peer_id),
                    "peer_type": peer_type,
                    "access_hash": task.target_access_hash,
                }
            )

    deduped: list[dict[str, Any]] = []
    seen = set()
    for target in targets:
        key = (target["peer_type"], target["peer_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(target)
    return deduped


def apply_task_targets(task: ScheduledMessageTask, targets: list[dict[str, Any]]) -> None:
    """Apply normalized targets to task fields."""
    task.target_peers = targets if targets else None
    if targets:
        primary = targets[0]
        task.target_peer_id = int(primary["peer_id"])
        task.target_peer_type = str(primary["peer_type"])
        task.target_access_hash = primary.get("access_hash")
        task.chat_id = int(primary["peer_id"])
    else:
        task.target_peer_id = None
        task.target_peer_type = None
        task.target_access_hash = None
        task.chat_id = None


def format_timestamp(ts: Optional[int]) -> str:
    """Format unix timestamp."""
    if ts is None:
        return "未设置"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def format_buttons(buttons) -> str:
    """Format inline button structure for display."""
    if not buttons:
        return "无"
    lines = []
    for row in buttons:
        btn_texts = [btn.get("text", "") for btn in row]
        lines.append(" | ".join(btn_texts))
    return "\n".join(lines)


def parse_buttons(text: str) -> list:
    """Parse multiline button input."""
    buttons = []
    for line in text.strip().split("\n"):
        row = []
        parts = line.split("&&")
        for part in parts:
            part = part.strip()
            if " - " not in part:
                raise ValueError(f"按钮格式错误: {part}")
            btn_text, url = part.split(" - ", 1)
            btn_text = btn_text.strip()
            url = url.strip()
            if not url.startswith("http://") and not url.startswith("https://"):
                url = "https://" + url
            row.append({"text": btn_text, "url": url})
        if row:
            buttons.append(row)

    if len(buttons) > 3:
        raise ValueError("最多支持 3 行按钮")
    for row in buttons:
        if len(row) > 3:
            raise ValueError("每行最多 3 个按钮")
    return buttons


def generate_h5_url(task_id: str) -> str:
    """Generate H5 URL for task page."""
    base = normalize_h5_base_url() or "http://localhost:8000"
    return f"{base}/tasks?task_id={task_id}"
