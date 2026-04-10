"""Command handlers and command dispatch for Telegram bot."""
from __future__ import annotations

from typing import Optional
import re

from loguru import logger
from sqlalchemy import func, select

from backend.bot.state.fsm import fsm_storage
from backend.bot.notice_manager import get_bot_notice_manager
from backend.bot.handlers.core.auth_gate import require_db_user_id
from backend.bot.handlers.task.management import create_new_task, show_task_list
from backend.bot.handlers.task.queries import resolve_db_user_id as _resolve_db_user_id
from backend.bot.handlers.core.user_link import (
    get_active_account_id as _get_active_account_id,
    normalize_operator_account_refs as _normalize_operator_account_refs,
)
from backend.bot.handlers.account.management import show_accounts_list, show_proxy_management, sync_account_resources
from backend.bot.onboarding import get_onboarding_service
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account


async def handle_start_command(event):
    """Handle /start command."""
    actor_user_id = event.sender_id
    fsm_storage.reset_state(actor_user_id)
    raw_text = (event.raw_text or event.message.message or "").replace("／", "/").strip()
    match = re.match(r"(?i)^/start(?:@[\w\d_]+)?(?:\s+(.+))?$", raw_text)
    payload = (match.group(1) or "").strip() if match else ""

    bind_match = re.match(r"(?i)^link_([A-Za-z0-9]{8,32})$", payload)
    if bind_match:
        bind_token = bind_match.group(1)
        await get_onboarding_service().bind_system_account(event, actor_user_id, bind_token)
        return

    try:
        await get_bot_notice_manager().ensure_notice_for_user(actor_user_id, force_repost=False)
    except Exception as exc:
        logger.warning("启动时刷新公告失败: sender={}, error_type={}", actor_user_id, type(exc).__name__)

    async with get_async_session() as session:
        linked_user_id = await _resolve_db_user_id(session, actor_user_id)
    if linked_user_id is None:
        claimed = await get_onboarding_service().try_auto_claim_from_account(event, actor_user_id)
        if claimed:
            return
        await get_onboarding_service().auto_register(event, actor_user_id)
        return

    # Repair stale mapping: user already mapped, but mapped user has no accounts,
    # while this Telegram sender exists as an account under another user.
    async with get_async_session() as session:
        mapped_account_count = (
            await session.execute(
                select(func.count())
                .select_from(Account)
                .where(Account.user_id == int(linked_user_id))
            )
        ).scalar_one()
        exists_other_owner = (
            await session.execute(
                select(Account.account_id)
                .where(
                    Account.tg_user_id == int(actor_user_id),
                    Account.user_id != int(linked_user_id),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
    if int(mapped_account_count or 0) == 0 and exists_other_owner is not None:
        claimed = await get_onboarding_service().try_auto_claim_from_account(event, actor_user_id)
        if claimed:
            return

    await get_onboarding_service().show_home(event, actor_user_id)


async def handle_bind_command(event):
    """Handle /bind command as compatibility entry for system-account binding."""
    try:
        actor_tg_user_id = event.sender_id
        text = (event.raw_text or event.message.message or "")
        normalized = text.replace("／", "/").strip()
        if not normalized:
            return
        if not normalized.lower().startswith("/bind"):
            return

        logger.info(f"收到 /bind 命令: sender={actor_tg_user_id}, text={normalized!r}")

        match = re.match(r"(?i)^/bind(?:@[\w\d_]+)?(?:\s+([A-Za-z0-9]{8,32}))?(?:\s+.*)?$", normalized)
        if not match:
            await event.respond(
                "📝 **使用方法：**\n请优先从 Web 首页点击“系统账号绑定到 TG Bot”按钮自动完成系统账号绑定。\n\n"
                "如需兼容手动方式，可使用：`/bind <系统绑定码>`",
                parse_mode="markdown",
            )
            return

        bind_token = (match.group(1) or "").strip()
        if not bind_token:
            await event.respond("❌ 请先从 Web 首页点击“系统账号绑定到 TG Bot”按钮获取系统绑定入口。", parse_mode="markdown")
            return
        await get_onboarding_service().bind_system_account(event, actor_tg_user_id, bind_token)
    except Exception as exc:
        logger.exception(f"/bind 处理失败: {type(exc).__name__}: {exc!r}")
        await event.respond("❌ 绑定处理异常，请稍后重试。\n如果问题持续存在，请回到 Web 首页重新点击“系统账号绑定到 TG Bot”。")


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
    if await get_onboarding_service().ensure_registered_user(event, user_id) is None:
        return
    await show_task_list(event, user_id)


async def _run_accounts_command(event, user_id: int, args: str):
    del args
    if await require_db_user_id(event, user_id) is None:
        return
    if await get_onboarding_service().ensure_registered_user(event, user_id) is None:
        return
    await show_accounts_list(event, user_id)


async def _run_sync_command(event, user_id: int, args: str):
    db_user_id = await require_db_user_id(event, user_id)
    if db_user_id is None:
        return
    if await get_onboarding_service().ensure_registered_user(event, user_id) is None:
        return
    account_id = args.split()[0] if args else None
    if not account_id:
        async with get_async_session() as session:
            active_accounts = (
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
                valid_account_ids=[str(item) for item in active_accounts],
                preferred_account_id=str(active_accounts[0]) if len(active_accounts) == 1 else None,
            )
            active_account_id = ref_state.get("active_account_id") or await _get_active_account_id(session, user_id, db_user_id)
            if active_account_id:
                exists = await session.execute(
                    select(Account.account_id).where(
                        Account.account_id == active_account_id,
                        Account.user_id == db_user_id,
                    )
                )
                if exists.scalar_one_or_none():
                    account_id = active_account_id
    await sync_account_resources(event, user_id, account_id)


async def _run_proxy_command(event, user_id: int, args: str):
    del args
    if await require_db_user_id(event, user_id) is None:
        return
    if await get_onboarding_service().ensure_registered_user(event, user_id) is None:
        return
    await show_proxy_management(event, user_id)


async def _run_help_command(event, user_id: int, args: str):
    del args
    await get_onboarding_service().show_help(event, user_id)


async def _run_notice_command(event, user_id: int, args: str):
    del args
    await get_onboarding_service().show_notice(event, user_id)


async def _run_login_command(event, user_id: int, args: str):
    del args
    await get_onboarding_service().start_account_login(event, user_id)


async def _run_newtask_command(event, user_id: int, args: str):
    del args
    if await require_db_user_id(event, user_id) is None:
        return
    if await get_onboarding_service().ensure_registered_user(event, user_id) is None:
        return
    await create_new_task(event, user_id)


_SHORT_COMMAND_HANDLERS = {
    "help": _run_help_command,
    "notice": _run_notice_command,
    "login": _run_login_command,
    "newtask": _run_newtask_command,
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
