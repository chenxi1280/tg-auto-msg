"""Telegram clients bootstrap and QR-login API surface."""
from __future__ import annotations

from telethon import TelegramClient
from telethon.sessions import StringSession
from loguru import logger

from backend.bot.client_runtime.qr_login import (
    start_qr_login as _start_qr_login_flow,
    wait_for_qr_login as _wait_for_qr_login_flow,
)
from backend.bot.client_runtime.session_store import (
    cleanup_legacy_session_files,
    delete_system_session,
    extract_expected_bot_id,
    persist_client_session,
    restore_client_session,
    save_system_session_string,
)
from backend.config.settings import settings
from backend.utils.crypto import generate_bind_code as _generate_bind_code

_SYSTEM_BOT_SESSION_KEY = "manager_bot"
_SYSTEM_USERBOT_SESSION_KEY = "global_userbot"
_LEGACY_SESSION_FILES = (
    "bot_session.session",
    "bot_session.session-journal",
    "userbot_session.session",
    "userbot_session.session-journal",
)

bot_client = TelegramClient(
    StringSession(),
    api_id=settings.api_id,
    api_hash=settings.api_hash,
)

userbot_client = TelegramClient(
    StringSession(),
    api_id=settings.api_id,
    api_hash=settings.api_hash,
)


async def start_manager_bot(bot_token: str):
    """Start manager bot and reconcile persisted session with current BOT_TOKEN."""
    expected_bot_id = extract_expected_bot_id(bot_token)
    current_me = None

    cleanup_legacy_session_files(_LEGACY_SESSION_FILES)

    if not bot_client.is_connected():
        await restore_client_session(bot_client, _SYSTEM_BOT_SESSION_KEY)
        await bot_client.connect()

    try:
        if await bot_client.is_user_authorized():
            current_me = await bot_client.get_me()
    except Exception as e:
        logger.warning(f"读取当前 bot 会话失败，将继续使用 token 重新登录: {e}")

    if current_me and expected_bot_id and int(current_me.id) != int(expected_bot_id):
        logger.warning(
            "检测到 BOT_TOKEN 与已持久化 bot 会话不一致，正在重建会话: "
            f"session_bot_id={current_me.id}, token_bot_id={expected_bot_id}"
        )
        try:
            await bot_client.disconnect()
        except Exception as e:
            logger.warning(f"断开旧 bot 会话失败: {e}")

        await delete_system_session(_SYSTEM_BOT_SESSION_KEY)
        bot_client.session = StringSession()
        await bot_client.connect()

    await bot_client.start(bot_token=bot_token)
    me = await bot_client.get_me()
    await persist_client_session(
        bot_client,
        _SYSTEM_BOT_SESSION_KEY,
        session_meta={"bot_id": int(me.id), "username": me.username or ""},
    )
    return me


async def init_userbot() -> bool:
    """Initialize shared userbot client and restore persisted session."""
    cleanup_legacy_session_files(_LEGACY_SESSION_FILES)

    if not userbot_client.is_connected():
        await restore_client_session(userbot_client, _SYSTEM_USERBOT_SESSION_KEY)
        await userbot_client.connect()

    if await userbot_client.is_user_authorized():
        me = await userbot_client.get_me()
        await persist_client_session(
            userbot_client,
            _SYSTEM_USERBOT_SESSION_KEY,
            session_meta={
                "tg_user_id": int(me.id),
                "username": me.username or "",
                "phone": me.phone or "",
            },
        )
        logger.info(f"Userbot 已登录: {me.first_name} (@{me.username})")
        return True

    logger.info("Userbot 未登录，请通过 H5 页面扫码登录")
    return False


async def start_qr_login(login_id: str) -> bool:
    """Start QR login workflow for H5 login session."""
    return await _start_qr_login_flow(
        login_id=login_id,
        userbot_client=userbot_client,
        save_system_session_fn=save_system_session_string,
        system_userbot_session_key=_SYSTEM_USERBOT_SESSION_KEY,
    )


def generate_bind_code() -> str:
    """Backward compatible bind-code generator."""
    return _generate_bind_code()


async def _wait_for_qr_login(login_id: str, qr_login, login_client: TelegramClient | None = None):
    """
    Backward-compatible wrapper used by login service background task.
    """
    await _wait_for_qr_login_flow(
        login_id=login_id,
        qr_login=qr_login,
        userbot_client=userbot_client,
        login_client=login_client,
        save_system_session_fn=save_system_session_string,
        system_userbot_session_key=_SYSTEM_USERBOT_SESSION_KEY,
    )


async def get_peer(chat_id: int):
    """Resolve peer entity by chat id via shared userbot client."""
    return await userbot_client.get_entity(chat_id)


async def is_userbot_ready() -> bool:
    """Check if shared userbot is connected and authorized."""
    if not userbot_client.is_connected():
        return False
    return await userbot_client.is_user_authorized()
