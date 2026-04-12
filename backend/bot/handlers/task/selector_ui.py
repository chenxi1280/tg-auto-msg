"""UI builders for task account/target picker."""
from __future__ import annotations

from typing import Optional

from telethon import Button

from backend.database.schema.models import Account, Resource
from backend.bot.handlers.core.helpers import normalize_target_filter, peer_meta, truncate_text

TARGET_PAGE_SIZE = 8


def build_account_picker_keyboard(
    *,
    task_id: str,
    accounts: list[Account],
    current_account_id: Optional[str],
    back_callback: Optional[str] = None,
) -> list:
    """Build account picker keyboard."""
    buttons = []
    for account in accounts:
        checked = "✅" if account.account_id == current_account_id else "▫️"
        display_name = (
            f"@{account.username}"
            if account.username
            else (account.phone or account.account_id[:8])
        )
        label = f"{checked} {truncate_text(display_name, 24)}"
        buttons.append([Button.inline(label, data=f"pick_acc:{account.account_id}")])

    buttons.append([
        Button.inline("⬅️ 返回上一页", data=back_callback or f"settings:{task_id}"),
        Button.inline("🏠 返回主菜单", data="bot_home"),
    ])
    return buttons


def build_target_picker_keyboard(
    *,
    task_id: str,
    resources: list[Resource],
    selected_keys: set[tuple[str, int]],
    page: int,
    peer_filter: str,
    search_query: str,
    back_callback: Optional[str] = None,
    done_label: Optional[str] = None,
) -> tuple[list, int, int]:
    """Build target picker keyboard with type filter/search/page controls."""
    total_pages = max(1, (len(resources) + TARGET_PAGE_SIZE - 1) // TARGET_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * TARGET_PAGE_SIZE
    end = start + TARGET_PAGE_SIZE
    page_items = resources[start:end]

    buttons = []
    peer_filter = normalize_target_filter(peer_filter)

    filter_row = []
    filter_items = [
        ("all", "🌐 全部"),
        ("user", "👤 个人"),
        ("group", "👥 群聊"),
        ("channel", "📢 频道"),
    ]
    for value, label in filter_items:
        prefix = "✅" if peer_filter == value else "▫️"
        filter_row.append(Button.inline(f"{prefix}{label}", data=f"pick_type:{value}"))
    buttons.append(filter_row)

    if (search_query or "").strip():
        preview = truncate_text((search_query or "").strip(), 14)
        buttons.append(
            [
                Button.inline(f"🔎 {preview}", data="pick_noop"),
                Button.inline("🔄 清空搜索", data="pick_search_clear"),
                Button.inline("🔎 重新搜索", data="pick_search"),
            ]
        )
    else:
        buttons.append([Button.inline("🔎 输入搜索", data="pick_search")])

    for resource in page_items:
        key = (str(resource.peer_type), int(resource.peer_id))
        checked = "✅" if key in selected_keys else "▫️"
        icon, _ = peer_meta(resource.peer_type)
        display_name = (
            (resource.title or "").strip()
            or (f"@{resource.username}" if resource.username else f"未命名{resource.peer_type or '目标'}")
        )
        label = f"{checked} {icon} {truncate_text(display_name, 18)}"
        buttons.append([Button.inline(label, data=f"pick_res:{resource.resource_id}")])

    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(Button.inline("⬅️ 上一页", data=f"pick_page:{page - 1}"))
        nav_row.append(Button.inline(f"📄 {page + 1}/{total_pages}", data="pick_noop"))
        if page < total_pages - 1:
            nav_row.append(Button.inline("下一页 ➡️", data=f"pick_page:{page + 1}"))
        buttons.append(nav_row)

    buttons.append(
        [
            Button.inline(done_label or f"✅ 完成 ({len(selected_keys)})", data="pick_done"),
            Button.inline("🔄 清空目标", data="pick_clear"),
        ]
    )
    buttons.append([
        Button.inline("⬅️ 返回上一页", data=back_callback or f"settings:{task_id}"),
        Button.inline("🏠 返回主菜单", data="bot_home"),
    ])
    return buttons, page, total_pages
