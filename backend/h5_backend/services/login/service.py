"""Login and binding domain service for H5 API."""
from __future__ import annotations

import random
import string
import ipaddress
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, HTTPException, Request, status
from loguru import logger
from telethon import password as telethon_password
from telethon import TelegramClient
from telethon.errors import PasswordHashInvalidError
from telethon.sessions import StringSession
from telethon.tl.functions.account import GetPasswordRequest
from telethon.tl.functions.auth import CheckPasswordRequest

from backend.bot.account.manager import get_account_manager
from backend.bot.account.binding_service import BindRateLimitError
from backend.bot.developer_apps import get_developer_app_service
from backend.bot.client_runtime.manager import _wait_for_qr_login, is_userbot_ready
from backend.bot.session.redis_login_manager import LoginStatus, get_redis_login_manager
from backend.database.runtime.session import get_async_session
from backend.h5_backend.services.me.account_limit import TgAccountLimitExceededError
from backend.h5_backend.services.me.service import get_me_service
from backend.utils.security.crypto import decrypt_string_session, encrypt_string_session


class LoginService:
    """Login lifecycle and bind business service."""

    @staticmethod
    def _normalize_ip_address(raw_ip: Optional[str]) -> Optional[str]:
        """Normalize client IP for PostgreSQL inet column."""
        value = (raw_ip or "").strip()
        if not value:
            return None
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            return None

    def generate_login_id(self) -> str:
        chars = string.ascii_letters + string.digits
        return "login_" + "".join(random.choices(chars, k=16))

    async def _finalize_login_account(
        self,
        *,
        login_id: str,
        user_id: int,
        ip_address: Optional[str],
    ) -> Dict[str, Any]:
        login_manager = get_redis_login_manager()
        session = await login_manager.get_session(login_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.system_user_id is not None and int(session.system_user_id) != int(user_id):
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.status != LoginStatus.CONFIRMED:
            raise HTTPException(status_code=400, detail="当前会话尚未完成登录")

        account_manager = get_account_manager()

        if session.account_id:
            account = await account_manager.get_account(session.account_id)
            if account:
                issued = await account_manager.issue_bind_code(account.account_id, refresh=False)
                if not issued:
                    issued = await account_manager.issue_bind_code(account.account_id, refresh=True)
                if issued:
                    await login_manager.update_status(
                        login_id,
                        LoginStatus.CONFIRMED,
                        bind_code=issued["bind_code"],
                        account_id=account.account_id,
                    )
                return {
                    "account_id": account.account_id,
                    "bind_code": issued["bind_code"] if issued else session.bind_code,
                    "tg_user_id": int(account.tg_user_id),
                    "username": account.username or account.first_name or "",
                }

        if not session.bind_code:
            raise HTTPException(status_code=400, detail="登录会话缺少绑定码，请重新扫码")

        try:
            account = await account_manager.bind_account(
                user_id=user_id,
                bind_code=session.bind_code,
                ip_address=ip_address or "",
            )
        except BindRateLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"登录收尾失败，请 {exc.retry_after_seconds} 秒后重试",
            ) from exc
        except TgAccountLimitExceededError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except RuntimeError as exc:
            logger.error(f"登录成功后自动建号失败: login_id={login_id}, error={exc}")
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if not account:
            raise HTTPException(status_code=400, detail="登录成功，但账号落库失败")

        issued = await account_manager.issue_bind_code(account.account_id, refresh=True)
        await login_manager.update_status(
            login_id,
            LoginStatus.CONFIRMED,
            bind_code=issued["bind_code"],
            account_id=account.account_id,
            tg_user_id=account.tg_user_id,
            username=account.username or account.first_name or "",
            phone=account.phone or "",
            error="",
        )
        logger.info(
            "二维码登录已自动建号: login_id={}, account_id={}, tg_user_id={}",
            login_id,
            account.account_id,
            account.tg_user_id,
        )
        return {
            "account_id": account.account_id,
            "bind_code": issued["bind_code"],
            "tg_user_id": int(account.tg_user_id),
            "username": account.username or account.first_name or "",
        }

    async def create_login_session(self, user_id: int, background_tasks: BackgroundTasks) -> Dict[str, Any]:
        me_service = get_me_service()
        await me_service.require_active_subscription(user_id)
        try:
            await me_service.ensure_can_add_tg_account(user_id)
        except TgAccountLimitExceededError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        developer_app_service = get_developer_app_service()
        credentials = await developer_app_service.choose_login_credentials_for_user(user_id)

        login_manager = get_redis_login_manager()
        login_id = self.generate_login_id()
        session = await login_manager.create_session(login_id)
        await login_manager.update_status(
            login_id,
            LoginStatus.PENDING,
            system_user_id=user_id,
            developer_app_id=credentials.app_id or "",
        )

        login_client = TelegramClient(
            StringSession(),
            api_id=credentials.api_id,
            api_hash=credentials.api_hash,
        )
        await login_client.connect()
        qr_login = await login_client.qr_login()
        qr_url = qr_login.url

        await login_manager.update_qr_url(login_id, qr_url)
        await login_manager.update_status(login_id, LoginStatus.PENDING)

        background_tasks.add_task(_wait_for_qr_login, login_id, qr_login, login_client)

        return {
            "login_id": login_id,
            "qr_url": qr_url,
            "expires_at": session.expires_at,
        }

    async def get_login_status(self, login_id: str, user_id: int) -> Dict[str, Any]:
        login_manager = get_redis_login_manager()
        session = await login_manager.get_session(login_id)
        if not session:
            return {"success": False, "status": "error", "error": "会话不存在"}

        owner_user_id = session.system_user_id
        if owner_user_id is not None:
            try:
                owner_user_id = int(owner_user_id)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=404, detail="会话不存在") from exc
            if owner_user_id != user_id:
                raise HTTPException(status_code=404, detail="会话不存在")

        response_data = {
            "status": session.status.value,
            "error": session.error,
            "qr_url": session.qr_url,
        }
        if session.status == LoginStatus.CONFIRMED:
            finalized = await self._finalize_login_account(
                login_id=login_id,
                user_id=user_id,
                ip_address=None,
            )
            response_data.update(
                {
                    "account_id": finalized["account_id"],
                    "bind_code": finalized["bind_code"],
                    "tg_user_id": finalized["tg_user_id"],
                    "username": finalized["username"],
                }
            )
        elif session.status == LoginStatus.PASSWORD_REQUIRED:
            response_data.update(
                {
                    "password_hint": session.password_hint,
                }
            )
        return {"success": True, "data": response_data}

    async def check_userbot_login(self) -> Dict[str, Any]:
        is_ready = await is_userbot_ready()
        return {"is_logged_in": is_ready}

    async def bind_account(self, request: Request, user_id: int) -> Dict[str, Any]:
        payload = await request.json()
        bind_code = payload.get("bind_code")
        if not bind_code:
            raise HTTPException(status_code=400, detail="缺少绑定码")

        login_manager = get_redis_login_manager()
        bind_data = await login_manager.get_account_by_bind_code(bind_code)
        if not bind_data:
            raise HTTPException(status_code=400, detail="绑定失败：绑定码无效或已过期")

        owner_user_id = bind_data.get("system_user_id")
        if owner_user_id is not None and int(owner_user_id) != user_id:
            raise HTTPException(status_code=403, detail="该绑定码不属于当前系统用户")

        account_manager = get_account_manager()
        try:
            account = await account_manager.bind_account(
                user_id=user_id,
                bind_code=bind_code,
                ip_address=self._normalize_ip_address(request.client.host if request.client else None) or "",
            )
        except BindRateLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"绑定失败次数过多，请 {exc.retry_after_seconds} 秒后再试",
            ) from exc
        except TgAccountLimitExceededError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not account:
            raise HTTPException(status_code=400, detail="绑定失败：绑定码无效或账号已绑定")

        return {"account_id": account.account_id, "username": account.username}

    async def submit_password(self, request: Request, user_id: int) -> Dict[str, Any]:
        payload = await request.json()
        login_id = (payload.get("login_id") or "").strip()
        password = payload.get("password") or ""

        if not login_id:
            raise HTTPException(status_code=400, detail="缺少登录会话 ID")
        if not password:
            raise HTTPException(status_code=400, detail="请输入 Telegram 二步密码")

        login_manager = get_redis_login_manager()
        session = await login_manager.get_session(login_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.system_user_id is not None and int(session.system_user_id) != int(user_id):
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.status != LoginStatus.PASSWORD_REQUIRED:
            raise HTTPException(status_code=400, detail="当前会话无需输入二步密码")
        if not session.pending_session_encrypted:
            raise HTTPException(status_code=400, detail="会话缺少待验证状态，请重新扫码")

        developer_app_service = get_developer_app_service()
        async with get_async_session() as db_session:
            credentials = await developer_app_service.resolve_credentials(
                session=db_session,
                developer_app_id=session.developer_app_id,
                user_id=user_id,
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
            string_session_encrypted = encrypt_string_session(string_session)
            bind_code = await login_manager.save_string_session(
                login_id=login_id,
                string_session=string_session_encrypted,
                tg_user_id=me.id,
                username=me.username or me.first_name or "",
                phone=me.phone or "",
            )
            finalized = await self._finalize_login_account(
                login_id=login_id,
                user_id=user_id,
                ip_address=self._normalize_ip_address(request.client.host if request.client else None),
            )

            return {
                "account_id": finalized["account_id"],
                "bind_code": finalized["bind_code"],
                "tg_user_id": finalized["tg_user_id"],
                "username": finalized["username"],
            }
        except PasswordHashInvalidError as exc:
            await login_manager.update_status(
                login_id,
                LoginStatus.PASSWORD_REQUIRED,
                error="二步密码错误，请重试",
            )
            raise HTTPException(status_code=400, detail="二步密码错误，请重试") from exc
        except Exception as exc:
            await login_manager.update_status(
                login_id,
                LoginStatus.ERROR,
                error=f"二步密码验证失败: {exc}",
            )
            raise HTTPException(status_code=400, detail=f"二步密码验证失败: {exc}") from exc
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass


_login_service: Optional[LoginService] = None


def get_login_service() -> LoginService:
    """Get singleton login service instance."""
    global _login_service
    if _login_service is None:
        _login_service = LoginService()
    return _login_service
