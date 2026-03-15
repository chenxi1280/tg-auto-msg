"""Account and proxy management flows for Telegram bot handlers."""
from __future__ import annotations

from typing import Optional
from urllib.parse import quote_plus

from telethon import Button

from backend.bot.handlers.core.helpers import (
    build_login_buttons as _build_login_buttons,
    is_valid_button_url as _is_valid_button_url,
    normalize_h5_base_url as _normalize_h5_base_url,
)
from backend.bot.handlers.core.user_link import (
    get_active_account_id as _get_active_account_id,
    set_active_account_id as _set_active_account_id,
)
from backend.bot.handlers.task.queries import resolve_db_user_id as _resolve_db_user_id
from backend.bot.ui.messages import *
from backend.database.schema.models import Account
from backend.database.runtime.session import get_async_session


async def bind_account(event, user_id: int, bind_code: str, actor_tg_user_id: Optional[int] = None):
    """绑定账号"""
    from backend.bot.account.manager import get_account_manager
    from backend.bot.account.binding_service import BindRateLimitError
    account_manager = get_account_manager()

    # actor_tg_user_id: 实际 Telegram 发送者，用于 AccountManager 校验合法绑定来源
    actor_id = int(actor_tg_user_id or user_id)
    try:
        account = await account_manager.bind_account(
            user_id=user_id,
            bind_code=bind_code,
            ip_address="",
            actor_tg_user_id=actor_id,
        )
    except BindRateLimitError as exc:
        await event.respond(f"⏳ 绑定失败次数过多，请 {exc.retry_after_seconds} 秒后再试")
        return
    except RuntimeError as exc:
        await event.respond(f"⚠️ 绑定失败：{exc}")
        return

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
    from backend.bot.account.manager import get_account_manager
    account_manager = get_account_manager()
    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, user_id)
        active_account_id = (
            await _get_active_account_id(session, user_id, db_user_id)
            if db_user_id is not None
            else None
        )
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
        if not acc.is_active:
            status = "⚪️"
        elif str(acc.health_status) == "online":
            status = "🟢"
        else:
            status = "🟠"
        proxy = f"代理#{acc.proxy_id}" if acc.proxy_id else "无代理"
        flooding = "🚨 Flood" if acc.is_flooding else ""
        current = "⭐ 当前账号" if active_account_id and str(acc.account_id) == str(active_account_id) else ""
        display_name = (
            f"@{acc.username}" if acc.username
            else (acc.phone or f"ID:{acc.tg_user_id}" if acc.tg_user_id else acc.account_id[:8])
        )

        account_lines.append(
            f"{i}. {status} {display_name}\n"
            f"   `{acc.account_id}`\n"
            f"   {proxy} {flooding} {current}"
        )

    text = ACCOUNTS_LIST.format(
        count=len(accounts),
        accounts_text="\n\n".join(account_lines)
    )

    # 按钮
    keyboard = [[Button.inline("🔄 同步全部资源", data="sync_all"), Button.inline("📋 任务列表", data="task_list")]]
    keyboard.append([Button.inline("➕ 新建任务", data="add_task")])

    for idx, acc in enumerate(accounts[:8], 1):
        display = acc.username or acc.phone or (f"ID:{acc.tg_user_id}" if acc.tg_user_id else acc.account_id[:8])
        prefix = "⭐" if active_account_id and str(acc.account_id) == str(active_account_id) else "▫️"
        keyboard.append([Button.inline(f"{prefix} 账号{idx}: {display[:22]}", data=f"acc_menu:{acc.account_id}")])

    keyboard.append(_build_login_buttons("🔐 扫码登录")[0])

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
    from backend.bot.resources.manager import get_resource_manager
    resource_manager = get_resource_manager()
    from backend.bot.account.manager import get_account_manager
    account_manager = get_account_manager()
    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, user_id)
    accounts = await account_manager.get_accounts(db_user_id, is_active=True) if db_user_id else []

    if not accounts:
        await event.respond("⚠️ 没有可用账号，请先绑定账号")
        return

    allowed_account_ids = {acc.account_id for acc in accounts}

    if account_id:
        if account_id not in allowed_account_ids:
            await event.respond("❌ 无权操作该账号，或账号未启用")
            return
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


async def _get_owned_account(user_id: int, account_id: str) -> tuple[Optional[int], Optional[Account]]:
    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, user_id)
        if db_user_id is None:
            return None, None
        result = await session.execute(
            Account.__table__.select().where(
                Account.account_id == account_id,
                Account.user_id == db_user_id,
            )
        )
        row = result.first()
        if not row:
            return db_user_id, None
        account = await session.get(Account, account_id)
        return db_user_id, account


async def show_account_menu(event, user_id: int, account_id: str):
    """显示单账号操作菜单。"""
    db_user_id, account = await _get_owned_account(user_id, account_id)
    if db_user_id is None:
        await event.answer("未找到绑定用户，请先 /bind", alert=True)
        return
    if not account:
        await event.answer("账号不存在或无权限", alert=True)
        return

    status_text = (
        "在线" if str(account.health_status) == "online"
        else ("离线" if str(account.health_status) == "offline" else str(account.health_status))
    )
    text = (
        "🧩 **账号操作**\n\n"
        f"账号: `{account.account_id}`\n"
        f"显示名: @{account.username or '-'}\n"
        f"状态: {status_text}\n"
        f"启用: {'是' if account.is_active else '否'}\n"
        f"已发送: {account.messages_sent}\n\n"
        "你可以设置为当前账号、同步资源、重新登录或解绑。"
    )
    keyboard = [
        [Button.inline("⭐ 设为当前账号", data=f"acc_set_active:{account_id}")],
        [Button.inline("🔄 同步资源", data=f"acc_sync:{account_id}"), Button.inline("➕ 新建任务", data=f"acc_add_task:{account_id}")],
        [Button.inline("♻️ 重新登录", data=f"acc_relogin:{account_id}"), Button.inline("🧷 刷新绑定码", data=f"acc_bindcode:{account_id}")],
        [Button.inline("🗑️ 解绑账号", data=f"acc_unbind:{account_id}")],
        [Button.inline("⬅️ 返回账号列表", data="accounts_list")],
    ]
    if hasattr(event, "edit"):
        await event.edit(text, buttons=keyboard, parse_mode="markdown")
    else:
        await event.respond(text, buttons=keyboard, parse_mode="markdown")


async def set_current_account(event, user_id: int, account_id: str):
    """设置当前账号，供 Bot 快捷操作使用。"""
    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, user_id)
        if db_user_id is None:
            await event.answer("未找到绑定用户，请先 /bind", alert=True)
            return
        account = await session.get(Account, account_id)
        if not account or int(account.user_id) != int(db_user_id):
            await event.answer("账号不存在或无权限", alert=True)
            return
        await _set_active_account_id(session, user_id, db_user_id, account_id)
    await event.answer("已设为当前账号")
    await show_account_menu(event, user_id, account_id)


async def sync_single_account(event, user_id: int, account_id: str):
    """同步单个账号资源。"""
    await sync_account_resources(event, user_id, account_id)


async def relogin_account(event, user_id: int, account_id: str):
    """给出重登入口。"""
    db_user_id, account = await _get_owned_account(user_id, account_id)
    if db_user_id is None or not account:
        await event.answer("账号不存在或无权限", alert=True)
        return

    base = _normalize_h5_base_url() or "http://localhost:8000"
    relogin_url = f"{base}/bind-tg?relogin_account_id={quote_plus(account_id)}"
    if _is_valid_button_url(relogin_url):
        await event.respond(
            "点击下方按钮重新扫码登录该账号：",
            buttons=[[Button.url("♻️ 重新登录该账号", relogin_url)]],
        )
    else:
        await event.respond(
            "当前地址无法作为 Telegram URL 按钮，请在浏览器手动打开：\n"
            f"{relogin_url}"
        )
    await event.answer("已发送重登入口")


async def refresh_bind_code(event, user_id: int, account_id: str):
    """刷新账号绑定码，便于 /bind 快捷操作。"""
    from backend.bot.account.manager import get_account_manager

    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, user_id)
        if db_user_id is None:
            await event.answer("未找到绑定用户，请先 /bind", alert=True)
            return
        account = await session.get(Account, account_id)
        if not account or int(account.user_id) != int(db_user_id):
            await event.answer("账号不存在或无权限", alert=True)
            return

    manager = get_account_manager()
    issued = await manager.issue_bind_code(account_id, refresh=True)
    if not issued:
        await event.answer("绑定码生成失败", alert=True)
        return
    code = issued["bind_code"]
    await event.respond(
        f"✅ 绑定码已刷新：`{code}`\n发送命令：`/bind {code}`",
        parse_mode="markdown",
    )
    await event.answer("绑定码已刷新")


async def confirm_unbind_account(event, user_id: int, account_id: str):
    """解绑前确认。"""
    db_user_id, account = await _get_owned_account(user_id, account_id)
    if db_user_id is None or not account:
        await event.answer("账号不存在或无权限", alert=True)
        return
    text = (
        "⚠️ **确认解绑账号**\n\n"
        f"账号: `{account.account_id}`\n"
        f"显示名: @{account.username or '-'}\n\n"
        "解绑后该账号及相关任务将删除，是否继续？"
    )
    keyboard = [
        [Button.inline("确认解绑", data=f"acc_unbind_confirm:{account_id}")],
        [Button.inline("取消", data=f"acc_menu:{account_id}")],
    ]
    await event.edit(text, buttons=keyboard, parse_mode="markdown")


async def unbind_account(event, user_id: int, account_id: str):
    """执行解绑（删除账号）。"""
    from backend.bot.account.manager import get_account_manager

    async with get_async_session() as session:
        db_user_id = await _resolve_db_user_id(session, user_id)
        if db_user_id is None:
            await event.answer("未找到绑定用户，请先 /bind", alert=True)
            return
        account = await session.get(Account, account_id)
        if not account or int(account.user_id) != int(db_user_id):
            await event.answer("账号不存在或无权限", alert=True)
            return

    manager = get_account_manager()
    ok = await manager.delete_account(account_id)
    if not ok:
        await event.answer("解绑失败，账号不存在", alert=True)
        return
    await event.answer("解绑成功")
    await show_accounts_list(event, user_id)


async def show_proxy_management(event, user_id: int):
    """显示代理管理页面"""
    from backend.bot.proxy.pool import get_proxy_pool
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
