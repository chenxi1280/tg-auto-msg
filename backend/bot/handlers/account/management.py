"""Account and proxy management flows for Telegram bot handlers."""
from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy import select
from telethon import Button

from backend.bot.account.reauth import (
    get_reauth_required_message,
    is_reauth_required_account,
)
from backend.bot.account.proxy_observation import (
    SING_BOX_PROXY_REGIONS,
    select_reauth_proxy_for_account,
)
from backend.bot.account.client_runtime import close_client
from backend.bot.handlers.core.user_link import (
    get_active_account_id as _get_active_account_id,
    normalize_operator_account_refs as _normalize_operator_account_refs,
    set_active_account_id as _set_active_account_id,
)
from backend.bot.handlers.task.queries import (
    USER_MODE_ACCOUNT_SCOPED,
    resolve_actor_access_context as _resolve_actor_access_context,
)
from backend.bot.ui.messages import *
from backend.database.schema.models import Account, Proxy
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


def _authorization_status_label(status: Optional[str]) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "active":
        return "已开通"
    if normalized == "expired":
        return "已到期"
    return "未开通"


def _account_authorization_status_label(status: Optional[str], *, authorization_id: Optional[str]) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "licensed":
        return "已开通"
    if normalized == "expired":
        return "已到期"
    return "已开通" if authorization_id else "未开通"


async def show_accounts_list(event, user_id: int):
    """显示账号列表"""
    from backend.bot.onboarding import get_onboarding_service
    from backend.bot.account.manager import get_account_manager

    if await get_onboarding_service().ensure_registered_user(event, user_id) is None:
        return

    account_manager = get_account_manager()
    db_user_id = None
    active_account_id = None
    current_authorization = None
    try:
        async with get_async_session() as session:
            access_ctx = await _resolve_actor_access_context(session, user_id)
            db_user_id = access_ctx.system_user_id

        authorization_items = await list_user_authorizations(db_user_id) if db_user_id else []
        current_authorization = authorization_items[0] if authorization_items else None
        accounts = await account_manager.get_accounts(db_user_id, is_active=True) if db_user_id else []
        if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED and access_ctx.scoped_account_id:
            accounts = [item for item in accounts if str(item.account_id) == str(access_ctx.scoped_account_id)]

        preferred_account_id = None
        if current_authorization and current_authorization.account_id:
            preferred_account_id = str(current_authorization.account_id)
        elif len(accounts) == 1:
            preferred_account_id = str(accounts[0].account_id)

        if db_user_id is not None:
            async with get_async_session() as session:
                ref_state = await _normalize_operator_account_refs(
                    session,
                    user_id,
                    db_user_id,
                    valid_account_ids=[str(item.account_id) for item in accounts],
                    preferred_account_id=preferred_account_id,
                )
                active_account_id = ref_state.get("active_account_id")
                if ref_state.get("active_changed") or ref_state.get("scoped_changed") or ref_state.get("mode_changed"):
                    logger.info(
                        "bot account refs repaired before list render: tg_user_id={}, system_user_id={}, active_account_id={}, scoped_account_id={}, mode={}",
                        int(user_id),
                        int(db_user_id),
                        active_account_id,
                        ref_state.get("scoped_account_id"),
                        ref_state.get("mode"),
                    )

        if not active_account_id and len(accounts) == 1:
            active_account_id = str(accounts[0].account_id)

        if not accounts:
            text = (
                "⚠️ 你还没有可用的 Telegram 账号\n\n"
                f"当前授权：{_authorization_status_label(current_authorization.status if current_authorization else None)}\n\n"
                "请先点击下方“绑定账号”，直接在 Bot 内完成 Telegram 手机号绑定。"
            )
            keyboard = [
                [Button.inline("📱 绑定账号", data="bot_login_account")],
                [Button.inline("🧾 查看授权", data="bot_authorization"), Button.inline("🛒 立即购买", data="bot_purchase")],
                [Button.inline("⬅️ 返回主菜单", data="bot_home")],
            ]
            await event.respond(text, buttons=keyboard, parse_mode='markdown')
            return

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
            current = "⭐ 当前账号" if str(acc.account_id) == str(active_account_id or "") else "备用账号"
            if is_reauth_required_account(acc):
                current = f"{current}（需要重新绑定）"
            display_name = (
                f"@{acc.username}" if acc.username
                else (acc.phone or "未命名账号")
            )
            authorization_status = _account_authorization_status_label(
                auth_summary.authorization_status,
                authorization_id=auth_summary.authorization_id,
            )
            slot_expiry = (
                f" / 到期 {auth_summary.authorization_end_at.strftime('%Y-%m-%d %H:%M')}"
                if auth_summary.authorization_end_at
                else ""
            )

            account_lines.append(
                f"{i}. {status} {display_name}\n"
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
            f"当前授权：{_authorization_status_label(current_authorization.status if current_authorization else None)}{auth_expiry_text}\n\n"
            f"{chr(10).join(account_lines)}\n\n"
            "下一步：请选择要查看的账号，或使用下方快捷操作。"
        )

        if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED:
            keyboard = [[Button.inline("🔄 同步全部资源", data="sync_all")]]
        else:
            keyboard = [[Button.inline("📱 绑定账号", data="bot_login_account"), Button.inline("🔄 同步全部资源", data="sync_all")]]
        keyboard.append([Button.inline("🗂️ 查看任务", data="task_list")])
        keyboard.append([Button.inline("⏰ 创建定时任务", data="add_scheduled_task"), Button.inline("🖱️ 创建手动任务", data="add_manual_task")])

        for idx, acc in enumerate(accounts[:8], 1):
            display = acc.username or acc.phone or "未命名账号"
            prefix = "⭐" if str(acc.account_id) == str(active_account_id or "") else "▫️"
            keyboard.append([Button.inline(f"{prefix} 账号{idx}: {display[:22]}", data=f"acc_menu:{acc.account_id}")])

        keyboard.append([Button.inline("🧾 查看授权", data="bot_authorization"), Button.inline("⬅️ 返回主菜单", data="bot_home")])

        if hasattr(event, "edit"):
            try:
                await event.edit(text, buttons=keyboard, parse_mode='markdown')
                return
            except Exception:
                pass
        await event.respond(text, buttons=keyboard, parse_mode='markdown')
    except Exception:
        logger.exception(
            "bot account list render failed: tg_user_id={}, system_user_id={}, active_account_id={}, authorization_id={}",
            int(user_id),
            int(db_user_id) if db_user_id is not None else None,
            active_account_id,
            str(current_authorization.authorization_id) if current_authorization is not None else None,
        )
        raise


async def sync_account_resources(event, user_id: int, account_id: Optional[str]):
    """同步账号资源（群组/频道）"""
    from backend.bot.onboarding import get_onboarding_service
    from backend.bot.account.manager import get_account_manager
    from backend.h5_backend.services.account.auto_sync import (
        SYNC_TRIGGER_MANUAL,
        account_auto_sync_runtime,
    )

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
    reauth_account_ids = {str(acc.account_id) for acc in accounts if is_reauth_required_account(acc)}

    if account_id:
        if account_id not in allowed_account_ids:
            await event.respond("❌ 该账号不可操作，可能未启用或不属于当前用户。")
            return
        if str(account_id) in reauth_account_ids:
            await event.respond(get_reauth_required_message())
            return
        queue_result = await account_auto_sync_runtime.enqueue_account(
            account_id,
            trigger_source=SYNC_TRIGGER_MANUAL,
            user_id=int(db_user_id),
        )
        if queue_result["status"] in {"queued", "running"}:
            await event.respond("⏳ 该账号正在同步中，请稍后查看账号详情。")
            return
        await event.respond("✅ 该账号已加入同步队列\n\n下一步：系统会自动同步账号资料和资源。")
    else:
        queued_accounts = 0
        already_running_accounts = 0
        skipped_reauth_accounts = 0
        for acc in accounts:
            if str(acc.account_id) in reauth_account_ids:
                skipped_reauth_accounts += 1
                continue
            queue_result = await account_auto_sync_runtime.enqueue_account(
                acc.account_id,
                trigger_source=SYNC_TRIGGER_MANUAL,
                user_id=int(db_user_id),
            )
            if queue_result["status"] == "enqueued":
                queued_accounts += 1
            elif queue_result["status"] in {"queued", "running"}:
                already_running_accounts += 1

        if queued_accounts == 0 and already_running_accounts == 0 and skipped_reauth_accounts > 0:
            await event.respond(get_reauth_required_message())
            return
        skipped_text = f"\n需重绑: {skipped_reauth_accounts}" if skipped_reauth_accounts > 0 else ""
        await event.respond(
            f"✅ 同步队列已更新\n"
            f"账号数: {len(accounts)}\n"
            f"新增排队: {queued_accounts}\n"
            f"同步中: {already_running_accounts}{skipped_text}\n\n"
            "下一步：系统会依次自动同步这些账号。"
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
        active_account_ids = (
            await session.execute(
                select(Account.account_id)
                .where(
                    Account.user_id == int(db_user_id),
                    Account.is_active == True,
                )
                .order_by(Account.updated_at.desc(), Account.last_used_at.desc(), Account.created_at.desc())
            )
        ).scalars().all()
        ref_state = await _normalize_operator_account_refs(
            session,
            user_id,
            db_user_id,
            valid_account_ids=[str(item) for item in active_account_ids],
            preferred_account_id=str(active_account_ids[0]) if len(active_account_ids) == 1 else None,
        )
        active_account_id = ref_state.get("active_account_id") or await _get_active_account_id(session, user_id, db_user_id)
    auth_summary = await get_account_authorization_summary(account.account_id)
    auth_text = "已授权" if auth_summary.can_create_tasks else ("已到期" if auth_summary.authorization_status == "expired" else "未授权")

    status_text = (
        "在线" if str(account.health_status) == "online"
        else ("离线" if str(account.health_status) == "offline" else str(account.health_status))
    )
    if is_reauth_required_account(account):
        status_text = f"{status_text}（需要重新绑定）"
    text = (
        "👤 **账号详情**\n\n"
        f"显示名：{('@' + account.username) if account.username else (account.phone or '未命名账号')}\n"
        f"状态：{status_text}\n"
        f"当前账号：{'是' if str(active_account_id or '') == str(account.account_id) else '否'}\n"
        f"已发送：{account.messages_sent}\n"
        f"自动发送：{auth_text}\n"
        f"到期时间：{auth_summary.authorization_end_at.strftime('%Y-%m-%d %H:%M') if auth_summary.authorization_end_at else '-'}\n\n"
        "下一步：请选择下方操作继续管理该账号。"
    )
    keyboard = [
        [Button.inline("⚙️ 设为当前账号", data=f"acc_set_active:{account_id}")],
        [Button.inline("🔄 同步资源", data=f"acc_sync:{account_id}"), Button.inline("📱 重新绑定", data=f"acc_relogin:{account_id}")],
        [
            Button.inline(region.label, data=f"acc_proxy_select:{account_id}:{region.code}")
            for region in SING_BOX_PROXY_REGIONS[:4]
        ],
        [
            Button.inline(region.label, data=f"acc_proxy_select:{account_id}:{region.code}")
            for region in SING_BOX_PROXY_REGIONS[4:]
        ],
        [Button.inline("⏰ 创建定时任务", data=f"add_scheduled_task:{account_id}"), Button.inline("🖱️ 创建手动任务", data=f"add_manual_task:{account_id}")],
        [Button.inline("⏳ 续费卡密", data=f"acc_renew_authorization:{account_id}")],
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
    """Start a re-login flow that keeps the existing account and tasks."""
    db_user_id, account = await _get_owned_account(user_id, account_id)
    if db_user_id is None or not account:
        await event.answer("账号不存在或无权限", alert=True)
        return
    if is_reauth_required_account(account):
        async with get_async_session() as session:
            proxy = await session.get(Proxy, int(account.proxy_id)) if account.proxy_id else None
        if not proxy or not bool(getattr(proxy, "is_system_gateway", False)):
            await event.answer("请先选择一个固定代理地区，再重新登录。", alert=True)
            await _send_or_reply(
                event,
                "⚠️ **请先选择代理地区**\n\n"
                "该账号需要重新绑定。为降低再次失效风险，请先选择与用户日常 VPN/登录地区接近的固定代理，然后再重新登录。",
                buttons=[
                    [
                        Button.inline(region.label, data=f"acc_proxy_select:{account_id}:{region.code}")
                        for region in SING_BOX_PROXY_REGIONS[:4]
                    ],
                    [
                        Button.inline(region.label, data=f"acc_proxy_select:{account_id}:{region.code}")
                        for region in SING_BOX_PROXY_REGIONS[4:]
                    ],
                    [Button.inline("⬅️ 返回账号页", data=f"acc_menu:{account_id}")],
                ],
            )
            return
    from backend.bot.onboarding import get_onboarding_service

    await event.answer("开始重新登录，请用原 Telegram 账号完成验证。")
    await get_onboarding_service().start_account_login(
        event,
        user_id,
        existing_tg_user_id=int(account.tg_user_id or 0) or None,
        target_account_id=str(account.account_id),
    )


async def select_account_proxy_region(event, user_id: int, account_id: str, region_code: str):
    """Select a fixed proxy region for account re-login."""
    db_user_id, account = await _get_owned_account(user_id, account_id)
    if db_user_id is None or not account:
        await event.answer("账号不存在或无权限", alert=True)
        return

    async with get_async_session() as session:
        result = await select_reauth_proxy_for_account(
            session,
            user_id=int(db_user_id),
            account_id=str(account_id),
            region_code=region_code,
        )
        await session.commit()

    from backend.bot.account.manager import get_account_manager

    await close_client(get_account_manager(), str(account_id))
    label = result.get("region_label") or result.get("region_code") or "已选地区"
    await event.answer(f"已选择{label}代理，请重新登录。")
    await _send_or_reply(
        event,
        "✅ **代理已配置**\n\n"
        f"账号：{('@' + account.username) if account.username else (account.phone or '未命名账号')}\n"
        f"代理地区：{label}\n\n"
        "下一步：请点击“重新绑定”，用原 Telegram 账号完成登录。成功后账号会进入 24 小时观察期。",
        buttons=[
            [Button.inline("📱 重新绑定", data=f"acc_relogin:{account_id}")],
            [Button.inline("⬅️ 返回账号页", data=f"acc_menu:{account_id}")],
        ],
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
        f"显示名：{('@' + account.username) if account.username else (account.phone or '未命名账号')}\n"
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
