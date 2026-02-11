"""Account and proxy management flows for Telegram bot handlers."""
from __future__ import annotations

from typing import Optional

from telethon import Button

from backend.bot.handlers.helpers import build_login_buttons as _build_login_buttons
from backend.bot.handlers.task_queries import resolve_db_user_id as _resolve_db_user_id
from backend.bot.messages import *
from backend.database.session import get_async_session


async def bind_account(event, user_id: int, bind_code: str, actor_tg_user_id: Optional[int] = None):
    """绑定账号"""
    from backend.bot.account_manager import get_account_manager
    account_manager = get_account_manager()

    # actor_tg_user_id: 实际 Telegram 发送者，用于 AccountManager 校验合法绑定来源
    actor_id = int(actor_tg_user_id or user_id)
    account = await account_manager.bind_account(
        user_id=actor_id,
        bind_code=bind_code,
        ip_address="telegram_bot"
    )

    if account:
        text = BIND_SUCCESS.format(
            username=account.username or "Unknown",
            account_id=account.account_id
        )
        await event.respond(text, parse_mode='markdown')
        await show_accounts_list(event, user_id)
    else:
        await event.respond(ERROR_INVALID_BIND_CODE)


async def show_accounts_list(event, user_id: int):
    """显示账号列表"""
    from backend.bot.account_manager import get_account_manager
    account_manager = get_account_manager()
    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, user_id)
    accounts = await account_manager.get_accounts(db_user_id, is_active=False) if db_user_id else []

    if not accounts:
        text = (
            "⚠️ 你还没有绑定任何账号\n\n"
            "请先在 H5 页面扫码登录并绑定，然后再使用 Bot 快捷操作。"
        )
        keyboard = _build_login_buttons("🔐 扫码登录")
        await event.respond(text, buttons=keyboard, parse_mode='markdown')
        return

    # 构建账号列表文本
    account_lines = []
    for i, acc in enumerate(accounts, 1):
        status = "🟢" if acc.is_active else "🔴"
        proxy = f"代理#{acc.proxy_id}" if acc.proxy_id else "无代理"
        flooding = "🚨 Flood" if acc.is_flooding else ""
        display_name = (
            f"@{acc.username}" if acc.username
            else (acc.phone or f"ID:{acc.tg_user_id}" if acc.tg_user_id else acc.account_id[:8])
        )

        account_lines.append(
            f"{i}. {status} {display_name}\n"
            f"   `{acc.account_id}`\n"
            f"   {proxy} {flooding}"
        )

    text = ACCOUNTS_LIST.format(
        count=len(accounts),
        accounts_text="\n\n".join(account_lines)
    )

    # 按钮
    keyboard = [
        [Button.inline("🔄 同步全部资源", data="sync_all")],
        [Button.inline("📋 任务列表", data="task_list")],
        _build_login_buttons("🔐 扫码登录")[0],
    ]

    # 避免 callback 编辑失败（同内容触发 MessageNotModified）
    if hasattr(event, "edit"):
        try:
            await event.edit(text, buttons=keyboard, parse_mode='markdown')
            return
        except Exception:
            pass
    await event.respond(text, buttons=keyboard, parse_mode='markdown')


async def sync_account_resources(event, user_id: int, account_id: Optional[str]):
    """同步账号资源（群组/频道）"""
    from backend.bot.resource_manager import get_resource_manager
    resource_manager = get_resource_manager()
    from backend.bot.account_manager import get_account_manager
    account_manager = get_account_manager()
    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, user_id)
    accounts = await account_manager.get_accounts(db_user_id, is_active=True) if db_user_id else []

    if not accounts:
        await event.respond("⚠️ 没有可用账号，请先绑定账号")
        return

    if account_id:
        # 同步指定账号
        result = await resource_manager.full_sync(account_id)
        await event.respond(
            f"✅ 同步完成\n"
            f"新增: {result.new}\n"
            f"更新: {result.updated}\n"
            f"失败: {result.failed}"
        )
    else:
        # 同步所有账号
        total_new = 0
        total_updated = 0
        total_failed = 0

        for acc in accounts:
            result = await resource_manager.full_sync(acc.account_id)
            total_new += result.new
            total_updated += result.updated
            total_failed += result.failed

        await event.respond(
            f"✅ 全部同步完成\n"
            f"账号数: {len(accounts)}\n"
            f"新增: {total_new}\n"
            f"更新: {total_updated}\n"
            f"失败: {total_failed}"
        )


async def show_proxy_management(event, user_id: int):
    """显示代理管理页面"""
    from backend.bot.proxy_pool import get_proxy_pool
    proxy_pool = get_proxy_pool()

    proxies = await proxy_pool.get_all_proxies()

    if not proxies:
        text = "🌐 **代理管理**\n\n暂无代理配置"
        keyboard = [[Button.inline("📋 返回任务列表", data="task_list")]]
    else:
        proxy_lines = []
        for p in proxies[:10]:  # 最多显示10个
            status = "🟢" if p.is_healthy else "🔴"
            assigned = f"→ {p.assigned_account_id[:8]}" if p.assigned_account_id else ""
            proxy_lines.append(
                f"{status} `{p.proxy_id}` {p.proxy_type}://{p.host}:{p.port} {assigned}\n"
                f"使用次数: {p.usage_count}"
            )

        proxies_text = "\n\n".join(proxy_lines)
        text = f"""🌐 **代理管理** ({len(proxies)})

{proxies_text}

💡 提示：
• 健康代理会自动分配给新绑定的账号
• 系统会定期检查代理健康状态"""

        keyboard = [[Button.inline("📋 进入任务列表", data="task_list")]]

    await event.respond(text, buttons=keyboard, parse_mode='markdown')
