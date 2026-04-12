"""Bot-first onboarding, license-slot and login flows."""
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
from backend.bot.account.reauth import (
    REAUTH_REQUIRED_TITLE,
    is_reauth_required_reason,
)
from backend.bot.client_runtime.manager import bot_client
from backend.bot.notice_manager import get_bot_notice_manager
from backend.bot.client_runtime.qr_login import wait_for_qr_login as _wait_for_qr_login_flow
from backend.bot.developer_apps import get_developer_app_service
from backend.bot.handlers.core.helpers import is_valid_button_url
from backend.bot.handlers.core.helpers import truncate_text as _truncate_text
from backend.bot.handlers.core.user_link import (
    USER_MODE_ACCOUNT_SCOPED,
    USER_MODE_OWNER,
    clear_active_account_id,
    clear_scoped_account_id,
    clear_user_mode,
    get_linked_system_user_id,
    get_scoped_account_id,
    get_user_mode,
    replace_linked_system_user_id,
    set_scoped_account_id,
    set_user_mode,
    set_linked_system_user_id,
    set_active_account_id,
)
from backend.bot.handlers.task.queries import ActorAccessContext, resolve_actor_access_context, resolve_db_user_id
from backend.bot.session.redis_login_manager import LoginStatus, get_redis_login_manager
from backend.bot.state.fsm import FSMState, fsm_storage
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account, AdminAuditLog, User
from backend.h5_backend.services.auth.service import get_auth_service
from backend.h5_backend.services.licensing.service import (
    TgAccountLimitExceededError,
    bind_current_authorization_to_account_if_possible,
    grant_trial_authorization_if_eligible,
    list_user_authorizations,
)
from backend.h5_backend.services.login.service import get_login_service
from backend.h5_backend.services.me.service import get_me_service
from backend.h5_backend.services.task.service import get_task_service
from backend.bot.ui.keyboards import build_reply_shortcut_keyboard
from backend.bot.ui.messages import BOT_HELP_MANUAL
from backend.utils.security.crypto import decrypt_string_session, encrypt_string_session, get_crypto_manager

_PENDING_LOGIN_TASKS: dict[int, asyncio.Task] = {}
_PENDING_LOGIN_CLIENTS: dict[int, TelegramClient] = {}
_PENDING_LOGIN_MESSAGE_IDS: dict[int, set[int]] = {}
_QR_MESSAGE_TTL_SECONDS = 60
_HOME_REPLY_KEYBOARD_SIGNATURES: dict[int, tuple[str, ...]] = {}


def _random_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _new_login_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "bot_login_" + "".join(secrets.choice(alphabet) for _ in range(16))


def _normalize_email(raw_value: str) -> Optional[str]:
    value = (raw_value or "").strip().lower()
    return value or None


def _is_initial_password_decrypt_error(exc: Exception) -> bool:
    text = str(exc or "")
    markers = (
        "解密失败",
        "密钥不匹配",
        "密文损坏",
    )
    return any(marker in text for marker in markers)


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
    prefix = "🔄 **绑定入口已刷新**\n\n" if refreshed else "📱 **请改用手机号绑定账号**\n\n"
    return (
        prefix +
        "Bot 端已不再提供扫码绑定，请点击「📱 绑定账号」后按提示输入手机号、验证码和 Telegram 二步密码。\n"
        "绑定会话 15 分钟内有效，2 分钟内只能发起 1 次 TG 账号绑定。\n\n"
        "下一步：返回主菜单后重新点击「📱 绑定账号」继续。"
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
        return "绑定未完成，请重新点击“绑定账号”再试一次。"
    if "expired" in lowered or "过期" in raw:
        return "绑定会话已过期，请重新点击“绑定账号”开始新的流程。"
    if "password" in lowered or "二步" in raw:
        return "该账号需要输入 Telegram 二步验证密码，请按提示继续输入。"
    if "session" in lowered or "会话" in raw:
        return "绑定会话已失效，请重新点击“绑定账号”。"
    if "token" in lowered:
        return "绑定状态已失效，请重新点击“绑定账号”重新开始。"
    return raw


class BotOnboardingService:
    """Bot-first user onboarding service."""

    @staticmethod
    def _mask_login_code(buffer: str) -> str:
        value = str(buffer or "")
        return "未输入" if not value else "•" * len(value)

    @staticmethod
    def _build_login_code_buttons(login_id: str):
        return [
            [
                Button.inline("1", data="bot_login_code_digit:1"),
                Button.inline("2", data="bot_login_code_digit:2"),
                Button.inline("3", data="bot_login_code_digit:3"),
            ],
            [
                Button.inline("4", data="bot_login_code_digit:4"),
                Button.inline("5", data="bot_login_code_digit:5"),
                Button.inline("6", data="bot_login_code_digit:6"),
            ],
            [
                Button.inline("7", data="bot_login_code_digit:7"),
                Button.inline("8", data="bot_login_code_digit:8"),
                Button.inline("9", data="bot_login_code_digit:9"),
            ],
            [
                Button.inline("清空", data="bot_login_code_clear"),
                Button.inline("0", data="bot_login_code_digit:0"),
                Button.inline("删除", data="bot_login_code_backspace"),
            ],
            [
                Button.inline("✅ 提交", data="bot_login_code_submit"),
                Button.inline("🔄 重发验证码", data="bot_login_code_resend"),
            ],
            [Button.inline("⬅️ 取消绑定", data=f"bot_cancel_login:{login_id}")],
        ]

    def _build_login_code_prompt(
        self,
        *,
        phone_number: str,
        buffer: str,
        detail: Optional[str] = None,
    ) -> str:
        masked = self._mask_login_code(buffer)
        count = len(str(buffer or ""))
        current_input = f"`{masked}`（已输入 {count} 位）" if count > 0 else "`未输入`"
        lines = [
            "📨 **验证码已发送**",
            "",
            f"手机号：`{phone_number or '未记录'}`",
            "请使用下方数字按钮输入 Telegram 验证码，不要直接发送验证码消息。",
            "为避免验证码被 Telegram 判定失效，Bot 不会在聊天中接收明文验证码。",
            "",
            f"当前输入：{current_input}",
            "",
            "验证码和本次绑定会话 15 分钟内有效。",
            "若提示验证码已过期，请点击「🔄 重发验证码」后输入最新验证码。",
            "",
            "下一步：输入验证码后，若账号开启二步验证，Bot 会继续提示你输入密码。",
        ]
        if detail:
            lines[6:6] = ["", f"⚠️ {detail}"]
        return "\n".join(lines)

    async def _render_login_code_prompt(
        self,
        event,
        *,
        tg_user_id: int,
        login_id: str,
        phone_number: str,
        buffer: str,
        detail: Optional[str] = None,
    ) -> None:
        text = self._build_login_code_prompt(
            phone_number=phone_number,
            buffer=buffer,
            detail=detail,
        )
        await _send_or_edit(
            event,
            text,
            buttons=self._build_login_code_buttons(login_id),
        )
        fsm_storage.update_data(
            tg_user_id,
            login_id=login_id,
            phone_number=phone_number,
            login_code_buffer=buffer,
        )

    @staticmethod
    async def _respond_bind_start_rate_limit(event, detail: str) -> None:
        message = f"⚠️ {detail}"
        if hasattr(event, "answer"):
            try:
                await event.answer("绑定过于频繁", alert=True)
            except Exception:
                pass
        await _send_or_edit(
            event,
            message,
            buttons=[[Button.inline("⬅️ 返回主菜单", data="bot_home")]],
        )

    async def _build_primary_quick_buttons(
        self,
        *,
        include_bind: bool = True,
        include_task: bool = True,
        include_notice: bool = True,
    ) -> list[list[Any]]:
        buttons: list[list[Any]] = [
            [Button.inline("🚀 开始使用", data="bot_home"), Button.inline("📖 帮助", data="bot_help")]
        ]
        second_row: list[Any] = []
        if include_bind:
            second_row.append(Button.inline("📱 绑定账号", data="bot_login_account"))
        if second_row:
            buttons.append(second_row)
        if include_task:
            buttons.append([
                Button.inline("⏰ 创建定时任务", data="add_scheduled_task"),
                Button.inline("🖱️ 创建手动任务", data="add_manual_task"),
            ])
        if include_notice:
            notice = await get_me_service().get_public_notice_entry()
            if notice.get("enabled") and notice.get("message_text"):
                buttons.append([Button.inline(notice.get("entry_button_text") or "📢 公告栏", data="bot_notice")])
        return buttons

    @staticmethod
    def _format_notice_updated_at(raw_value: Optional[str]) -> str:
        if not raw_value:
            return "-"
        try:
            return datetime.fromisoformat(raw_value).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return raw_value

    async def show_notice(self, event, tg_user_id: int) -> None:
        result = await get_bot_notice_manager().ensure_notice_for_user(
            tg_user_id,
            force_repost=True,
        )
        if result.get("status") == "disabled":
            if hasattr(event, "answer"):
                await event.answer("当前暂无公告内容", alert=True)
                return
            await event.respond("📢 当前暂无公告内容。")
            return
        if hasattr(event, "answer"):
            await event.answer("公告已刷新，请查看最新公告消息")

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
            linked_user_id = await get_linked_system_user_id(session, tg_user_id)
            return int(linked_user_id) if linked_user_id is not None else None

    async def _get_actor_access_context(self, tg_user_id: int) -> ActorAccessContext:
        async with get_async_session() as session:
            return await resolve_actor_access_context(session, tg_user_id)

    async def _set_owner_mode(
        self,
        session,
        *,
        tg_user_id: int,
        system_user_id: int,
    ) -> None:
        await set_user_mode(session, tg_user_id, USER_MODE_OWNER)
        await clear_scoped_account_id(session, tg_user_id, system_user_id)

    async def _set_account_scoped_mode(
        self,
        session,
        *,
        tg_user_id: int,
        system_user_id: int,
        scoped_account_id: str,
    ) -> None:
        await set_user_mode(session, tg_user_id, USER_MODE_ACCOUNT_SCOPED)
        await set_scoped_account_id(session, tg_user_id, system_user_id, scoped_account_id)

    async def try_auto_claim_from_account(self, event, tg_user_id: int) -> bool:
        """Auto-claim system user by existing account.tg_user_id on first /start."""
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(Account).where(
                        Account.tg_user_id == int(tg_user_id),
                    ).order_by(
                        Account.updated_at.desc(),
                        Account.last_used_at.desc(),
                        Account.created_at.desc(),
                    )
                )
            ).scalars().all()

            if not rows:
                return False

            chosen = rows[0]
            owner_user_id = int(chosen.user_id)
            distinct_user_ids = sorted({int(item.user_id) for item in rows})

            previous_user_id = await replace_linked_system_user_id(session, int(tg_user_id), owner_user_id)
            if previous_user_id is not None:
                await clear_active_account_id(session, int(tg_user_id), int(previous_user_id))
                await clear_scoped_account_id(session, int(tg_user_id), int(previous_user_id))

            await self._set_account_scoped_mode(
                session,
                tg_user_id=int(tg_user_id),
                system_user_id=owner_user_id,
                scoped_account_id=str(chosen.account_id),
            )
            await set_active_account_id(session, int(tg_user_id), owner_user_id, str(chosen.account_id))
            await bind_current_authorization_to_account_if_possible(
                user_id=owner_user_id,
                account_id=str(chosen.account_id),
                session=session,
            )

            if len(distinct_user_ids) > 1:
                session.add(
                    AdminAuditLog(
                        actor=f"tg:{int(tg_user_id)}",
                        action="bot.auto_claim_conflict_resolved",
                        target_type="tg_user_id",
                        target_id=str(int(tg_user_id)),
                        old_value={"candidate_user_ids": distinct_user_ids},
                        new_value={
                            "selected_user_id": owner_user_id,
                            "selected_account_id": str(chosen.account_id),
                        },
                        detail={
                            "candidate_account_ids": [str(item.account_id) for item in rows[:10]],
                            "strategy": "latest_account_updated_at",
                        },
                    )
                )
                logger.warning(
                    "auto claim conflict resolved: tg_user_id={}, selected_user_id={}, selected_account_id={}, candidates={}",
                    int(tg_user_id),
                    owner_user_id,
                    str(chosen.account_id),
                    distinct_user_ids,
                )

            await session.commit()

        account_label = _account_display_name(chosen)
        _, home_buttons = await self.build_home_view(int(tg_user_id))
        await event.respond(
            "✅ **已自动识别并绑定系统账号**\n\n"
            f"当前绑定账号：{account_label}\n"
            "检测到你已在系统内存在该 Telegram 账号，已自动认领到对应系统用户。\n\n"
            "你当前处于“账号自管”模式：仅可管理自己的账号、任务和当前授权续费。\n\n"
            "下一步：请直接使用下方菜单继续操作。",
            buttons=home_buttons,
            parse_mode="markdown",
        )
        return True

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
                bot_initial_password_encrypted=get_crypto_manager().encrypt(password),
                bot_initial_password_viewable=True,
                password_changed_after_bot_registration=False,
                email=normalized_email,
                is_active=True,
            )
            session.add(user)
            await session.flush()
            await set_linked_system_user_id(session, tg_user_id, int(user.id))
            await self._set_owner_mode(
                session,
                tg_user_id=int(tg_user_id),
                system_user_id=int(user.id),
            )
            await session.commit()
            await session.refresh(user)
            return user

    async def ensure_registered_user(self, event, tg_user_id: int) -> Optional[int]:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
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
            "首次成功绑定 TG 账号后，系统会自动赠送 **7 天试用授权**。\n\n"
            "下一步：先点击下方「📱 绑定账号」绑定你的 TG 账号；7 天到期后，如需继续使用再输入卡密续费。",
            parse_mode="markdown",
            buttons=[
                [Button.inline("📱 绑定账号", data="bot_login_account"), Button.inline("🎟️ 激活卡密", data="bot_activate")],
                [Button.inline("🧾 查看授权", data="bot_authorization")],
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
            "首次成功绑定 TG 账号后，系统会自动赠送 **7 天试用授权**。\n\n"
            "下一步：先点击下方「📱 绑定账号」绑定你的 TG 账号；7 天到期后，如需继续使用再输入卡密续费。",
            parse_mode="markdown",
            buttons=[
                [Button.inline("📱 绑定账号", data="bot_login_account"), Button.inline("🎟️ 激活卡密", data="bot_activate")],
                [Button.inline("🧾 查看授权", data="bot_authorization")],
                [Button.inline("⬅️ 返回主菜单", data="bot_home")],
            ],
        )

    async def build_home_view(self, tg_user_id: int) -> tuple[str, list]:
        access_ctx = await self._get_actor_access_context(tg_user_id)
        db_user_id = access_ctx.system_user_id
        me_service = get_me_service()
        if db_user_id is None:
            text = (
                "👋 **欢迎使用全球通**\n\n"
                "全球通是你的 Telegram 定时消息管理入口。\n\n"
                "这里就是主操作入口。你可以直接在 Bot 内完成：\n"
                "1. 注册系统账号\n"
                "2. 绑定 Telegram 账号\n"
                "3. 输入卡密续费当前授权\n"
                "4. 管理任务与查看状态\n\n"
                "如果你已经在 Web 注册，也可以点击 Web 首页的「系统账号绑定到 TG Bot」按钮，直接把系统账号绑定到当前 Bot。\n\n"
                "下一步：请选择一种注册方式开始。"
            )
            buttons = [
                [
                    Button.inline("🚀 自动注册", data="bot_reg_auto"),
                    Button.inline("手动注册", data="bot_reg_manual"),
                ]
            ]
            notice = await me_service.get_public_notice_entry()
            extra_row: list[Any] = [Button.inline("📖 帮助", data="bot_help")]
            if notice.get("enabled") and notice.get("message_text"):
                extra_row.insert(0, Button.inline(notice.get("entry_button_text") or "📢 公告栏", data="bot_notice"))
            buttons.append(extra_row)
            return text, buttons

        profile = await me_service.get_profile(db_user_id)
        authorization_status = profile["authorization_status"]
        plans = profile["plans"]
        user = profile["user"]
        await me_service.get_authorization_status(db_user_id)
        accounts = await get_account_manager().get_accounts(db_user_id, is_active=True)
        if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED and access_ctx.scoped_account_id:
            accounts = [item for item in accounts if str(item.account_id) == str(access_ctx.scoped_account_id)]
        authorization_overview = profile.get("authorization_overview") or {}

        if not authorization_status["is_active"]:
            max_account_count = int(authorization_overview.get("max_account_count") or 1)
            account_count = int(authorization_overview.get("account_count") or len(accounts))
            plans_text = " / ".join(
                f"{plan['display_name']} {plan['price_yuan']}元"
                for plan in plans
            ) or "请联系管理员配置 Key 规格"
            text = (
                "⚠️ **全球通账号已注册，当前还没有可用授权**\n\n"
                f"用户名：`{user['username']}`\n"
                f"可选卡密规格：{plans_text}\n\n"
                f"当前已绑定账号：{account_count}/{max_account_count}\n"
                "未输入卡密续费时，系统仍支持绑定 1 个 TG 账号用于查看和管理，但不能执行自动发送任务。\n\n"
                "首次成功绑定 TG 账号时，系统会自动赠送 7 天试用；试用结束后需输入卡密续费当前唯一授权。\n\n"
                "下一步：可先绑定 TG 账号，或点击下方「🎟️ 激活卡密」为当前授权续费。"
            )
            buttons = await self._build_primary_quick_buttons()
            buttons.extend([
                [Button.inline("🧾 查看授权", data="bot_authorization"), Button.inline("🛒 立即购买", data="bot_purchase")],
                [Button.inline("🎟️ 激活卡密", data="bot_activate"), Button.inline("🛒 立即购买", data="bot_purchase")],
            ])
            return text, buttons

        current = authorization_status["current_authorization"] or {}
        if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED:
            scoped_display = "未命中账号"
            if accounts:
                scoped_display = _account_display_name(accounts[0])
            text = (
                "✅ **全球通已就绪（账号自管模式）**\n\n"
                f"系统用户：`{user['username']}`\n"
                f"当前账号：{scoped_display}\n"
                f"当前授权：{'已开通' if authorization_status['is_active'] else '未开通'}\n"
                f"最近到期：{current.get('end_at') or '-'}\n\n"
                "你当前只能管理自己的 TG 账号与其任务。\n"
                "可续费自己的当前授权，但不能绑定其他 TG 账号。"
            )
            buttons = await self._build_primary_quick_buttons()
            buttons.extend([
                [Button.inline("👥 查看账号", data="accounts_list"), Button.inline("🗂️ 查看任务", data="task_list")],
                [Button.inline("🧾 查看授权", data="bot_authorization")],
            ])
            return text, buttons

        account_summary = f"{authorization_overview.get('account_count', len(accounts))}/1"
        text = (
            "✅ **全球通已就绪，可以开始使用**\n\n"
            f"系统用户：`{user['username']}`\n"
            f"当前授权：{'已开通' if authorization_status['is_active'] else '未开通'}\n"
            f"最近到期：{current.get('end_at') or '-'}\n"
            f"账号数量：{account_summary}\n\n"
            "下一步：可先查看账号，或输入新的卡密续费当前授权。"
        )
        buttons = await self._build_primary_quick_buttons()
        buttons.extend([
            [Button.inline("👥 查看账号", data="accounts_list"), Button.inline("🗂️ 查看任务", data="task_list")],
            [Button.inline("🧾 查看授权", data="bot_authorization")],
        ])
        buttons.append([Button.inline("🎟️ 激活卡密", data="bot_activate"), Button.inline("🛒 立即购买", data="bot_purchase")])
        if user.get("bot_initial_password_viewable"):
            buttons.append([Button.inline("🔑 查看初始密码", data="bot_show_initial_password")])
        return text, buttons

    async def build_home_reply_keyboard(self, tg_user_id: int) -> list:
        labels = await self.get_home_reply_keyboard_labels(tg_user_id)
        return build_reply_shortcut_keyboard(labels)

    async def get_home_reply_keyboard_labels(self, tg_user_id: int) -> list[str]:
        access_ctx = await self._get_actor_access_context(tg_user_id)
        if access_ctx.system_user_id is None:
            return []
        shortcuts = await get_task_service().list_manual_shortcuts(
            access_ctx.system_user_id,
            account_id=access_ctx.scoped_account_id if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED else None,
        )
        labels = []
        for task in shortcuts[:3]:
            label = str(task.shortcut_label or "").strip() or _truncate_text(str(task.title or "快捷任务"), 20)
            labels.append(label)
        return labels

    async def sync_home_reply_keyboard(self, tg_user_id: int) -> None:
        labels = await self.get_home_reply_keyboard_labels(tg_user_id)
        signature = tuple(labels)
        previous_signature = _HOME_REPLY_KEYBOARD_SIGNATURES.get(int(tg_user_id))
        if previous_signature == signature:
            return

        _HOME_REPLY_KEYBOARD_SIGNATURES[int(tg_user_id)] = signature
        keyboard = Button.clear() if not labels else build_reply_shortcut_keyboard(labels)
        await bot_client.send_message(tg_user_id, "\u2063", buttons=keyboard)

    async def show_home(self, event, tg_user_id: int) -> None:
        text, buttons = await self.build_home_view(tg_user_id)
        await _send_or_edit(event, text, buttons=buttons)
        if int(tg_user_id) not in _HOME_REPLY_KEYBOARD_SIGNATURES:
            await self.sync_home_reply_keyboard(tg_user_id)

    async def show_help(self, event, tg_user_id: int) -> None:
        text = BOT_HELP_MANUAL
        buttons = []
        notice = await get_me_service().get_public_notice_entry()
        if notice.get("enabled") and notice.get("message_text"):
            buttons.append([Button.inline(notice.get("entry_button_text") or "📢 公告栏", data="bot_notice")])
        buttons.append([Button.inline("📱 绑定账号", data="bot_login_account")])
        buttons.append([Button.inline("⏰ 创建定时任务", data="add_scheduled_task"), Button.inline("🖱️ 创建手动任务", data="add_manual_task")])
        buttons.append([Button.inline("🏠 返回主菜单", data="bot_home")])
        await _send_or_edit(event, text, buttons=buttons)

    async def _respond_license_error(self, event, message: str) -> None:
        if hasattr(event, "answer"):
            await event.answer(message, alert=True)
            return
        await event.respond(
            f"⚠️ {message}",
            buttons=[
                [Button.inline("🧾 查看授权", data="bot_authorization"), Button.inline("🛒 立即购买", data="bot_purchase")],
                [Button.inline("⬅️ 返回主菜单", data="bot_home")],
            ],
        )

    async def show_purchase(self, event, tg_user_id: int) -> None:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return
        me_service = get_me_service()
        status = await me_service.get_authorization_status(db_user_id)
        purchase = status["purchase"]
        plans_text = "\n".join(
            f"• {plan['display_name']}：{plan['price_yuan']} 元 / {plan['duration_days']} 天"
            for plan in status["plans"]
        ) or "• 暂无可用卡密规格"

        text = (
            "💳 **全球通购买指引**\n\n"
            f"{plans_text}\n\n"
            "如需继续使用，请点击下方按钮前往 Telegram 购买入口购买全球通卡密。\n\n"
            "下一步：完成购买后，返回 Bot 输入卡密续费当前授权。"
        )
        buttons = [[Button.inline("⬅️ 返回主菜单", data="bot_home")]]
        purchase_url = (purchase.get("url") or "").strip()
        if is_valid_button_url(purchase_url):
            buttons.insert(0, [Button.url(purchase.get("button_text") or "立即购买", purchase_url)])
        else:
            text = f"{text}\n\n购买链接：{purchase_url or '未配置'}"
        await _send_or_edit(event, text, buttons=buttons)

    async def show_initial_password(self, event, tg_user_id: int) -> None:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            await self.auto_register(event, tg_user_id)
            return
        me_service = get_me_service()
        try:
            password = await me_service.get_bot_initial_password(db_user_id)
        except ValueError as exc:
            if not _is_initial_password_decrypt_error(exc):
                raise

            logger.warning(
                "Bot 初始密码读取失败，已触发按需重置: tg_user_id={}, user_id={}",
                tg_user_id,
                db_user_id,
            )
            new_password = await me_service.reset_corrupted_bot_initial_password(db_user_id)
            await _send_or_edit(
                event,
                "🔐 **登录密码已重置**\n\n"
                "检测到历史初始密码数据异常，系统已为你重置 Web 登录密码。\n\n"
                f"新密码：`{new_password}`\n\n"
                "该密码仅发送这一次，请尽快登录 Web 后立即修改密码。",
                buttons=[[Button.inline("⬅️ 返回主菜单", data="bot_home")]],
                parse_mode="markdown",
            )
            return
        if not password:
            await _send_or_edit(
                event,
                "🔑 **初始密码不可查看**\n\n"
                "当前系统账号没有可查看的 Bot 初始密码。\n"
                "如果你已经修改过密码，初始密码查看权限会自动失效。\n\n"
                "下一步：请使用当前密码登录 Web，或在后台重置密码。",
                buttons=[[Button.inline("⬅️ 返回主菜单", data="bot_home")]],
            )
            return
        await _send_or_edit(
            event,
            "🔑 **Bot 自动注册初始密码**\n\n"
            f"初始密码：`{password}`\n\n"
            "这是 Bot 自动注册时生成的初始密码。\n"
            "一旦你在 Web 修改密码，这里将不能再查看。\n\n"
            "下一步：如需安全起见，请尽快到 Web 修改密码。",
            buttons=[[Button.inline("⬅️ 返回主菜单", data="bot_home")]],
            parse_mode="markdown",
        )

    async def show_authorization_overview(self, event, tg_user_id: int) -> None:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return
        me_service = get_me_service()
        status = await me_service.get_authorization_status(db_user_id)
        profile = await me_service.get_profile(db_user_id)
        current = status["current_authorization"] or {}
        overview = profile.get("authorization_overview") or {}
        authorization_lines = []
        if current:
            authorization_lines.append(
                f"状态：{'🟢 生效中' if current.get('status') == 'active' else '⚪️ 已到期'}\n"
                f"绑定账号：{current.get('account_name') or current.get('account_id') or '未绑定 TG 账号'}\n"
                f"开始时间：{current.get('start_at') or '-'}\n"
                f"到期时间：{current.get('end_at') or '-'}\n"
                f"授权来源：{current.get('grant_source_label') or '-'}\n"
                f"首张卡密：{current.get('source_card_code_masked') or '-'}\n"
                f"最近续费：{current.get('latest_card_code_masked') or '-'}"
            )

        text = (
            "💳 **全球通当前授权**\n\n"
            f"状态：{'当前授权有效' if status['is_active'] else '当前还没有有效授权'}\n"
            f"系统账号已绑定 TG 数：{overview.get('account_count', 0)}/1\n"
            f"最近到期：{current.get('end_at') or '-'}\n"
            f"剩余天数：{status.get('remain_days') if status.get('remain_days') is not None else '-'}\n\n"
            f"{chr(10).join(authorization_lines) if authorization_lines else '当前还没有授权记录；首次成功绑定 TG 账号时会自动赠送 7 天试用。'}\n\n"
            "到期后 TG 账号会保持登录，但自动发送任务会暂停。\n\n"
            "下一步：如需继续使用，请输入新的卡密续费当前授权。"
        )
        buttons = [[Button.inline("⬅️ 返回主菜单", data="bot_home")]]
        if current:
            buttons.insert(0, [Button.inline("💳 续费当前授权", data="authorization_renew")])
        purchase = status.get("purchase") or {}
        if not status["is_active"]:
            buttons.insert(0, [Button.inline("🎟️ 激活卡密", data="bot_activate")])
        if not status["is_active"] and is_valid_button_url((purchase.get("url") or "").strip()):
            buttons.insert(0, [Button.url(purchase.get("button_text") or "立即购买", purchase["url"])])
        await _send_or_edit(event, text, buttons=buttons)

    async def show_activation_menu(self, event, tg_user_id: int) -> None:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return
        text = (
            "💳 **激活卡密**\n\n"
            "当前版本已改为单系统账号单 TG 账号授权。\n"
            "卡密只会用于续费当前唯一授权，不再新开第二条授权。\n\n"
            "下一步：点击下方按钮后，直接输入卡密即可续费。"
        )
        buttons = [
            [Button.inline("💳 输入卡密", data="bot_activate_renew")],
            [Button.inline("🧾 查看授权", data="bot_authorization"), Button.inline("⬅️ 返回主菜单", data="bot_home")],
        ]
        await _send_or_edit(event, text, buttons=buttons)

    async def start_activation(self, event, tg_user_id: int) -> None:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return
        fsm_storage.set_state(tg_user_id, FSMState.WAIT_ACTIVATION_CODE)
        fsm_storage.update_data(tg_user_id)
        await _send_or_edit(
            event,
            "💳 **输入卡密续费授权**\n\n请输入发卡系统提供的卡密。\n"
            "如果暂时不想继续，发送 `/cancel` 可返回主菜单。\n\n"
            "下一步：输入成功后会立即续费你当前系统账号下的唯一授权。",
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
            buttons = [[Button.inline("⬅️ 返回主菜单", data="bot_home")]]
            purchase = await me_service.get_authorization_status(db_user_id)
            purchase_meta = purchase.get("purchase") or {}
            purchase_url = (purchase_meta.get("url") or "").strip()
            if is_valid_button_url(purchase_url):
                buttons.insert(0, [Button.url(purchase_meta.get("button_text") or "立即购买", purchase_url)])
            await event.respond(
                f"❌ 激活失败：{exc.detail}\n"
                "下一步：请核对激活码后重新输入，或点击「🛒 立即购买」获取新的激活码。"
                + ("\n\n购买链接未配置，请联系管理员。" if not is_valid_button_url(purchase_url) else ""),
                buttons=buttons,
            )
            return

        fsm_storage.reset_state(tg_user_id)
        current = status.get("current_authorization") or {}
        await event.respond(
            (
                "✅ **全球通授权续费成功**\n\n"
                + f"最近到期时间：{current.get('end_at') or '-'}\n"
                + f"当前授权：{'已开通' if status.get('is_active') else '未开通'}\n\n"
                + "下一步：点击下方「👥 查看账号」，继续查看当前绑定 TG 账号或创建定时/手动任务。"
            ),
            parse_mode="markdown",
            buttons=[
                [Button.inline("👥 查看账号", data="accounts_list"), Button.inline("🧾 查看授权", data="bot_authorization")],
                [Button.inline("⬅️ 返回主菜单", data="bot_home")],
            ],
        )

    async def bind_system_account(self, event, tg_user_id: int, bind_token: str) -> None:
        login_manager = get_redis_login_manager()
        system_user_id = await login_manager.consume_system_bind_token(bind_token)
        if system_user_id is None:
            await event.respond("❌ 绑定失败：绑定入口已失效，请回到 Web 首页重新点击“系统账号绑定到 TG Bot”。")
            return

        account_manager = get_account_manager()
        accounts = await account_manager.get_accounts(int(system_user_id), is_active=True)
        preferred_account_id = accounts[0].account_id if accounts else None
        async with get_async_session() as session:
            previous_user_id = await replace_linked_system_user_id(session, int(tg_user_id), int(system_user_id))
            if previous_user_id is not None:
                await clear_active_account_id(session, int(tg_user_id), int(previous_user_id))
                await clear_scoped_account_id(session, int(tg_user_id), int(previous_user_id))
            await self._set_owner_mode(
                session,
                tg_user_id=int(tg_user_id),
                system_user_id=int(system_user_id),
            )
            if preferred_account_id:
                await set_active_account_id(session, int(tg_user_id), int(system_user_id), preferred_account_id)
            await session.commit()
        await event.respond(
            "✅ **系统账号已绑定到当前 Bot**\n\n"
            "后续你可以在这里统一查看该系统账号下的 TG 账号状态、当前授权状态和任务状态。\n\n"
            "下一步：点击下方按钮进入主菜单。",
            parse_mode="markdown",
            buttons=[[Button.inline("⬅️ 进入主菜单", data="bot_home")]],
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
        buttons = [[Button.inline("⬅️ 取消绑定", data=f"bot_cancel_login:{login_id}")]]
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

    async def _send_login_success_message(
        self,
        *,
        tg_user_id: int,
        db_user_id: int,
        account_id: str,
        sync_queue_status: Optional[str] = None,
        trial_authorization: Optional[dict[str, Any]] = None,
    ) -> None:
        account_manager = get_account_manager()
        account = await account_manager.get_account(str(account_id))
        if not account:
            await bot_client.send_message(tg_user_id, "❌ 登录已完成，但账号状态读取失败，请稍后刷新账号页。")
            return

        me_service = get_me_service()
        status = await me_service.get_authorization_status(db_user_id)
        current = status.get("current_authorization") or {}
        trial_text = ""
        if trial_authorization:
            trial_text = (
                f"🎁 已自动开通 **7 天试用授权**\n"
                f"试用到期：{trial_authorization.get('end_at') or '-'}\n\n"
            )
        sync_text = "⏳ 已加入自动同步队列，系统会依次同步账号资料和资源。\n\n"
        if sync_queue_status in {"queued", "running"}:
            sync_text = "⏳ 该账号正在同步中，系统会继续自动完成账号资料和资源刷新。\n\n"
        await bot_client.send_message(
            tg_user_id,
            "✅ **全球通登录并绑定成功**\n\n"
            f"账号：{_account_display_name(account)}\n"
            f"Telegram UID：`{account.tg_user_id or '-'}`\n"
            f"{trial_text}"
            f"{sync_text}"
            f"剩余天数：{status.get('remain_days') if status.get('remain_days') is not None else '-'}\n"
            f"到期时间：{current.get('end_at') or '-'}\n\n"
            "下一步：可继续查看账号、创建定时/手动任务或查看当前授权状态。",
            parse_mode="markdown",
            buttons=[
                [Button.inline("👥 查看账号", data="accounts_list"), Button.inline("🗂️ 查看任务", data="task_list")],
                [Button.inline("🧾 查看授权", data="bot_authorization"), Button.inline("⬅️ 返回主菜单", data="bot_home")],
            ],
        )

    async def start_account_login(
        self,
        event,
        tg_user_id: int,
        *,
        existing_tg_user_id: Optional[int] = None,
    ) -> None:
        access_ctx = await self._get_actor_access_context(tg_user_id)
        db_user_id = access_ctx.system_user_id
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return
        if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED and existing_tg_user_id is None:
            existing_tg_user_id = int(tg_user_id)
        elif existing_tg_user_id is None:
            existing_account = await self._get_latest_bound_account_snapshot(db_user_id)
            if existing_account is not None:
                await self.prompt_replace_account_before_login(
                    event,
                    tg_user_id,
                    account_id=str(existing_account["account_id"]),
                    account_label=str(existing_account["label"]),
                )
                return
        await self.start_phone_account_login(
            event,
            tg_user_id,
            existing_tg_user_id=existing_tg_user_id,
        )

    async def _get_latest_bound_account_snapshot(self, db_user_id: int, *, account_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        async with get_async_session() as session:
            stmt = (
                select(Account)
                .where(
                    Account.user_id == int(db_user_id),
                    Account.is_active.is_(True),
                )
                .order_by(Account.updated_at.desc(), Account.created_at.desc())
                .limit(1)
            )
            if account_id:
                stmt = stmt.where(Account.account_id == str(account_id))
            account = (await session.execute(stmt)).scalar_one_or_none()
            if account is None:
                return None
            label = f"@{account.username}" if account.username else (account.phone or str(account.tg_user_id or account.account_id))
            return {
                "account_id": str(account.account_id),
                "label": label,
                "tg_user_id": int(account.tg_user_id or 0),
                "reauth_required": bool(getattr(account, "reauth_required", False)),
                "reauth_reason": str(getattr(account, "reauth_reason", "") or ""),
            }

    async def prompt_replace_account_before_login(
        self,
        event,
        tg_user_id: int,
        *,
        account_id: str,
        account_label: Optional[str] = None,
    ) -> None:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return
        snapshot = await self._get_latest_bound_account_snapshot(db_user_id, account_id=account_id)
        if snapshot is None:
            await self.start_phone_account_login(event, tg_user_id)
            return

        label = account_label or str(snapshot["label"])
        needs_reauth = bool(snapshot.get("reauth_required")) or is_reauth_required_reason(str(snapshot.get("reauth_reason") or ""))
        intro_text = ""
        if needs_reauth:
            intro_text = f"⚠️ **{REAUTH_REQUIRED_TITLE}**\n\n"
        text = (
            f"{intro_text}⚠️ **确认更换绑定账号**\n\n"
            f"当前已绑定账号：{label}\n"
            f"账号ID：`{snapshot['account_id']}`\n\n"
            "继续前需要先解除当前绑定。解除后，该账号及相关任务会被删除，然后立即进入新的手机号绑定流程。\n\n"
            "是否继续？"
        )
        buttons = [
            [Button.inline("确认解除并继续绑定", data=f"bot_login_replace_confirm:{snapshot['account_id']}")],
            [Button.inline("查看当前账号", data=f"acc_menu:{snapshot['account_id']}"), Button.inline("⬅️ 返回主菜单", data="bot_home")],
        ]
        await _send_or_edit(event, text, buttons=buttons)

    async def replace_account_and_start_login(self, event, tg_user_id: int, *, account_id: str) -> None:
        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return
        snapshot = await self._get_latest_bound_account_snapshot(db_user_id, account_id=account_id)
        if snapshot is None:
            await self.start_phone_account_login(event, tg_user_id)
            return

        manager = get_account_manager()
        ok = await manager.delete_account(str(snapshot["account_id"]))
        if not ok:
            if hasattr(event, "answer"):
                await event.answer("解除绑定失败，请刷新后重试。", alert=True)
            return

        if hasattr(event, "answer"):
            await event.answer("已解除当前绑定，开始新的绑定流程。")
        await self.start_phone_account_login(event, tg_user_id)

    async def start_qr_account_login(
        self,
        event,
        tg_user_id: int,
        *,
        existing_tg_user_id: Optional[int] = None,
    ) -> None:
        access_ctx = await self._get_actor_access_context(tg_user_id)
        db_user_id = access_ctx.system_user_id
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return
        if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED and existing_tg_user_id is None:
            # 账号自管模式下，主菜单“绑定账号”仅用于登录/重登当前 Telegram 账号。
            existing_tg_user_id = int(tg_user_id)

        me_service = get_me_service()
        try:
            await me_service.ensure_can_add_tg_account(
                db_user_id,
                existing_tg_user_id=existing_tg_user_id,
            )
        except HTTPException as exc:
            await self._respond_license_error(event, str(exc.detail))
            return
        except TgAccountLimitExceededError as exc:
            await self._respond_limit_error(
                event,
                tg_user_id,
                limit_message=str(exc),
            )
            return
        try:
            await get_login_service().enforce_bind_start_cooldown(user_id=db_user_id)
        except HTTPException as exc:
            if exc.status_code == 429:
                await self._respond_bind_start_rate_limit(event, str(exc.detail))
                return
            raise

        await self._cancel_existing_login_task(tg_user_id)

        developer_service = get_developer_app_service()
        credentials = await developer_service.choose_login_credentials_for_user(
            db_user_id,
            existing_tg_user_id=existing_tg_user_id,
        )
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
        qr_login = await login_client.qr_login()
        await login_manager.update_qr_url(login_id, qr_login.url)
        await login_manager.update_status(login_id, LoginStatus.PENDING)

        _PENDING_LOGIN_CLIENTS[tg_user_id] = login_client
        task = asyncio.create_task(
            self._run_login_watcher(
                tg_user_id,
                db_user_id,
                login_id,
                qr_login,
                login_client,
                expected_tg_user_id=existing_tg_user_id,
            )
        )
        _PENDING_LOGIN_TASKS[tg_user_id] = task
        await self._send_login_qr_message(
            tg_user_id=tg_user_id,
            login_id=login_id,
            qr_url=qr_login.url,
            refreshed=False,
        )

        if hasattr(event, "answer"):
            await event.answer("Bot 端已切换为手机号绑定，请查看最新消息")

    async def start_phone_account_login(
        self,
        event,
        tg_user_id: int,
        *,
        existing_tg_user_id: Optional[int] = None,
    ) -> None:
        access_ctx = await self._get_actor_access_context(tg_user_id)
        db_user_id = access_ctx.system_user_id
        if db_user_id is None:
            await self.show_home(event, tg_user_id)
            return
        if access_ctx.mode == USER_MODE_ACCOUNT_SCOPED and existing_tg_user_id is None:
            existing_tg_user_id = int(tg_user_id)

        me_service = get_me_service()
        try:
            await me_service.ensure_can_add_tg_account(
                db_user_id,
                existing_tg_user_id=existing_tg_user_id,
            )
        except HTTPException as exc:
            await self._respond_license_error(event, str(exc.detail))
            return
        except TgAccountLimitExceededError as exc:
            await self._respond_limit_error(event, tg_user_id, limit_message=str(exc))
            return

        await self._cancel_existing_login_task(tg_user_id)
        try:
            login_session = await get_login_service().create_phone_login_session(
                db_user_id,
                existing_tg_user_id=existing_tg_user_id,
            )
        except HTTPException as exc:
            if exc.status_code == 429:
                await self._respond_bind_start_rate_limit(event, str(exc.detail))
                return
            await self._respond_license_error(event, str(exc.detail))
            return
        login_id = str(login_session["login_id"])
        fsm_storage.set_state(tg_user_id, FSMState.WAIT_LOGIN_PHONE)
        fsm_storage.update_data(
            tg_user_id,
            login_id=login_id,
            expected_tg_user_id=existing_tg_user_id,
            login_mode="phone_code",
        )
        prompt = await bot_client.send_message(
            tg_user_id,
            "📱 **手机号绑定**\n\n"
            "请直接回复 Telegram 绑定手机号，需包含国家区号。\n"
            "示例：`+8613812345678`\n\n"
            "本次绑定会话 15 分钟内有效。\n"
            "为避免误绑定，2 分钟内只能发起 1 次 TG 账号绑定。\n\n"
            "下一步：发送手机号后，Bot 会向 Telegram 发起验证码绑定。",
            parse_mode="markdown",
            buttons=[[Button.inline("⬅️ 取消绑定", data=f"bot_cancel_login:{login_id}")]],
        )
        _track_login_message(tg_user_id, prompt)
        if hasattr(event, "answer"):
            await event.answer("请直接发送手机号")

    async def _run_login_watcher(
        self,
        tg_user_id: int,
        db_user_id: int,
        login_id: str,
        qr_login,
        login_client: TelegramClient,
        *,
        expected_tg_user_id: Optional[int] = None,
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
                await bot_client.send_message(tg_user_id, "⚠️ 绑定会话已失效，请重新发起绑定。")
                return

            if session.status == LoginStatus.PASSWORD_REQUIRED:
                hint = f"\n密码提示：`{session.password_hint}`" if session.password_hint else ""
                fsm_storage.set_state(tg_user_id, FSMState.WAIT_LOGIN_PASSWORD)
                fsm_storage.update_data(
                    tg_user_id,
                    login_id=login_id,
                    expected_tg_user_id=expected_tg_user_id,
                )
                password_prompt = await bot_client.send_message(
                    tg_user_id,
                    "🔒 **该账号开启了二步验证**\n\n"
                    "请直接回复 Telegram 二步密码。\n"
                    "收到后系统会立即删除你的密码消息，不会在聊天里保留明文。"
                    f"{hint}\n\n下一步：输入正确密码后，系统会自动完成绑定。",
                    parse_mode="markdown",
                    buttons=[[Button.inline("⬅️ 取消绑定", data=f"bot_cancel_login:{login_id}")]],
                )
                _track_login_message(tg_user_id, password_prompt)
                return

            if session.status == LoginStatus.CONFIRMED:
                if expected_tg_user_id is not None and int(session.tg_user_id or 0) != int(expected_tg_user_id):
                    await login_manager.update_status(
                        login_id,
                        LoginStatus.ERROR,
                        error="当前登录方式仅允许验证指定的 Telegram 账号",
                    )
                    await bot_client.send_message(
                        tg_user_id,
                        "❌ 当前登录方式仅允许验证指定的 Telegram 账号，请重新选择正确账号后再试。",
                    )
                    return
                await self._finalize_bound_account(
                    tg_user_id=tg_user_id,
                    db_user_id=db_user_id,
                    login_id=login_id,
                )
                return

            if session.status == LoginStatus.EXPIRED:
                await _clear_tracked_login_messages(tg_user_id, delete=True)
                await bot_client.send_message(tg_user_id, "⚠️ 绑定流程已过期，请重新点击“绑定账号”开始新的手机号绑定。")
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
                "❌ 绑定流程异常，请稍后重新点击“绑定账号”再试一次。",
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
            await event.answer("已取消绑定")
        await self.show_home(event, tg_user_id)

    async def _finalize_bound_account(self, *, tg_user_id: int, db_user_id: int, login_id: str) -> None:
        login_service = get_login_service()
        try:
            finalized = await login_service._upsert_login_account(
                login_id=login_id,
                user_id=db_user_id,
                actor_tg_user_id=tg_user_id,
            )
        except TgAccountLimitExceededError as exc:
            await bot_client.send_message(
                tg_user_id,
                f"⚠️ {exc}\n\n下一步：可删除闲置账号，或购买并输入新的卡密。",
            )
            return
        except HTTPException as exc:
            await bot_client.send_message(tg_user_id, f"❌ 登录已完成，但系统账号绑定失败：{exc.detail}")
            return
        await self._send_login_success_message(
            tg_user_id=tg_user_id,
            db_user_id=db_user_id,
            account_id=str(finalized["account_id"]),
            sync_queue_status=finalized.get("sync_queue_status"),
            trial_authorization=finalized.get("trial_authorization"),
        )
        await _clear_tracked_login_messages(tg_user_id, delete=False)
        fsm_storage.reset_state(tg_user_id)

    async def _respond_limit_error(self, event, tg_user_id: int, *, limit_message: str) -> None:
        text = f"⚠️ {limit_message}\n\n下一步：可删除已绑定账号，或购买并输入新的卡密。"
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

    async def handle_login_phone(self, event, tg_user_id: int, text: str) -> None:
        phone = (text or "").strip()
        data = fsm_storage.get_data(tg_user_id)
        login_id = str(data.get("login_id") or "").strip()
        if phone.lower() == "/cancel":
            await self.cancel_login(event, tg_user_id, login_id or None)
            return
        if not login_id:
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(tg_user_id, "⚠️ 绑定会话已失效。\n下一步：请重新点击「📱 绑定账号」。")
            return

        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            fsm_storage.reset_state(tg_user_id)
            await self.show_home(event, tg_user_id)
            return

        try:
            result = await get_login_service().submit_phone_number_data(
                login_id=login_id,
                user_id=db_user_id,
                phone_number=phone,
            )
        except HTTPException as exc:
            await bot_client.send_message(tg_user_id, f"❌ {exc.detail}")
            return

        fsm_storage.set_state(tg_user_id, FSMState.WAIT_LOGIN_CODE)
        fsm_storage.update_data(
            tg_user_id,
            login_id=login_id,
            expected_tg_user_id=data.get("expected_tg_user_id"),
            login_mode="phone_code",
            phone_number=result.get("phone_number") or phone,
            login_code_buffer="",
        )
        logger.info(
            "bot login code keypad ready: sender={}, login_id={}, phone={}",
            tg_user_id,
            login_id,
            result.get("phone_number") or phone,
        )
        message = await bot_client.send_message(
            tg_user_id,
            self._build_login_code_prompt(
                phone_number=result.get("phone_number") or phone,
                buffer="",
            ),
            parse_mode="markdown",
            buttons=self._build_login_code_buttons(login_id),
        )
        fsm_storage.update_data(tg_user_id, login_code_message_id=getattr(message, "id", None))
        _track_login_message(tg_user_id, message)

    async def handle_login_code(self, event, tg_user_id: int, text: str) -> None:
        code = (text or "").strip()
        data = fsm_storage.get_data(tg_user_id)
        login_id = str(data.get("login_id") or "").strip()
        if code.lower() == "/cancel":
            await self.cancel_login(event, tg_user_id, login_id or None)
            return
        if not login_id:
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(tg_user_id, "⚠️ 绑定会话已失效。\n下一步：请重新点击「📱 绑定账号」。")
            return
        await bot_client.send_message(
            tg_user_id,
            "⚠️ 为避免验证码失效，请不要把验证码作为消息发送。请使用下方数字按钮输入。",
        )

    async def handle_login_code_digit(self, event, tg_user_id: int, digit: str) -> None:
        if digit not in "0123456789":
            if hasattr(event, "answer"):
                await event.answer("验证码数字无效", alert=True)
            return
        data = fsm_storage.get_data(tg_user_id)
        login_id = str(data.get("login_id") or "").strip()
        if not login_id:
            if hasattr(event, "answer"):
                await event.answer("绑定会话已失效，请重新开始。", alert=True)
            return
        buffer = f"{data.get('login_code_buffer') or ''}{digit}"
        logger.info(
            "bot login code digit appended: sender={}, login_id={}, digits={}",
            tg_user_id,
            login_id,
            len(buffer),
        )
        await self._render_login_code_prompt(
            event,
            tg_user_id=tg_user_id,
            login_id=login_id,
            phone_number=str(data.get("phone_number") or ""),
            buffer=buffer,
        )

    async def handle_login_code_backspace(self, event, tg_user_id: int) -> None:
        data = fsm_storage.get_data(tg_user_id)
        login_id = str(data.get("login_id") or "").strip()
        if not login_id:
            if hasattr(event, "answer"):
                await event.answer("绑定会话已失效，请重新开始。", alert=True)
            return
        buffer = str(data.get("login_code_buffer") or "")
        if not buffer:
            if hasattr(event, "answer"):
                await event.answer("当前没有可删除的数字")
            return
        await self._render_login_code_prompt(
            event,
            tg_user_id=tg_user_id,
            login_id=login_id,
            phone_number=str(data.get("phone_number") or ""),
            buffer=buffer[:-1],
        )

    async def handle_login_code_clear(self, event, tg_user_id: int) -> None:
        data = fsm_storage.get_data(tg_user_id)
        login_id = str(data.get("login_id") or "").strip()
        if not login_id:
            if hasattr(event, "answer"):
                await event.answer("绑定会话已失效，请重新开始。", alert=True)
            return
        buffer = str(data.get("login_code_buffer") or "")
        if not buffer:
            if hasattr(event, "answer"):
                await event.answer("当前验证码输入已为空")
            return
        await self._render_login_code_prompt(
            event,
            tg_user_id=tg_user_id,
            login_id=login_id,
            phone_number=str(data.get("phone_number") or ""),
            buffer="",
        )

    async def handle_login_code_resend(self, event, tg_user_id: int) -> None:
        data = fsm_storage.get_data(tg_user_id)
        login_id = str(data.get("login_id") or "").strip()
        phone_number = str(data.get("phone_number") or "").strip()
        if not login_id or not phone_number:
            if hasattr(event, "answer"):
                await event.answer("绑定会话已失效，请重新开始。", alert=True)
            return

        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            fsm_storage.reset_state(tg_user_id)
            await self.show_home(event, tg_user_id)
            return

        try:
            result = await get_login_service().submit_phone_number_data(
                login_id=login_id,
                user_id=db_user_id,
                phone_number=phone_number,
            )
        except HTTPException as exc:
            await self._render_login_code_prompt(
                event,
                tg_user_id=tg_user_id,
                login_id=login_id,
                phone_number=phone_number,
                buffer=str(data.get("login_code_buffer") or ""),
                detail=str(exc.detail),
            )
            return

        logger.info(
            "bot login code resent: sender={}, login_id={}, phone={}",
            tg_user_id,
            login_id,
            result.get("phone_number") or phone_number,
        )
        await self._render_login_code_prompt(
            event,
            tg_user_id=tg_user_id,
            login_id=login_id,
            phone_number=result.get("phone_number") or phone_number,
            buffer="",
            detail="验证码已重新发送，请输入最新验证码。",
        )

    async def submit_login_code_by_keypad(self, event, tg_user_id: int) -> None:
        data = fsm_storage.get_data(tg_user_id)
        login_id = str(data.get("login_id") or "").strip()
        code = str(data.get("login_code_buffer") or "").strip()
        if not login_id:
            if hasattr(event, "answer"):
                await event.answer("绑定会话已失效，请重新开始。", alert=True)
            return
        if not code:
            if hasattr(event, "answer"):
                await event.answer("请先输入验证码", alert=True)
            return

        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            fsm_storage.reset_state(tg_user_id)
            await self.show_home(event, tg_user_id)
            return

        logger.info(
            "bot login code submitted: sender={}, login_id={}, digits={}",
            tg_user_id,
            login_id,
            len(code),
        )
        try:
            result = await get_login_service().submit_phone_code_data(
                login_id=login_id,
                user_id=db_user_id,
                code=code,
                expected_tg_user_id=data.get("expected_tg_user_id"),
                input_mode="callback_keypad",
            )
        except HTTPException as exc:
            latest = await get_redis_login_manager().get_session(login_id)
            if latest is None or latest.status == LoginStatus.ERROR:
                fsm_storage.reset_state(tg_user_id)
                await bot_client.send_message(
                    tg_user_id,
                    f"❌ {exc.detail}\n\n下一步：请重新点击「📱 绑定账号」开始新的手机号绑定。",
                )
                return
            await self._render_login_code_prompt(
                event,
                tg_user_id=tg_user_id,
                login_id=login_id,
                phone_number=str(data.get("phone_number") or ""),
                buffer=code,
                detail=str(exc.detail),
            )
            return

        if result.get("status") == LoginStatus.PASSWORD_REQUIRED.value:
            fsm_storage.set_state(tg_user_id, FSMState.WAIT_LOGIN_PASSWORD)
            fsm_storage.update_data(
                tg_user_id,
                login_id=login_id,
                expected_tg_user_id=data.get("expected_tg_user_id"),
                login_mode="phone_code",
                login_code_buffer="",
            )
            hint = f"\n密码提示：`{result.get('password_hint')}`" if result.get("password_hint") else ""
            await _send_or_edit(
                event,
                "🔒 **该账号开启了二步验证**\n\n"
                "请直接回复 Telegram 二步密码。\n"
                "收到后系统会立即删除你的密码消息，不会在聊天里保留明文。"
                f"{hint}\n\n"
                "当前绑定会话 15 分钟内有效，请尽快完成。\n\n"
                "下一步：输入正确密码后，系统会自动完成绑定。",
                buttons=[[Button.inline("⬅️ 取消绑定", data=f"bot_cancel_login:{login_id}")]],
                parse_mode="markdown",
            )
            return

        await self._send_login_success_message(
            tg_user_id=tg_user_id,
            db_user_id=db_user_id,
            account_id=str(result["account_id"]),
            trial_authorization=result.get("trial_authorization"),
        )
        await _clear_tracked_login_messages(tg_user_id, delete=False)
        fsm_storage.reset_state(tg_user_id)

    async def handle_login_password(self, event, tg_user_id: int, text: str) -> None:
        password = (text or "").strip()
        if password.lower() == "/cancel":
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(tg_user_id, "⚠️ 已取消输入二步密码。\n下一步：如需继续，请重新点击「📱 绑定账号」。")
            await _send_main_menu_to_actor(tg_user_id)
            return

        data = fsm_storage.get_data(tg_user_id)
        login_id = str(data.get("login_id") or "").strip()
        if not login_id:
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(tg_user_id, "⚠️ 绑定会话已失效。\n下一步：请重新点击「📱 绑定账号」。")
            return

        db_user_id = await self._get_db_user_id(tg_user_id)
        if db_user_id is None:
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(
                tg_user_id,
                "⚠️ 当前 Telegram 账号还未绑定系统账号。\n下一步：请先发送 /start，或回到 Web 首页点击“系统账号绑定到 TG Bot”。",
            )
            return

        login_manager = get_redis_login_manager()
        session = await login_manager.get_session(login_id)
        if not session:
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(tg_user_id, "⚠️ 绑定会话不存在。\n下一步：请重新点击「📱 绑定账号」。")
            return
        if session.status != LoginStatus.PASSWORD_REQUIRED:
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(tg_user_id, "⚠️ 当前绑定会话无需输入密码。\n下一步：请重新点击「📱 绑定账号」。")
            return
        if not session.pending_session_encrypted:
            fsm_storage.reset_state(tg_user_id)
            await bot_client.send_message(tg_user_id, "⚠️ 会话缺少待验证状态。\n下一步：请重新点击「📱 绑定账号」。")
            return
        try:
            result = await get_login_service().submit_password_data(
                login_id=login_id,
                user_id=db_user_id,
                password=password,
                expected_tg_user_id=data.get("expected_tg_user_id"),
            )
        except HTTPException as exc:
            latest = await login_manager.get_session(login_id)
            if latest is None or latest.status == LoginStatus.ERROR:
                fsm_storage.reset_state(tg_user_id)
                await bot_client.send_message(
                    tg_user_id,
                    f"❌ {exc.detail}\n\n下一步：请重新点击「📱 绑定账号」后再试一次。",
                )
                return
            await bot_client.send_message(tg_user_id, f"❌ {exc.detail}")
            return

        await self._send_login_success_message(
            tg_user_id=tg_user_id,
            db_user_id=db_user_id,
            account_id=str(result["account_id"]),
            trial_authorization=result.get("trial_authorization"),
        )
        await _clear_tracked_login_messages(tg_user_id, delete=False)
        fsm_storage.reset_state(tg_user_id)


_service: Optional[BotOnboardingService] = None


def get_onboarding_service() -> BotOnboardingService:
    """Get singleton onboarding service."""
    global _service
    if _service is None:
        _service = BotOnboardingService()
    return _service
