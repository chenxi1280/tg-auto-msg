"""Bot-first onboarding, subscription and login flows."""
from __future__ import annotations

import asyncio
import secrets
import string
from datetime import datetime
from io import BytesIO
from typing import Any, Optional

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from telethon import Button, TelegramClient, password as telethon_password
from telethon.errors import PasswordHashInvalidError
from telethon.sessions import StringSession
from telethon.tl.functions.account import GetPasswordRequest
from telethon.tl.functions.auth import CheckPasswordRequest

from backend.bot.account.manager import get_account_manager
from backend.bot.client_runtime.manager import bot_client
from backend.bot.client_runtime.qr_login import wait_for_qr_login as _wait_for_qr_login_flow
from backend.bot.developer_apps import get_developer_app_service
from backend.bot.handlers.core.helpers import is_valid_button_url
from backend.bot.handlers.core.user_link import set_linked_system_user_id
from backend.bot.handlers.task.queries import resolve_db_user_id
from backend.bot.session.redis_login_manager import LoginStatus, get_redis_login_manager
from backend.bot.state.fsm import FSMState, fsm_storage
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account, User
from backend.h5_backend.services.auth.service import get_auth_service
from backend.h5_backend.services.me.account_limit import TgAccountLimitExceededError
from backend.h5_backend.services.me.service import get_me_service
from backend.utils.security.crypto import decrypt_string_session, encrypt_string_session

_PENDING_LOGIN_TASKS: dict[int, asyncio.Task] = {}
_PENDING_LOGIN_CLIENTS: dict[int, TelegramClient] = {}
_PENDING_LOGIN_MESSAGE_IDS: dict[int, set[int]] = {}
_QR_MESSAGE_TTL_SECONDS = 60


def _random_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _new_login_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "bot_login_" + "".join(secrets.choice(alphabet) for _ in range(16))


def _normalize_email(raw_value: str) -> Optional[str]:
    value = (raw_value or "").strip().lower()
    return value or None


def _is_valid_username(value: str) -> bool:
    text = (value or "").strip()
    if len(text) < 3 or len(text) > 50:
        return False
    return all(ch.isalnum() or ch == "_" for ch in text)


async def _delete_message_safely(event, *, state: Optional[FSMState] = None) -> None:
    try:
        await event.delete()
        logger.info(
            "password message deleted: sender={}, chat={}, state={}",
            getattr(event, "sender_id", None),
            getattr(event, "chat_id", None),
            state.value if isinstance(state, FSMState) else state,
        )
    except Exception as exc:
        logger.warning(
            "password message delete failed: sender={}, chat={}, state={}, error_type={}",
            getattr(event, "sender_id", None),
            getattr(event, "chat_id", None),
            state.value if isinstance(state, FSMState) else state,
            type(exc).__name__,
        )


async def _send_or_edit(event, text: str, *, buttons: Any = None, parse_mode: Optional[str] = "markdown") -> None:
    if hasattr(event, "edit"):
        try:
            await event.edit(text, buttons=buttons, parse_mode=parse_mode)
            return
        except Exception:
            pass
    await event.respond(text, buttons=buttons, parse_mode=parse_mode)


async def _send_main_menu_to_actor(tg_user_id: int) -> None:
    text, buttons = await get_onboarding_service().build_home_view(tg_user_id)
    await bot_client.send_message(tg_user_id, text, buttons=buttons, parse_mode="markdown")


async def _reply_idle_main_menu(
    event,
    tg_user_id: int,
    *,
    prefix_text: Optional[str] = None,
) -> None:
    text, buttons = await get_onboarding_service().build_home_view(tg_user_id)
    if prefix_text:
        text = f"{prefix_text}\n\n{text}"
    await event.respond(text, buttons=buttons, parse_mode="markdown")


def _track_login_message(tg_user_id: int, message: Any) -> None:
    """Track bot-side login messages so they can be deleted on cancel."""
    message_id = getattr(message, "id", None)
    if not message_id:
        return
    _PENDING_LOGIN_MESSAGE_IDS.setdefault(tg_user_id, set()).add(int(message_id))


async def _clear_tracked_login_messages(tg_user_id: int, *, delete: bool) -> None:
    """Clear or delete tracked login messages for one Telegram user."""
    message_ids = sorted(_PENDING_LOGIN_MESSAGE_IDS.pop(tg_user_id, set()))
    if not delete or not message_ids:
        return
    try:
        await bot_client.delete_messages(tg_user_id, message_ids)
    except Exception:
        pass


def _build_login_qr_caption(*, refreshed: bool = False) -> str:
    prefix = "🔄 **二维码已刷新**\n\n" if refreshed else "🔐 **请使用 Telegram 扫码登录**\n\n"
    return (
        prefix +
        "路径：Telegram -> 设置 -> 设备 -> 链接桌面设备\n"
        f"二维码约 {_QR_MESSAGE_TTL_SECONDS} 秒内有效，过期后系统会自动删除旧二维码并发送新的二维码。\n"
        "扫码确认后请等待约 5 秒，系统会自动继续。\n"
        "若出现二步验证，Bot 会继续提示你输入密码。\n\n"
        "下一步：扫码确认后留在当前聊天，等待 Bot 继续提示。"
    )


def _account_display_name(account: Account) -> str:
    if account.username:
        return f"@{account.username}"
    if account.phone:
        return account.phone
    if account.tg_user_id:
        return f"UID:{account.tg_user_id}"
    return account.account_id[:8]


def _friendly_login_error(message: str) -> str:
    raw = str(message or "").strip()
    lowered = raw.lower()
    if not raw:
        return "登录未完成，请重新点击“登录账号”再试一次。"
    if "expired" in lowered or "过期" in raw:
        return "二维码已过期，请重新点击“登录账号”获取新的二维码。"
    if "password" in lowered or "二步" in raw:
        return "该账号需要输入 Telegram 二步验证密码，请按提示继续输入。"
    if "session" in lowered or "会话" in raw:
        return "登录会话已失效，请重新点击“登录账号”。"
    if "token" in lowered:
        return "二维码状态已失效，请重新点击“登录账号”生成新的二维码。"
    return raw


class BotOnboardingService:
    """Bot-first user onboarding service."""

    async def delete_sensitive_input_message(self, event, state: FSMState) -> None:
        await _delete_message_safely(event, state=state)

    async def reply_idle_main_menu(
        self,
        event,
        tg_user_id: int,
        *,
        prefix_text: Optional[str] = None,
    ) -> None:
        await _reply_idle_main_menu(event, tg_user_id, prefix_text=prefix_text)

    async def _get_db_user_id(self, tg_user_id: int) -> Optional[int]:
        async with get_async_session() as session:
            return await resolve_db_user_id(session, tg_user_id)

    async def _create_user_and_link(
        self,
        *,
        tg_user_id: int,
        username: str,
        password: str,
        email: Optional[str],
    ) -> User:
        auth_service = get_auth_service()
        normalized_email = _normalize_email(email or "")

        async with get_async_session() as session:
            existing_user_id = await resolve_db_user_id(session, tg_user_id)
            if existing_user_id is not None:
                row = await session.get(User, existing_user_id)
                if row is None:
                    raise HTTPException(status_code=404, detail="系统用户不存在")
                return row

            existed_username = await session.execute(
                select(User.id).where(User.username == username).limit(1)
            )
            if existed_username.scalar_one_or_none() is not None:
                raise HTTPException(status_code=400, detail="用户名已存在，请换一个")

            if normalized_email:
                existed_email = await session.execute(
                    select(User.id).where(func.lower(User.email) == normalized_email).limit(1)
                )
                if existed_email.scalar_one_or_none() is not None:
                    raise HTTPException(status_code=400, detail="邮箱已被占用，请换一个")

            user = User(
                username=username,
                password_hash=auth_service.get_password_hash(password),
                email=normalized_email,
                is_active=True,
            )
            session.add(user)
            await session.flush()
            await set_linked_system_user_id(session, tg_user_id, int(user.id))
            await session.commit()
            await session.refresh(user)
            return user

    async def ensure_active_subscription(self, event, tg_user_id: int) -> Optional[int]:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return None

        me_service = get_me_service()
        try:
            await me_service.require_active_subscription(db_user_id)
        except HTTPException as exc:
            await self._respond_subscription_error(event, str(exc.detail))
            return None
        return db_user_id

    async def auto_register(self, event, tg_user_id: int) -> None:
        existing_user_id = await self._get_db_user_id(tg_user_id)
        if existing_user_id is not None:
            await self.show_home(event, tg_user_id)
            return

        base_username = f"tg_{tg_user_id}"
        password = _random_password()
        user: Optional[User] = None
        last_error: Optional[Exception] = None

        for attempt in range(10):
            candidate = base_username if attempt == 0 else f"{base_username}_{secrets.token_hex(2)}"
            try:
                user = await self._create_user_and_link(
                    tg_user_id=tg_user_id,
                    username=candidate,
                    password=password,
                    email=None,
                )
                break
            except HTTPException as exc:
                last_error = exc
                if exc.detail == "用户名已存在，请换一个":
                    continue
                raise
            except IntegrityError as exc:
                last_error = exc
                continue

        if user is None:
            raise RuntimeError(f"自动注册失败: {last_error or '未知错误'}")

        fsm_storage.reset_state(tg_user_id)
        await event.respond(
            "✅ **注册成功**\n\n"
            f"用户名：`{user.username}`\n"
            f"Web 初始密码：`{password}`\n\n"
            "该密码仅展示一次，请尽快在 Web 端修改。\n\n"
            "下一步：点击下方「💳 激活套餐」，完成开通后即可登录 Telegram 账号。",
            parse_mode="markdown",
            buttons=[
                [Button.inline("💳 激活套餐", data="bot_activate"), Button.inline("💳 查看订阅", data="bot_subscription")],
                [Button.inline("⬅️ 返回主菜单", data="bot_home")],
            ],
        )

    async def start_manual_registration(self, event, tg_user_id: int) -> None:
        existing_user_id = await self._get_db_user_id(tg_user_id)
        if existing_user_id is not None:
            await self.show_home(event, tg_user_id)
            return
        fsm_storage.set_state(tg_user_id, FSMState.WAIT_REGISTER_USERNAME)
        fsm_storage.update_data(tg_user_id)
        await _send_or_edit(
            event,
            "🚀 **注册系统账号**\n\n"
            "请输入你想使用的用户名（3-50 位，仅支持字母、数字、下划线）。\n"
            "发送 `/cancel` 可取消。\n\n"
            "下一步：发送用户名后，Bot 会继续引导你设置密码。",
        )

    async def handle_register_username(self, event, tg_user_id: int, text: str) -> None:
        value = (text or "").strip()
        if value.lower() == "/cancel":
            fsm_storage.reset_state(tg_user_id)
            await self.show_home(event, tg_user_id)
            return
        if not _is_valid_username(value):
            await event.respond("❌ 用户名格式不正确，请输入 3-50 位字母、数字或下划线。")
            return

        fsm_storage.set_state(tg_user_id, FSMState.WAIT_REGISTER_PASSWORD)
        fsm_storage.update_data(tg_user_id, register_username=value)
        await event.respond(
            "🔐 请输入登录密码（至少 6 位）。\n"
            "发送后仅用于系统注册，不会回显。",
        )

    async def handle_register_password(self, event, tg_user_id: int, text: str) -> None:
        value = (text or "").strip()
        if value.lower() == "/cancel":
            fsm_storage.reset_state(tg_user_id)
            await _send_main_menu_to_actor(tg_user_id)
            return
        if len(value) < 6:
            await bot_client.send_message(tg_user_id, "❌ 密码至少需要 6 位，请重新输入。")
            return

        fsm_storage.set_state(tg_user_id, FSMState.WAIT_REGISTER_EMAIL)
        fsm_storage.update_data(tg_user_id, register_password=value)
        await bot_client.send_message(
            tg_user_id,
            "📮 请输入邮箱（可选）。\n"
            "如果不想填写，请回复 `skip`。",
            parse_mode="markdown",
        )

    async def handle_register_email(self, event, tg_user_id: int, text: str) -> None:
        value = (text or "").strip()
        if value.lower() == "/cancel":
            fsm_storage.reset_state(tg_user_id)
            await self.show_home(event, tg_user_id)
            return

        email = None if value.lower() in {"skip", "跳过", "-"} else value
        if email and ("@" not in email or "." not in email):
            await event.respond("❌ 邮箱格式不正确，请重新输入，或发送 `skip` 跳过。", parse_mode="markdown")
            return

        data = fsm_storage.get_data(tg_user_id)
        username = str(data.get("register_username") or "").strip()
        password = str(data.get("register_password") or "")
        if not username or not password:
            fsm_storage.reset_state(tg_user_id)
            await event.respond("⚠️ 注册会话已失效，请重新开始。")
            await self.show_home(event, tg_user_id)
            return

        try:
            user = await self._create_user_and_link(
                tg_user_id=tg_user_id,
                username=username,
                password=password,
                email=email,
            )
        except HTTPException as exc:
            if str(exc.detail).startswith("用户名已存在"):
                fsm_storage.set_state(tg_user_id, FSMState.WAIT_REGISTER_USERNAME)
                fsm_storage.update_data(tg_user_id, register_password=None)
                await event.respond("❌ 用户名已存在，请重新输入新的用户名。")
                return
            await event.respond(f"❌ 注册失败：{exc.detail}")
            return

        fsm_storage.reset_state(tg_user_id)
        await event.respond(
            "✅ **注册成功**\n\n"
            f"用户名：`{user.username}`\n"
            "下一步：点击下方「💳 激活套餐」，完成开通后即可登录 Telegram 账号。",
            parse_mode="markdown",
            buttons=[
                [Button.inline("💳 激活套餐", data="bot_activate"), Button.inline("💳 查看订阅", data="bot_subscription")],
                [Button.inline("⬅️ 返回主菜单", data="bot_home")],
            ],
        )

    async def build_home_view(self, tg_user_id: int) -> tuple[str, list]:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            text = (
                "👋 **欢迎使用全球通**\n\n"
                "全球通是你的 Telegram 定时消息管理入口。\n\n"
                "这里就是主操作入口。你可以直接在 Bot 内完成：\n"
                "1. 注册系统账号\n"
                "2. 激活套餐\n"
                "3. 登录 Telegram 账号\n"
                "4. 管理任务与查看状态\n\n"
                "下一步：请选择一种注册方式开始。"
            )
            buttons = [
                [
                    Button.inline("🚀 自动注册", data="bot_reg_auto"),
                    Button.inline("手动注册", data="bot_reg_manual"),
                ]
            ]
            return text, buttons

        me_service = get_me_service()
        profile = await me_service.get_profile(db_user_id)
        subscription = profile["subscription"]
        tg_account_limit = profile.get("tg_account_limit") or {}
        purchase = profile["purchase"]
        plans = profile["plans"]
        user = profile["user"]
        accounts = await get_account_manager().get_accounts(db_user_id, is_active=False)

        if not subscription["is_active"]:
            plans_text = " / ".join(
                f"{plan['display_name']} {plan['price_yuan']}元"
                for plan in plans
            ) or "请联系管理员配置套餐"
            text = (
                "⚠️ **全球通账号已注册，尚未开通**\n\n"
                f"用户名：`{user['username']}`\n"
                f"可选套餐：{plans_text}\n\n"
                "开通全球通套餐后，你就可以直接在 Bot 内扫码登录 Telegram 账号。\n\n"
                "下一步：点击下方「💳 激活套餐」或「💳 立即购买」。"
            )
            buttons = [
                [Button.inline("💳 激活套餐", data="bot_activate"), Button.inline("💳 立即购买", data="bot_purchase")],
                [Button.inline("💳 查看订阅", data="bot_subscription"), Button.inline("🧷 查看绑定码", data="bot_bind_codes")],
            ]
            return text, buttons

        current = subscription["current"] or {}
        remain_days = subscription["remain_days"]
        limit_info = tg_account_limit
        effective_limit = int(limit_info.get("effective_limit") or 0)
        account_summary = (
            f"{limit_info.get('account_count', len(accounts))}/{effective_limit}"
            if effective_limit > 0
            else f"{limit_info.get('account_count', len(accounts))}/∞"
        )
        text = (
            "✅ **全球通已就绪，可以开始使用**\n\n"
            f"系统用户：`{user['username']}`\n"
            f"订阅状态：已开通\n"
            f"剩余天数：{remain_days if remain_days is not None else '-'}\n"
            f"到期时间：{current.get('end_at') or '-'}\n"
            f"账号数量：{account_summary}\n\n"
            "下一步：可先查看账号，或继续登录新的 Telegram 账号。"
        )
        buttons = [
            [Button.inline("👥 查看账号", data="accounts_list"), Button.inline("🔐 登录账号", data="bot_login_account")],
            [Button.inline("📋 查看任务", data="task_list"), Button.inline("💳 查看订阅", data="bot_subscription")],
            [Button.inline("🧷 查看绑定码", data="bot_bind_codes"), Button.inline("💳 立即购买", data="bot_purchase")],
        ]
        return text, buttons

    async def show_home(self, event, tg_user_id: int) -> None:
        text, buttons = await self.build_home_view(tg_user_id)
        await _send_or_edit(event, text, buttons=buttons)

    async def _respond_subscription_error(self, event, message: str) -> None:
        if hasattr(event, "answer"):
            await event.answer(message, alert=True)
            return
        await event.respond(
            f"⚠️ {message}",
            buttons=[
                [Button.inline("💳 查看订阅", data="bot_subscription"), Button.inline("💳 立即购买", data="bot_purchase")],
                [Button.inline("⬅️ 返回主菜单", data="bot_home")],
            ],
        )

    async def show_purchase(self, event, tg_user_id: int) -> None:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return
        me_service = get_me_service()
        status = await me_service.get_subscription_status(db_user_id)
        purchase = status["purchase"]
        plans_text = "\n".join(
            f"• {plan['display_name']}：{plan['price_yuan']} 元 / {plan['duration_days']} 天"
            for plan in status["plans"]
        ) or "• 暂无可用套餐"

        text = (
            "💳 **全球通购买指引**\n\n"
            f"{plans_text}\n\n"
            "如需开通或续费，请点击下方按钮前往 Telegram 购买入口，购买全球通套餐。\n\n"
            "下一步：完成购买后，返回 Bot 使用激活码完成开通。"
        )
        buttons = [[Button.inline("⬅️ 返回主菜单", data="bot_home")]]
        purchase_url = (purchase.get("url") or "").strip()
        if is_valid_button_url(purchase_url):
            buttons.insert(0, [Button.url(purchase.get("button_text") or "立即购买", purchase_url)])
        else:
            text = f"{text}\n\n购买链接：{purchase_url or '未配置'}"
        await _send_or_edit(event, text, buttons=buttons)

    async def show_subscription(self, event, tg_user_id: int) -> None:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return
        me_service = get_me_service()
        status = await me_service.get_subscription_status(db_user_id)
        current = status["current"] or {}
        plan_map = {plan["plan_code"]: plan["display_name"] for plan in status.get("plans") or []}
        plan_name = plan_map.get(current.get("plan_code")) or current.get("plan_code") or "-"
        text = (
            "💳 **全球通订阅信息**\n\n"
            f"状态：{'已开通' if status['is_active'] else '未开通'}\n"
            f"套餐：{plan_name}\n"
            f"剩余天数：{status.get('remain_days') if status.get('remain_days') is not None else '-'}\n"
            f"到期时间：{current.get('end_at') or '-'}\n\n"
            f"TG账号上限：{('∞' if int((status.get('tg_account_limit') or {}).get('effective_limit') or 0) == 0 else str((status.get('tg_account_limit') or {}).get('effective_limit')))}\n\n"
            "若即将到期，Bot 会在到期前 7 天、3 天、1 天自动提醒。\n\n"
            "下一步：未开通请先购买并激活；已开通可返回主菜单继续操作。"
        )
        buttons = [[Button.inline("⬅️ 返回主菜单", data="bot_home")]]
        purchase = status.get("purchase") or {}
        if not status["is_active"]:
            buttons.insert(0, [Button.inline("💳 激活套餐", data="bot_activate")])
        if not status["is_active"] and is_valid_button_url((purchase.get("url") or "").strip()):
            buttons.insert(0, [Button.url(purchase.get("button_text") or "立即购买", purchase["url"])])
        await _send_or_edit(event, text, buttons=buttons)

    async def start_activation(self, event, tg_user_id: int) -> None:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return
        fsm_storage.set_state(tg_user_id, FSMState.WAIT_ACTIVATION_CODE)
        await _send_or_edit(
            event,
            "💳 **激活套餐**\n\n请输入发卡系统提供的激活码。\n"
            "如果暂时不想继续，发送 `/cancel` 可返回主菜单。\n\n"
            "下一步：输入成功后会立即为你开通套餐。",
        )

    async def handle_activation_code(self, event, tg_user_id: int, text: str) -> None:
        value = (text or "").strip()
        if value.lower() == "/cancel":
            fsm_storage.reset_state(tg_user_id)
            await self.show_home(event, tg_user_id)
            return
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            fsm_storage.reset_state(tg_user_id)
            await self.show_home(event, tg_user_id)
            return

        me_service = get_me_service()
        try:
            status = await me_service.activate_card(db_user_id, value)
        except HTTPException as exc:
            await event.respond(
                f"❌ 激活失败：{exc.detail}\n"
                "下一步：请核对激活码后重新输入，或点击「💳 立即购买」获取新的激活码。"
            )
            return

        fsm_storage.reset_state(tg_user_id)
        current = status.get("current") or {}
        await event.respond(
            "✅ **全球通激活成功**\n\n"
            f"剩余天数：{status.get('remain_days')}\n"
            f"到期时间：{current.get('end_at') or '-'}\n\n"
            "下一步：点击下方「🔐 登录账号」，在 Bot 内扫码登录 Telegram 账号。",
            parse_mode="markdown",
            buttons=[
                [Button.inline("🔐 登录账号", data="bot_login_account"), Button.inline("💳 查看订阅", data="bot_subscription")],
                [Button.inline("⬅️ 返回主菜单", data="bot_home")],
            ],
        )

    async def show_bind_codes(self, event, tg_user_id: int) -> None:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return

        account_manager = get_account_manager()
        accounts = await account_manager.get_accounts(db_user_id, is_active=False)
        if not accounts:
            await _send_or_edit(
                event,
                "🧷 **绑定码**\n\n当前还没有可展示的账号绑定码。\n\n下一步：请先点击下方「🔐 登录账号」。",
                buttons=[[Button.inline("🔐 登录账号", data="bot_login_account")], [Button.inline("⬅️ 返回主菜单", data="bot_home")]],
            )
            return

        lines = []
        buttons = []
        for index, account in enumerate(accounts[:8], start=1):
            issued = await account_manager.issue_bind_code(account.account_id, refresh=False)
            code = issued["bind_code"] if issued else "未生成"
            expires_at = issued["expires_at"].strftime("%Y-%m-%d %H:%M") if issued and issued.get("expires_at") else "-"
            display = account.username or account.phone or f"ID:{account.tg_user_id or account.account_id[:8]}"
            lines.append(
                f"{index}. {display}\n"
                f"   绑定码：`{code}`\n"
                f"   过期时间：{expires_at}\n"
                f"   快捷命令：`/bind {code}`"
            )
            buttons.append([Button.inline(f"🧷 刷新绑定码 {display[:10]}", data=f"acc_bindcode:{account.account_id}")])

        buttons.append([Button.inline("⬅️ 返回主菜单", data="bot_home")])
        await _send_or_edit(
            event,
            "🧷 **全球通绑定码**\n\n"
            "用于手动发送 `/bind <绑定码>`，或核对账号绑定关系。\n\n"
            + "\n\n".join(lines)
            + "\n\n下一步：如需重新生成，请点击下方「🧷 刷新绑定码」。",
            buttons=buttons,
        )

    async def _render_qr_file(self, qr_url: str) -> Optional[BytesIO]:
        try:
            import qrcode
        except Exception:
            return None

        buf = BytesIO()
        image = qrcode.make(qr_url)
        image.save(buf, format="PNG")
        buf.seek(0)
        buf.name = "telegram-login-qr.png"
        return buf

    async def _cancel_existing_login_task(self, tg_user_id: int) -> None:
        task = _PENDING_LOGIN_TASKS.pop(tg_user_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        client = _PENDING_LOGIN_CLIENTS.pop(tg_user_id, None)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass
        await _clear_tracked_login_messages(tg_user_id, delete=True)

    async def _send_login_qr_message(
        self,
        *,
        tg_user_id: int,
        login_id: str,
        qr_url: str,
        refreshed: bool = False,
    ) -> None:
        await _clear_tracked_login_messages(tg_user_id, delete=True)
        qr_file = await self._render_qr_file(qr_url)
        caption = _build_login_qr_caption(refreshed=refreshed)
        buttons = [[Button.inline("⬅️ 取消登录", data=f"bot_cancel_login:{login_id}")]]
        if qr_file is not None:
            message = await bot_client.send_file(
                tg_user_id,
                qr_file,
                caption=caption,
                parse_mode="markdown",
                buttons=buttons,
            )
        else:
            message = await bot_client.send_message(
                tg_user_id,
                f"{caption}\n\n二维码链接：`{qr_url}`",
                parse_mode="markdown",
                buttons=buttons,
            )
        _track_login_message(tg_user_id, message)

    async def start_account_login(self, event, tg_user_id: int) -> None:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return

        me_service = get_me_service()
        try:
            await me_service.require_active_subscription(db_user_id)
            await me_service.ensure_can_add_tg_account(db_user_id)
        except HTTPException as exc:
            await self._respond_subscription_error(event, str(exc.detail))
            return
        except TgAccountLimitExceededError as exc:
            await self._respond_limit_error(
                event,
                tg_user_id,
                limit_message=str(exc),
            )
            return

        developer_service = get_developer_app_service()
        credentials = await developer_service.choose_login_credentials_for_user(db_user_id)
        login_manager = get_redis_login_manager()
        login_id = _new_login_id()
        await login_manager.create_session(login_id)
        await login_manager.update_status(
            login_id,
            LoginStatus.PENDING,
            system_user_id=db_user_id,
            developer_app_id=credentials.app_id or "",
            error="",
        )

        login_client = TelegramClient(
            StringSession(),
            api_id=credentials.api_id,
            api_hash=credentials.api_hash,
        )
        await login_client.connect()
        _PENDING_LOGIN_CLIENTS[tg_user_id] = login_client
        qr_login = await login_client.qr_login()
        await login_manager.update_qr_url(login_id, qr_login.url)
        await login_manager.update_status(login_id, LoginStatus.PENDING)

        await self._cancel_existing_login_task(tg_user_id)
        task = asyncio.create_task(self._run_login_watcher(tg_user_id, db_user_id, login_id, qr_login, login_client))
        _PENDING_LOGIN_TASKS[tg_user_id] = task
        await self._send_login_qr_message(
            tg_user_id=tg_user_id,
            login_id=login_id,
            qr_url=qr_login.url,
            refreshed=False,
        )

        if hasattr(event, "answer"):
            await event.answer("二维码已发送，请查看最新消息")

    async def _run_login_watcher(
        self,
        tg_user_id: int,
        db_user_id: int,
        login_id: str,
        qr_login,
        login_client: TelegramClient,
    ) -> None:
        login_manager = get_redis_login_manager()
        try:
            await _wait_for_qr_login_flow(
                login_id=login_id,
                qr_login=qr_login,
                userbot_client=login_client,
                login_client=login_client,
                save_system_session_fn=None,
                system_userbot_session_key=None,
                on_qr_refreshed=self._make_qr_refresh_notifier(
                    tg_user_id=tg_user_id,
                    login_id=login_id,
                ),
            )
            session = await login_manager.get_session(login_id)
            if session is None:
                await bot_client.send_message(tg_user_id, "⚠️ 登录会话已失效，请重新发起登录。")
                return

            if session.status == LoginStatus.PASSWORD_REQUIRED:
                hint = f"\n密码提示：`{session.password_hint}`" if session.password_hint else ""
                fsm_storage.set_state(tg_user_id, FSMState.WAIT_LOGIN_PASSWORD)
                fsm_storage.update_data(tg_user_id, login_id=login_id)
                password_prompt = await bot_client.send_message(
                    tg_user_id,
                    "🔒 **该账号开启了二步验证**\n\n"
                    "请直接回复 Telegram 二步密码。\n"
                    "收到后系统会立即删除你的密码消息，不会在聊天里保留明文。"
                    f"{hint}\n\n下一步：输入正确密码后，系统会自动完成绑定。",
                    parse_mode="markdown",
                    buttons=[[Button.inline("⬅️ 取消登录", data=f"bot_cancel_login:{login_id}")]],
                )
                _track_login_message(tg_user_id, password_prompt)
                return

            if session.status == LoginStatus.CONFIRMED:
                await self._finalize_bound_account(
                    tg_user_id=tg_user_id,
                    db_user_id=db_user_id,
                    login_id=login_id,
                )
                return

            if session.status == LoginStatus.EXPIRED:
                await _clear_tracked_login_messages(tg_user_id, delete=True)
                await bot_client.send_message(tg_user_id, "⌛ 二维码已过期，请重新点击“登录账号”获取新的二维码。")
                return

            await bot_client.send_message(
                tg_user_id,
                f"❌ 登录失败：{_friendly_login_error(session.error)}",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"Bot 登录监控失败: {type(exc).__name__}: {exc!r}")
            await bot_client.send_message(
                tg_user_id,
                "❌ 登录流程异常，请稍后重新点击“登录账号”再试一次。",
            )
        finally:
            _PENDING_LOGIN_TASKS.pop(tg_user_id, None)
            client = _PENDING_LOGIN_CLIENTS.pop(tg_user_id, None)
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def cancel_login(self, event, tg_user_id: int, login_id: Optional[str] = None) -> None:
        await self._cancel_existing_login_task(tg_user_id)
        fsm_storage.reset_state(tg_user_id)
        if login_id:
            await get_redis_login_manager().delete_session(login_id)
        if hasattr(event, "answer"):
            await event.answer("已取消登录")
        await self.show_home(event, tg_user_id)

    async def _finalize_bound_account(self, *, tg_user_id: int, db_user_id: int, login_id: str) -> None:
        login_manager = get_redis_login_manager()
        session = await login_manager.get_session(login_id)
        if not session or not session.bind_code:
            await bot_client.send_message(tg_user_id, "❌ 登录已确认，但系统未拿到绑定信息，请重新登录一次。")
            return

        account_manager = get_account_manager()
        try:
            account = await account_manager.bind_account(
                user_id=db_user_id,
                bind_code=session.bind_code,
                ip_address="",
                actor_tg_user_id=tg_user_id,
            )
        except TgAccountLimitExceededError as exc:
            await bot_client.send_message(
                tg_user_id,
                f"⚠️ {exc}\n\n下一步：可删除闲置账号、升级套餐或联系管理员调整。",
            )
            return
        if not account:
            await bot_client.send_message(tg_user_id, "❌ 登录已完成，但自动绑定失败，请稍后重新登录一次。")
            return

        me_service = get_me_service()
        status = await me_service.get_subscription_status(db_user_id)
        current = status.get("current") or {}
        await bot_client.send_message(
            tg_user_id,
            "✅ **全球通登录并绑定成功**\n\n"
            f"账号：{_account_display_name(account)}\n"
            f"Telegram UID：`{account.tg_user_id or '-'}`\n"
            f"剩余天数：{status.get('remain_days') if status.get('remain_days') is not None else '-'}\n"
            f"到期时间：{current.get('end_at') or '-'}\n\n"
            "下一步：可继续查看账号、创建任务或查看绑定码。",
            parse_mode="markdown",
            buttons=[
                [Button.inline("👥 查看账号", data="accounts_list"), Button.inline("📋 查看任务", data="task_list")],
                [Button.inline("🧷 查看绑定码", data="bot_bind_codes"), Button.inline("⬅️ 返回主菜单", data="bot_home")],
            ],
        )
        await _clear_tracked_login_messages(tg_user_id, delete=False)
        fsm_storage.reset_state(tg_user_id)

    async def _respond_limit_error(self, event, tg_user_id: int, *, limit_message: str) -> None:
        text = f"⚠️ {limit_message}\n\n下一步：可删除闲置账号、升级套餐或联系管理员调整。"
        if hasattr(event, "answer"):
            await event.answer("已达账号上限")
        await bot_client.send_message(
            tg_user_id,
            text,
            buttons=[[Button.inline("⬅️ 返回主菜单", data="bot_home")]],
        )

    def _make_qr_refresh_notifier(self, *, tg_user_id: int, login_id: str):
        async def _notify(qr_url: str, reason: str) -> None:
            logger.info(
                "bot qr refreshed: sender={}, login_id={}, reason={}",
                tg_user_id,
                login_id,
                reason,
            )
            await self._send_login_qr_message(
                tg_user_id=tg_user_id,
                login_id=login_id,
                qr_url=qr_url,
                refreshed=True,
            )

        return _notify

    async def handle_login_password(self, event, tg_user_id: int, text: str) -> None:
        password = (text or "").strip()
        if password.lower() == "/cancel":
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(tg_user_id, "⚠️ 已取消输入二步密码。\n下一步：如需继续，请重新点击「🔐 登录账号」。")
            await _send_main_menu_to_actor(tg_user_id)
            return

        data = fsm_storage.get_data(tg_user_id)
        login_id = str(data.get("login_id") or "").strip()
        if not login_id:
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(tg_user_id, "⚠️ 登录会话已失效。\n下一步：请重新点击「🔐 登录账号」。")
            return

        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(tg_user_id, "⚠️ 当前 Bot 用户未注册。\n下一步：请先发送 /start 完成注册。")
            return

        login_manager = get_redis_login_manager()
        session = await login_manager.get_session(login_id)
        if not session:
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(tg_user_id, "⚠️ 登录会话不存在。\n下一步：请重新点击「🔐 登录账号」。")
            return
        if session.status != LoginStatus.PASSWORD_REQUIRED:
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(tg_user_id, "⚠️ 当前登录会话无需输入密码。\n下一步：请重新点击「🔐 登录账号」。")
            return
        if not session.pending_session_encrypted:
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(tg_user_id, "⚠️ 会话缺少待验证状态。\n下一步：请重新点击「🔐 登录账号」。")
            return

        developer_app_service = get_developer_app_service()
        async with get_async_session() as db_session:
            credentials = await developer_app_service.resolve_credentials(
                session=db_session,
                developer_app_id=session.developer_app_id,
                user_id=db_user_id,
            )

        temp_session = decrypt_string_session(session.pending_session_encrypted)
        client = TelegramClient(
            StringSession(temp_session),
            api_id=credentials.api_id,
            api_hash=credentials.api_hash,
        )

        try:
            await client.connect()
            password_info = await client(GetPasswordRequest())
            await client(CheckPasswordRequest(telethon_password.compute_check(password_info, password)))

            me = await client.get_me()
            string_session = StringSession.save(client.session)
            encrypted_session = encrypt_string_session(string_session)
            await login_manager.save_string_session(
                login_id=login_id,
                string_session=encrypted_session,
                tg_user_id=me.id,
                username=me.username or me.first_name or "",
                phone=me.phone or "",
            )
        except PasswordHashInvalidError:
            await login_manager.update_status(
                login_id,
                LoginStatus.PASSWORD_REQUIRED,
                error="二步密码错误，请重试",
            )
            await bot_client.send_message(tg_user_id, "❌ 二步密码错误，请重新输入。")
            return
        except Exception as exc:
            await login_manager.update_status(
                login_id,
                LoginStatus.ERROR,
                error=f"二步密码验证失败: {exc}",
            )
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(tg_user_id, "❌ 二步密码验证失败，请重新点击“登录账号”后再试一次。")
            return
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

        await self._finalize_bound_account(
            tg_user_id=tg_user_id,
            db_user_id=db_user_id,
            login_id=login_id,
        )


_service: Optional[BotOnboardingService] = None


def get_onboarding_service() -> BotOnboardingService:
    """Get singleton onboarding service."""
    global _service
    if _service is None:
        _service = BotOnboardingService()
    return _service
