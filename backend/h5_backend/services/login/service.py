"""Login and binding domain service for H5 API."""
from __future__ import annotations

import random
import string
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, HTTPException, Request, status
from telethon import TelegramClient
from telethon.sessions import StringSession

from backend.bot.account.manager import get_account_manager
from backend.bot.account.binding_service import BindRateLimitError
from backend.bot.developer_apps import get_developer_app_service
from backend.bot.client_runtime.manager import _wait_for_qr_login, is_userbot_ready
from backend.bot.session.redis_login_manager import LoginStatus, get_redis_login_manager
from backend.h5_backend.services.me.service import get_me_service


class LoginService:
    """Login lifecycle and bind business service."""

    def generate_login_id(self) -> str:
        chars = string.ascii_letters + string.digits
        return "login_" + "".join(random.choices(chars, k=16))

    async def create_login_session(self, user_id: int, background_tasks: BackgroundTasks) -> Dict[str, Any]:
        me_service = get_me_service()
        await me_service.require_active_subscription(user_id)
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
            response_data.update(
                {
                    "bind_code": session.bind_code,
                    "tg_user_id": session.tg_user_id,
                    "username": session.username,
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
                ip_address=request.client.host if request.client else "",
            )
        except BindRateLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"绑定失败次数过多，请 {exc.retry_after_seconds} 秒后再试",
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not account:
            raise HTTPException(status_code=400, detail="绑定失败：绑定码无效或账号已绑定")

        return {"account_id": account.account_id, "username": account.username}


_login_service: Optional[LoginService] = None


def get_login_service() -> LoginService:
    """Get singleton login service instance."""
    global _login_service
    if _login_service is None:
        _login_service = LoginService()
    return _login_service
