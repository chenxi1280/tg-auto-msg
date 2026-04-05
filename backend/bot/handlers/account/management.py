"""Account and proxy management flows for Telegram bot handlers."""
from __future__ import annotations

from typing import Optional

from telethon import Button

from backend.bot.handlers.core.user_link import (
    get_active_account_id as _get_active_account_id,
    set_active_account_id as _set_active_account_id,
)
from backend.bot.handlers.task.queries import (
    USER_MODE_ACCOUNT_SCOPED,
    resolve_actor_access_context as _resolve_actor_access_context,
)
from backend.bot.ui.messages import *
from backend.database.schema.models import Account
from backend.database.runtime.session import get_async_session
from backend.h5_backend.services.licensing.service import (
    get_account_authorization_summary,
    list_user_authorizations,
)


async def _send_or_reply(event, text: str, *, buttons=None):
    if hasattr(event, "edit"):
        try:
            await event.edit(text, buttons=buttons, parse_mode="markdown")
            return
        except Exception:
            pass
    await event.respond(text, buttons=buttons, parse_mode="markdown")


async def show_accounts_list(event, user_id: int):
    """显示账号列表"""
    from backend.bot.onboarding import get_onboarding_service
    from backend.bot.account.manager import get_account_manager

    if await get_onboarding_service().ensure_registered_user(event, user_id) is None:
        return

    account_manager = get_account_manager()
    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        db_user_id = access_ctx.system_user_id
        active_account_id = (
            await _get_active_account_id(session, user_id, db_user_id)
            if db_user_id is not None
            else None
        )
    if db_user_id:
        await list_user_authorizations(db_user_id)
    accounts = await account_manager.get_accounts(db_user_id, is_active=True) if db_user_id else []
    if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED and access_ctx.scoped_account_id:
        accounts = [item for item in accounts if str(item.account_id) == str(access_ctx.scoped_account_id)]
    authorization_items = await list_user_authorizations(db_user_id) if db_user_id else []
    current_authorization = authorization_items[0] if authorization_items else None

    if not accounts:
        text = (
            "⚠️ 你还没有可用的 Telegram 账号\n\n"
            f"当前授权：{'已开通' if current_authorization and current_authorization.status == 'active' else '未开通'}\n\n"
            "请先点击下方“绑定账号”，直接在 Bot 内完成 Telegram 手机号绑定。"
        )
        keyboard = [
            [Button.inline("📱 绑定账号", data="bot_login_account")],
            [Button.inline("🧾 查看授权", data="bot_authorization"), Button.inline("🛒 立即购买", data="bot_purchase")],
            [Button.inline("⬅️ 返回主菜单", data="bot_home")],
        ]
        await event.respond(text, buttons=keyboard, parse_mode='markdown')
        return

    # 构建账号列表文本
    account_lines = []
    for i, acc in enumerate(accounts, 1):
        auth_summary = await get_account_authorization_summary(acc.account_id)
        if not acc.is_active:
            status = "⚪️"
        elif str(acc.health_status) == "online":
            status = "🟢"
        else:
            status = "🟠"
        proxy = f"代理#{acc.proxy_id}" if acc.proxy_id else "无代理"
        flooding = "🚨 Flood" if acc.is_flooding else ""
        current = "⭐ 当前账号" if active_account_id and str(acc.account_id) == str(active_account_id) else "备用账号"
        display_name = (
            f"@{acc.username}" if acc.username
            else (acc.phone or f"ID:{acc.tg_user_id}" if acc.tg_user_id else acc.account_id[:8])
        )
        authorization_status = "已开通" if auth_summary.authorization_id else "未开通"
        slot_expiry = (
            f" / 到期 {auth_summary.authorization_end_at.strftime('%Y-%m-%d %H:%M')}"
            if auth_summary.authorization_end_at
            else ""
        )

        account_lines.append(
            f"{i}. {status} {display_name}\n"
            f"   账号ID: `{acc.account_id}`\n"
            f"   代理: {proxy}\n"
            f"   状态: {current} {flooding}\n"
            f"   自动发送: {'已授权' if auth_summary.can_create_tasks else ('已到期' if auth_summary.authorization_status == 'expired' else '未授权')}\n"
            f"   当前授权: {authorization_status}{slot_expiry}"
        )

    auth_expiry_text = ""
    if current_authorization and current_authorization.end_at:
        auth_expiry_text = f" / 到期 {current_authorization.end_at.strftime('%Y-%m-%d %H:%M')}"
    text = (
        f"👥 **账号列表**（{len(accounts)}）\n\n"
        f"当前授权：{current_authorization.status if current_authorization else '未开通'}{auth_expiry_text}\n\n"
        f"{chr(10).join(account_lines)}\n\n"
        "下一步：请选择要查看的账号，或使用下方快捷操作。"
    )

    # 按钮
    if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED:
        keyboard = [[Button.inline("🔄 同步全部资源", data="sync_all")]]
    else:
        keyboard = [[Button.inline("📱 绑定账号", data="bot_login_account"), Button.inline("🔄 同步全部资源", data="sync_all")]]
    keyboard.append([Button.inline("🗂️ 查看任务", data="task_list"), Button.inline("➕ 新建任务", data="add_task")])

    for idx, acc in enumerate(accounts[:8], 1):
        display = acc.username or acc.phone or (f"ID:{acc.tg_user_id}" if acc.tg_user_id else acc.account_id[:8])
        prefix = "⭐" if active_account_id and str(acc.account_id) == str(active_account_id) else "▫️"
        keyboard.append([Button.inline(f"{prefix} 账号{idx}: {display[:22]}", data=f"acc_menu:{acc.account_id}")])

    keyboard.append([Button.inline("🧾 查看授权", data="bot_authorization"), Button.inline("⬅️ 返回主菜单", data="bot_home")])

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
    from backend.bot.onboarding import get_onboarding_service
    from backend.bot.resources.manager import get_resource_manager
    resource_manager = get_resource_manager()
    from backend.bot.account.manager import get_account_manager
    account_manager = get_account_manager()

    if await get_onboarding_service().ensure_registered_user(event, user_id) is None:
        return

    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        db_user_id = access_ctx.system_user_id
    accounts = await account_manager.get_accounts(db_user_id, is_active=True) if db_user_id else []
    if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED and access_ctx.scoped_account_id:
        accounts = [acc for acc in accounts if str(acc.account_id) == str(access_ctx.scoped_account_id)]

    if not accounts:
        await event.respond("⚠️ 当前没有可用账号。\n下一步：请先点击「📱 绑定账号」绑定至少一个 Telegram 账号。")
        return

    allowed_account_ids = {acc.account_id for acc in accounts}

    if account_id:
        if account_id not in allowed_account_ids:
            await event.respond("❌ 该账号不可操作，可能未启用或不属于当前用户。")
            return
        # 同步指定账号
        result = await resource_manager.full_sync(account_id)
        await event.respond(
            f"✅ 同步完成\n"
            f"新增: {result.new}\n"
            f"更新: {result.updated}\n"
            f"失败: {result.failed}\n\n"
            "下一步：可继续查看账号详情或创建任务。"
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
            f"失败: {total_failed}\n\n"
            "下一步：可进入账号详情查看具体账号状态。"
        )


async def _get_owned_account(user_id: int, account_id: str) -> tuple[Optional[int], Optional[Account]]:
    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        db_user_id = access_ctx.system_user_id
        if db_user_id is None:
            return None, None
        if (
            access_ctx.mode == USER_MODE_ACCOUNT_SCOPED
            and access_ctx.scoped_account_id
            and str(account_id) != str(access_ctx.scoped_account_id)
        ):
            return db_user_id, None
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
        await event.answer("当前 Telegram 账号还未绑定系统账号，请先发送 /start，或回到 Web 首页点击“系统账号绑定到 TG Bot”。", alert=True)
        return
    if not account:
        await event.answer("账号不存在或无权限", alert=True)
        return

    async with get_async_session() as session:
        active_account_id = await _get_active_account_id(session, user_id, db_user_id)
    auth_summary = await get_account_authorization_summary(account.account_id)
    auth_text = "已授权" if auth_summary.can_create_tasks else ("已到期" if auth_summary.authorization_status == "expired" else "未授权")

    status_text = (
        "在线" if str(account.health_status) == "online"
        else ("离线" if str(account.health_status) == "offline" else str(account.health_status))
    )
    text = (
        "👤 **账号详情**\n\n"
        f"显示名：{('@' + account.username) if account.username else (account.phone or str(account.tg_user_id or '-'))}\n"
        f"状态：{status_text}\n"
        f"当前账号：{'是' if str(active_account_id or '') == str(account.account_id) else '否'}\n"
        f"已发送：{account.messages_sent}\n"
        f"自动发送：{auth_text}\n"
        f"到期时间：{auth_summary.authorization_end_at.strftime('%Y-%m-%d %H:%M') if auth_summary.authorization_end_at else '-'}\n"
        f"账号ID：`{account.account_id}`\n\n"
        "下一步：请选择下方操作继续管理该账号。"
    )
    keyboard = [
        [Button.inline("⚙️ 设为当前账号", data=f"acc_set_active:{account_id}")],
        [Button.inline("🔄 同步资源", data=f"acc_sync:{account_id}"), Button.inline("📱 重新绑定", data=f"acc_relogin:{account_id}")],
        [Button.inline("➕ 新建任务", data=f"acc_add_task:{account_id}"), Button.inline("⏳ 续费卡密", data=f"acc_renew_authorization:{account_id}")],
        [Button.inline("解绑账号", data=f"acc_unbind:{account_id}")],
        [Button.inline("⬅️ 返回账号页", data="accounts_list"), Button.inline("🏠 返回主菜单", data="bot_home")],
    ]
    if hasattr(event, "edit"):
        await event.edit(text, buttons=keyboard, parse_mode="markdown")
    else:
        await event.respond(text, buttons=keyboard, parse_mode="markdown")


async def set_current_account(event, user_id: int, account_id: str):
    """设置当前账号，供 Bot 快捷操作使用。"""
    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        db_user_id = access_ctx.system_user_id
        if db_user_id is None:
            await event.answer("当前 Telegram 账号还未绑定系统账号，请先发送 /start，或回到 Web 首页点击“系统账号绑定到 TG Bot”。", alert=True)
            return
        if (
            access_ctx.mode == USER_MODE_ACCOUNT_SCOPED
            and access_ctx.scoped_account_id
            and str(account_id) != str(access_ctx.scoped_account_id)
        ):
            await event.answer("受限模式下仅可操作自己的账号。", alert=True)
            return
        account = await session.get(Account, account_id)
        if not account or int(account.user_id) != int(db_user_id):
            await event.answer("账号不存在或无权限", alert=True)
            return
        await _set_active_account_id(session, user_id, db_user_id, account_id)
    await event.answer("✅ 已设为当前账号")
    await show_account_menu(event, user_id, account_id)


async def sync_single_account(event, user_id: int, account_id: str):
    """同步单个账号资源。"""
    await sync_account_resources(event, user_id, account_id)


async def relogin_account(event, user_id: int, account_id: str):
    """给出重新绑定入口。"""
    db_user_id, account = await _get_owned_account(user_id, account_id)
    if db_user_id is None or not account:
        await event.answer("账号不存在或无权限", alert=True)
        return
    from backend.bot.onboarding import get_onboarding_service

    await event.answer("已进入重新绑定流程，请查看最新消息。")
    await get_onboarding_service().start_account_login(
        event,
        user_id,
        existing_tg_user_id=int(account.tg_user_id) if account.tg_user_id else None,
    )


async def renew_account_authorization(event, user_id: int, account_id: str):
    db_user_id, account = await _get_owned_account(user_id, account_id)
    if db_user_id is None:
        await event.answer("当前 Telegram 账号还未绑定系统账号，请先发送 /start，或回到 Web 首页点击“系统账号绑定到 TG Bot”。", alert=True)
        return
    if not account:
        await event.answer("账号不存在或无权限", alert=True)
        return
    from backend.bot.onboarding import get_onboarding_service

    auth_summary = await get_account_authorization_summary(account.account_id)
    if not auth_summary.authorization_id:
        await event.answer("该账号当前没有可续费的授权，请先绑定 TG 账号触发 7 天试用，或在 H5 中输入卡密开通当前授权。", alert=True)
        return
    await event.answer("请输入新的续费卡密")
    await get_onboarding_service().start_activation(event, user_id)


async def confirm_unbind_account(event, user_id: int, account_id: str):
    """解绑前确认。"""
    db_user_id, account = await _get_owned_account(user_id, account_id)
    if db_user_id is None or not account:
        await event.answer("账号不存在或无权限", alert=True)
        return
    text = (
        "⚠️ **确认解绑账号**\n\n"
        f"显示名：{('@' + account.username) if account.username else (account.phone or str(account.tg_user_id or '-'))}\n"
        f"账号ID：`{account.account_id}`\n\n"
        "解绑后该账号及相关任务将删除，是否继续？"
    )
    keyboard = [
        [Button.inline("确认解绑", data=f"acc_unbind_confirm:{account_id}")],
        [Button.inline("⬅️ 返回账号详情", data=f"acc_menu:{account_id}"), Button.inline("🏠 返回主菜单", data="bot_home")],
    ]
    await event.edit(text, buttons=keyboard, parse_mode="markdown")


async def unbind_account(event, user_id: int, account_id: str):
    """执行解绑（删除账号）。"""
    from backend.bot.account.manager import get_account_manager

    async with get_async_session() as session:
        access_ctx = await _resolve_actor_access_context(session, user_id)
        db_user_id = access_ctx.system_user_id
        if db_user_id is None:
            await event.answer("当前 Telegram 账号还未绑定系统账号，请先发送 /start，或回到 Web 首页点击“系统账号绑定到 TG Bot”。", alert=True)
            return
        if (
            access_ctx.mode == USER_MODE_ACCOUNT_SCOPED
            and access_ctx.scoped_account_id
            and str(account_id) != str(access_ctx.scoped_account_id)
        ):
            await event.answer("受限模式下仅可解绑自己的账号。", alert=True)
            return
        account = await session.get(Account, account_id)
        if not account or int(account.user_id) != int(db_user_id):
            await event.answer("账号不存在或无权限", alert=True)
            return

    manager = get_account_manager()
    ok = await manager.delete_account(account_id)
    if not ok:
        await event.answer("解绑失败，账号不存在或已被删除。", alert=True)
        return
    await event.answer("✅ 解绑成功")
    await show_accounts_list(event, user_id)


async def show_proxy_management(event, user_id: int):
    """显示代理管理页面"""
    from backend.bot.proxy.pool import get_proxy_pool
    proxy_pool = get_proxy_pool()

    proxies = await proxy_pool.get_all_proxies()

    if not proxies:
        text = "🌐 **代理管理**\n\n暂无代理配置"
        keyboard = [[Button.inline("📋 返回任务页", data="task_list")]]
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

        keyboard = [[Button.inline("🗂️ 查看任务", data="task_list")]]

    await event.respond(text, buttons=keyboard, parse_mode='markdown')
