"""QR login flow helpers for userbot."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from loguru import logger
from telethon import TelegramClient
from telethon import events, functions
from telethon.errors import SessionPasswordNeededError
from telethon.tl import types
from telethon.tl.functions.account import GetPasswordRequest
from telethon.sessions import StringSession

from backend.bot.session.redis_login_manager import LoginStatus, RedisLoginManager
from backend.utils.security.crypto import encrypt_string_session

_current_qr_login_id: Optional[str] = None


async def _wait_for_qr_token_import(login_id: str, qr_login, redis_manager: RedisLoginManager):
    """
    等待 Telegram 触发 UpdateLoginToken。
    该事件表示二维码已被扫描/导入，此时前端可切到 loading 态。
    """
    timeout = (qr_login._resp.expires - datetime.now(tz=timezone.utc)).total_seconds()
    event = asyncio.Event()

    async def handler(_update):
        await redis_manager.update_status(login_id, LoginStatus.SCANNING, error="")
        event.set()

    qr_login._client.add_event_handler(handler, events.Raw(types.UpdateLoginToken))
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    finally:
        qr_login._client.remove_event_handler(handler)

    resp = await qr_login._client(qr_login._request)
    if isinstance(resp, types.auth.LoginTokenMigrateTo):
        await qr_login._client._switch_dc(resp.dc_id)
        resp = await qr_login._client(functions.auth.ImportLoginTokenRequest(resp.token))

    if isinstance(resp, types.auth.LoginTokenSuccess):
        user = resp.authorization.user
        await qr_login._client._on_login(user)
        return user

    raise TypeError(f"Login token response was unexpected: {resp}")


async def start_qr_login(
    *,
    login_id: str,
    userbot_client: TelegramClient,
    save_system_session_fn: Callable[..., asyncio.Future],
    system_userbot_session_key: str,
) -> bool:
    """Start QR login workflow for one login session."""
    global _current_qr_login_id

    redis_manager = RedisLoginManager()
    session = await redis_manager.get_session(login_id)
    if not session:
        logger.error(f"登录会话无效或已过期: {login_id}")
        await redis_manager.update_status(login_id, LoginStatus.ERROR, error="会话无效或已过期")
        return False

    try:
        if not userbot_client.is_connected():
            await userbot_client.connect()

        if await userbot_client.is_user_authorized():
            me = await userbot_client.get_me()
            string_session = StringSession.save(userbot_client.session)
            string_session_encrypted = encrypt_string_session(string_session)
            await save_system_session_fn(
                system_userbot_session_key,
                string_session,
                developer_app_id=session.developer_app_id if session else None,
                session_meta={
                    "tg_user_id": int(me.id),
                    "username": me.username or "",
                    "phone": me.phone or "",
                },
            )
            bind_code = await redis_manager.save_string_session(
                login_id=login_id,
                string_session=string_session_encrypted,
                tg_user_id=me.id,
                username=me.username or me.first_name or "",
                phone=me.phone or "",
            )
            logger.info(f"Userbot 已登录: {me.first_name}, bind_code={bind_code}")
            return True

        logger.info(f"开始二维码登录流程: {login_id}")
        _current_qr_login_id = login_id

        qr_login = await userbot_client.qr_login()
        await redis_manager.update_qr_url(login_id, qr_login.url)
        await redis_manager.update_status(login_id, LoginStatus.PENDING)
        logger.info(f"QR URL 已保存: {qr_login.url}")

        asyncio.create_task(
            wait_for_qr_login(
                login_id=login_id,
                qr_login=qr_login,
                userbot_client=userbot_client,
                login_client=None,
                save_system_session_fn=save_system_session_fn,
                system_userbot_session_key=system_userbot_session_key,
            )
        )
        return True
    except Exception as e:
        error_msg = str(e)
        logger.error(f"启动二维码登录失败: {error_msg}")
        await redis_manager.update_status(login_id, LoginStatus.ERROR, error=error_msg)
        return False


async def wait_for_qr_login(
    *,
    login_id: str,
    qr_login,
    userbot_client: TelegramClient,
    login_client: Optional[TelegramClient] = None,
    save_system_session_fn: Optional[Callable[..., asyncio.Future]] = None,
    system_userbot_session_key: Optional[str] = None,
    on_qr_refreshed: Optional[Callable[[str, str], Awaitable[None]]] = None,
) -> None:
    """Wait for QR confirmation, refresh token when expired, and persist session."""
    global _current_qr_login_id

    active_client = login_client or userbot_client
    redis_manager = RedisLoginManager()

    try:
        await redis_manager.update_status(login_id, LoginStatus.PENDING, error="")
        deadline = time.monotonic() + 300
        refresh_attempts = 0

        async def refresh_qr(reason: str) -> bool:
            nonlocal qr_login, refresh_attempts
            last_error: Optional[Exception] = None

            try:
                qr_login = await qr_login.recreate()
                await redis_manager.update_qr_url(login_id, qr_login.url)
                await redis_manager.update_status(login_id, LoginStatus.PENDING, error="")
                if on_qr_refreshed is not None:
                    await on_qr_refreshed(qr_login.url, reason)
                refresh_attempts += 1
                logger.info(f"二维码已刷新({reason}): {login_id}, attempt={refresh_attempts}, strategy=recreate")
                return True
            except Exception as e:
                last_error = e

            try:
                qr_login = await active_client.qr_login()
                await redis_manager.update_qr_url(login_id, qr_login.url)
                await redis_manager.update_status(login_id, LoginStatus.PENDING, error="")
                if on_qr_refreshed is not None:
                    await on_qr_refreshed(qr_login.url, reason)
                refresh_attempts += 1
                logger.info(f"二维码已刷新({reason}): {login_id}, attempt={refresh_attempts}, strategy=new")
                return True
            except Exception as e:
                last_error = e

            error_msg = str(last_error) if last_error else "二维码刷新失败"
            logger.error(f"刷新二维码失败: {error_msg}")
            await redis_manager.update_status(login_id, LoginStatus.ERROR, error=error_msg)
            return False

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await redis_manager.update_status(login_id, LoginStatus.EXPIRED)
                logger.error(f"二维码登录超时: {login_id}")
                return

            try:
                result = await asyncio.wait_for(
                    _wait_for_qr_token_import(login_id, qr_login, redis_manager),
                    timeout=min(60, remaining),
                )
            except SessionPasswordNeededError:
                try:
                    password_info = await active_client(GetPasswordRequest())
                    temp_session = StringSession.save(active_client.session)
                    pending_session_encrypted = encrypt_string_session(temp_session)
                    password_hint = getattr(password_info, "hint", "") or ""
                    await redis_manager.update_status(
                        login_id,
                        LoginStatus.PASSWORD_REQUIRED,
                        error="",
                        password_hint=password_hint,
                        pending_session_encrypted=pending_session_encrypted,
                    )
                    logger.info(
                        f"二维码登录需二步密码: {login_id}, "
                        f"has_hint={'yes' if password_hint else 'no'}"
                    )
                except Exception as e:
                    error_msg = f"进入二步密码流程失败: {e}"
                    logger.error(error_msg)
                    await redis_manager.update_status(login_id, LoginStatus.ERROR, error=error_msg)
                return
            except asyncio.TimeoutError:
                if not await refresh_qr(reason="timeout"):
                    return
                continue
            except Exception as e:
                error_msg = str(e)
                lowered = error_msg.lower()
                if (
                    "authorization token has expired" in lowered
                    or "token has expired" in lowered
                    or "updated qr-code must be re-scanned" in lowered
                    or "importlogintokenrequest" in lowered
                    or "acceptlogintokenrequest" in lowered
                ):
                    if not await refresh_qr(reason="token-expired"):
                        return
                    continue

                if "two-step verification" in error_msg.lower() or "password" in lowered:
                    await redis_manager.update_status(
                        login_id,
                        LoginStatus.ERROR,
                        error="该账户启用了两步验证，请暂时关闭或使用验证码登录",
                    )
                else:
                    await redis_manager.update_status(login_id, LoginStatus.ERROR, error=error_msg)
                return

            if result:
                me = await active_client.get_me()
                string_session = StringSession.save(active_client.session)
                string_session_encrypted = encrypt_string_session(string_session)

                bind_code = await redis_manager.save_string_session(
                    login_id=login_id,
                    string_session=string_session_encrypted,
                    tg_user_id=me.id,
                    username=me.username or me.first_name or "",
                    phone=me.phone or "",
                )

                if (
                    login_client is None
                    and save_system_session_fn is not None
                    and system_userbot_session_key
                ):
                    session_obj = await redis_manager.get_session(login_id)
                    await save_system_session_fn(
                        system_userbot_session_key,
                        string_session,
                        developer_app_id=session_obj.developer_app_id if session_obj else None,
                        session_meta={
                            "tg_user_id": int(me.id),
                            "username": me.username or "",
                            "phone": me.phone or "",
                        },
                    )

                logger.info(f"二维码登录成功: {me.first_name} (@{me.username}), bind_code: {bind_code}")
                return

            await redis_manager.update_status(login_id, LoginStatus.ERROR, error="登录被取消")
            return
    except Exception as e:
        error_msg = str(e)
        logger.error(f"二维码登录失败: {error_msg}")
        await redis_manager.update_status(login_id, LoginStatus.ERROR, error=error_msg)
    finally:
        _current_qr_login_id = None
        if login_client:
            try:
                await login_client.disconnect()
            except Exception as e:
                logger.warning(f"关闭临时二维码登录客户端失败: {e}")
