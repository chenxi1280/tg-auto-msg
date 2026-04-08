"""Login and binding domain service for H5 API."""
from __future__ import annotations

import random
import string
import ipaddress
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, HTTPException, Request, status
from loguru import logger
from sqlalchemy import select
from telethon import password as telethon_password
from telethon import TelegramClient
from telethon.errors import (
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.account import GetPasswordRequest
from telethon.tl.functions.auth import CheckPasswordRequest

from backend.bot.account.manager import get_account_manager
from backend.bot.developer_apps import get_developer_app_service
from backend.bot.developer_apps.service import (
    ASSIGNMENT_CONTEXT_EXISTING_REASSIGN,
    ASSIGNMENT_CONTEXT_NEW,
)
from backend.bot.client_runtime.manager import _wait_for_qr_login, is_userbot_ready
from backend.config.core.settings import settings
from backend.bot.handlers.core.user_link import (
    clear_active_account_id,
    replace_linked_system_user_id,
    set_active_account_id,
)
from backend.bot.session.redis_login_manager import LoginStatus, get_redis_login_manager
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account, HealthStatus, TelegramDeveloperApp
from backend.h5_backend.services.licensing.service import (
    TgAccountLimitExceededError,
    bind_current_authorization_to_account_if_possible,
    grant_trial_authorization_if_eligible,
)
from backend.h5_backend.services.account.auto_sync import (
    SYNC_TRIGGER_LOGIN_SUCCESS,
    account_auto_sync_runtime,
)
from backend.h5_backend.services.me.service import get_me_service
from backend.utils.security.crypto import decrypt_string_session, encrypt_string_session


class LoginService:
    """Login lifecycle and bind business service."""
    PHONE_CODE_MAX_ATTEMPTS = 5
    BIND_START_COOLDOWN_SECONDS = max(1, int(settings.bind_start_cooldown_seconds or 120))
    LOGIN_SESSION_TTL_SECONDS = max(1, int(settings.login_session_ttl_seconds or 900))

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

    @staticmethod
    def _normalize_phone_number(raw_phone: Optional[str]) -> str:
        value = (raw_phone or "").strip().replace(" ", "")
        if not value:
            raise HTTPException(status_code=400, detail="请输入手机号")
        if not value.startswith("+"):
            raise HTTPException(status_code=400, detail="手机号需包含国家区号，例如 +8613812345678")
        digits = value[1:]
        if not digits.isdigit() or len(digits) < 6 or len(digits) > 20:
            raise HTTPException(status_code=400, detail="手机号格式不正确，请检查国家区号和号码")
        return value

    @staticmethod
    def _normalize_phone_code(raw_code: Optional[str]) -> str:
        value = "".join(ch for ch in str(raw_code or "").strip() if ch.isdigit())
        if len(value) < 3:
            raise HTTPException(status_code=400, detail="请输入 Telegram 验证码")
        return value

    async def _enforce_bind_start_cooldown(self, *, user_id: int) -> None:
        retry_after = await get_redis_login_manager().acquire_bind_start_cooldown(
            user_id,
            ttl_seconds=self.BIND_START_COOLDOWN_SECONDS,
        )
        if retry_after > 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "操作过于频繁，请稍后再试。"
                    f"为避免误绑定，2 分钟内只能发起 1 次 TG 账号绑定，"
                    f"请在 {retry_after} 秒后重试。"
                ),
            )

    async def enforce_bind_start_cooldown(self, *, user_id: int) -> None:
        """Public wrapper so Bot/H5 binding entries share the same cooldown policy."""
        await self._enforce_bind_start_cooldown(user_id=user_id)

    async def _load_session_for_user(self, *, login_id: str, user_id: int):
        login_manager = get_redis_login_manager()
        session = await login_manager.get_session(login_id)
        if not session:
            raise HTTPException(status_code=404, detail="登录会话不存在或已过期")
        if session.system_user_id is not None and int(session.system_user_id) != int(user_id):
            raise HTTPException(status_code=404, detail="登录会话不存在或已过期")
        return session

    async def _resolve_login_credentials(self, *, user_id: int, developer_app_id: Optional[int]):
        developer_app_service = get_developer_app_service()
        async with get_async_session() as db_session:
            return await developer_app_service.resolve_credentials(
                session=db_session,
                developer_app_id=developer_app_id,
                user_id=user_id,
            )

    async def _upsert_login_account(
        self,
        *,
        login_id: str,
        user_id: int,
        actor_tg_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        login_manager = get_redis_login_manager()
        session = await login_manager.get_session(login_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.system_user_id is not None and int(session.system_user_id) != int(user_id):
            raise HTTPException(status_code=404, detail="会话不存在")
        if session.status != LoginStatus.CONFIRMED:
            raise HTTPException(status_code=400, detail="当前会话尚未完成登录")

        if session.account_id:
            account_manager = get_account_manager()
            account = await account_manager.get_account(session.account_id)
            if account:
                return {
                    "account_id": account.account_id,
                    "tg_user_id": int(account.tg_user_id or 0),
                    "username": account.username or account.first_name or "",
                }

        if not session.confirmed_session_encrypted:
            raise HTTPException(status_code=400, detail="登录会话缺少确认后的会话数据，请重新扫码")

        tg_user_id = int(session.tg_user_id or 0)
        if tg_user_id <= 0:
            raise HTTPException(status_code=400, detail="登录会话缺少 Telegram 账号信息，请重新扫码")

        developer_service = get_developer_app_service()
        async with get_async_session() as db_session:
            trial_authorization = None
            existing = await db_session.execute(
                select(Account).where(
                    Account.user_id == user_id,
                    Account.tg_user_id == tg_user_id,
                )
            )
            account = existing.scalar_one_or_none()

            preferred_app_id = session.developer_app_id
            resolved_app_id = await developer_service.resolve_assignable_app_id(
                user_id=int(user_id),
                preferred_app_id=preferred_app_id,
                exclude_account_id=account.account_id if account else None,
                assignment_context=ASSIGNMENT_CONTEXT_EXISTING_REASSIGN if account else ASSIGNMENT_CONTEXT_NEW,
                existing_app_id=int(account.developer_app_id) if account and account.developer_app_id is not None else None,
            )
            resolved_app_version = 1
            if resolved_app_id is not None:
                app_row = await db_session.get(TelegramDeveloperApp, int(resolved_app_id))
                if app_row is not None:
                    resolved_app_version = int(app_row.credentials_version or 1)

            if account is None:
                existing_any = await db_session.execute(
                    select(Account).where(Account.tg_user_id == tg_user_id)
                )
                other_account = existing_any.scalar_one_or_none()
                if other_account and int(other_account.user_id) != int(user_id):
                    raise HTTPException(status_code=400, detail="该 Telegram 账号已归属于其他系统账号")

                me_service = get_me_service()
                try:
                    await me_service.ensure_can_add_tg_account(user_id, existing_tg_user_id=tg_user_id)
                except TgAccountLimitExceededError as exc:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

                account = Account(
                    user_id=user_id,
                    tg_user_id=tg_user_id,
                    username=(session.username or "") or f"user_{tg_user_id}",
                    first_name=session.username or "",
                    phone=session.phone or "",
                    string_session_encrypted=session.confirmed_session_encrypted,
                    developer_app_id=resolved_app_id,
                    developer_app_version=resolved_app_version,
                    reauth_required=False,
                    reauth_reason=None,
                    reauth_required_at=None,
                    health_status=HealthStatus.ONLINE,
                )
                db_session.add(account)
                await db_session.flush()
            else:
                account.username = (session.username or "") or account.username
                account.first_name = (session.username or "") or account.first_name
                account.phone = (session.phone or "") or account.phone
                account.string_session_encrypted = session.confirmed_session_encrypted
                account.developer_app_id = resolved_app_id
                account.developer_app_version = resolved_app_version
                account.reauth_required = False
                account.reauth_reason = None
                account.reauth_required_at = None
                account.health_status = HealthStatus.ONLINE

            await bind_current_authorization_to_account_if_possible(
                user_id=user_id,
                account_id=account.account_id,
                session=db_session,
            )
            trial_authorization = await grant_trial_authorization_if_eligible(
                user_id=user_id,
                account_id=account.account_id,
                session=db_session,
            )

            if actor_tg_user_id and int(actor_tg_user_id) > 0:
                previous_user_id = await replace_linked_system_user_id(
                    db_session,
                    int(actor_tg_user_id),
                    int(user_id),
                )
                if previous_user_id is not None:
                    await clear_active_account_id(db_session, int(actor_tg_user_id), previous_user_id)
                await set_active_account_id(
                    db_session,
                    int(actor_tg_user_id),
                    int(user_id),
                    account.account_id,
                )

            await db_session.commit()
            await db_session.refresh(account)

        await login_manager.update_status(
            login_id,
            LoginStatus.CONFIRMED,
            account_id=account.account_id,
            tg_user_id=account.tg_user_id,
            username=account.username or account.first_name or "",
            phone=account.phone or "",
            error="",
        )
        logger.info(
            "二维码登录已直接建号/更新: login_id={}, account_id={}, tg_user_id={}",
            login_id,
            account.account_id,
            account.tg_user_id,
        )
        sync_queue_result = await account_auto_sync_runtime.enqueue_account(
            account.account_id,
            trigger_source=SYNC_TRIGGER_LOGIN_SUCCESS,
            user_id=int(user_id),
        )
        return {
            "account_id": account.account_id,
            "tg_user_id": int(account.tg_user_id or 0),
            "username": account.username or account.first_name or "",
            "sync_queue_status": sync_queue_result.get("status"),
            "trial_authorization": (
                {
                    "authorization_id": trial_authorization.authorization_id,
                    "end_at": trial_authorization.end_at.isoformat() if trial_authorization.end_at else None,
                    "grant_source": getattr(trial_authorization, "grant_source", None),
                }
                if trial_authorization is not None
                else None
            ),
        }

    async def create_system_bind_link(self, user_id: int) -> Dict[str, Any]:
        me_service = get_me_service()
        bot = await me_service._serialize_bot_entry()
        username = (bot.get("username") or "").strip().lstrip("@")
        if not username:
            raise HTTPException(status_code=400, detail="当前未配置 TG Bot 入口")

        login_manager = get_redis_login_manager()
        token = await login_manager.create_system_bind_token(int(user_id))
        return {
            "bot_username": username,
            "bind_token": token,
            "bot_bind_url": f"https://t.me/{username}?start=link_{token}",
        }

    async def create_phone_login_session(
        self,
        user_id: int,
        *,
        existing_tg_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        me_service = get_me_service()
        try:
            await me_service.ensure_can_add_tg_account(user_id, existing_tg_user_id=existing_tg_user_id)
        except TgAccountLimitExceededError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        await self._enforce_bind_start_cooldown(user_id=user_id)

        developer_app_service = get_developer_app_service()
        credentials = await developer_app_service.choose_login_credentials_for_user(
            user_id,
            existing_tg_user_id=existing_tg_user_id,
        )

        login_manager = get_redis_login_manager()
        login_id = self.generate_login_id()
        session = await login_manager.create_session(login_id)
        await login_manager.update_status(
            login_id,
            LoginStatus.PHONE_INPUT_REQUIRED,
            system_user_id=user_id,
            developer_app_id=credentials.app_id or "",
            login_mode="phone_code",
            qr_url="",
            error="",
            phone_number="",
            phone_code_hash="",
            code_sent_at="",
            code_attempts="0",
            pending_session_encrypted="",
        )
        return {
            "login_id": login_id,
            "expires_at": session.expires_at,
            "expires_in_seconds": self.LOGIN_SESSION_TTL_SECONDS,
            "status": LoginStatus.PHONE_INPUT_REQUIRED.value,
        }

    async def create_login_session(self, user_id: int, background_tasks: BackgroundTasks) -> Dict[str, Any]:
        me_service = get_me_service()
        try:
            await me_service.ensure_can_add_tg_account(user_id)
        except TgAccountLimitExceededError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        await self._enforce_bind_start_cooldown(user_id=user_id)
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
            "expires_in_seconds": self.LOGIN_SESSION_TTL_SECONDS,
        }

    async def submit_phone_number_data(
        self,
        *,
        login_id: str,
        user_id: int,
        phone_number: str,
    ) -> Dict[str, Any]:
        normalized_phone = self._normalize_phone_number(phone_number)
        session = await self._load_session_for_user(login_id=login_id, user_id=user_id)
        if session.login_mode != "phone_code":
            raise HTTPException(status_code=400, detail="当前会话不是手机号登录，请重新开始")
        if session.status not in {LoginStatus.PHONE_INPUT_REQUIRED, LoginStatus.CODE_INPUT_REQUIRED, LoginStatus.ERROR}:
            raise HTTPException(status_code=400, detail="当前会话状态不允许重新发送验证码")

        credentials = await self._resolve_login_credentials(
            user_id=user_id,
            developer_app_id=session.developer_app_id,
        )
        client = TelegramClient(
            StringSession(),
            api_id=credentials.api_id,
            api_hash=credentials.api_hash,
        )

        try:
            await client.connect()
            sent = await client.send_code_request(normalized_phone)
            pending_session = encrypt_string_session(StringSession.save(client.session))
            await get_redis_login_manager().update_status(
                login_id,
                LoginStatus.CODE_INPUT_REQUIRED,
                login_mode="phone_code",
                phone_number=normalized_phone,
                phone_code_hash=sent.phone_code_hash,
                code_sent_at=datetime.now().isoformat(),
                code_attempts="0",
                pending_session_encrypted=pending_session,
                error="",
                password_hint="",
                qr_url="",
            )
            logger.info("手机号登录验证码已发送: login_id={}, phone={}", login_id, f"{normalized_phone[:4]}***")
            return {
                "login_id": login_id,
                "status": LoginStatus.CODE_INPUT_REQUIRED.value,
                "phone_number": normalized_phone,
                "expires_in_seconds": self.LOGIN_SESSION_TTL_SECONDS,
            }
        except PhoneNumberInvalidError as exc:
            raise HTTPException(status_code=400, detail="手机号格式不正确，请检查国家区号和号码") from exc
        except Exception as exc:
            await get_redis_login_manager().update_status(
                login_id,
                LoginStatus.ERROR,
                error=f"发送验证码失败: {type(exc).__name__}",
            )
            raise HTTPException(status_code=400, detail="发送 Telegram 验证码失败，请稍后重试") from exc
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def submit_phone_code_data(
        self,
        *,
        login_id: str,
        user_id: int,
        code: str,
        expected_tg_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        normalized_code = self._normalize_phone_code(code)
        session = await self._load_session_for_user(login_id=login_id, user_id=user_id)
        if session.login_mode != "phone_code":
            raise HTTPException(status_code=400, detail="当前会话不是手机号登录，请重新开始")
        if session.status != LoginStatus.CODE_INPUT_REQUIRED:
            raise HTTPException(status_code=400, detail="当前会话暂时不能提交验证码")
        if not session.phone_number or not session.phone_code_hash or not session.pending_session_encrypted:
            raise HTTPException(status_code=400, detail="登录会话缺少手机号信息，请重新发送验证码")

        credentials = await self._resolve_login_credentials(
            user_id=user_id,
            developer_app_id=session.developer_app_id,
        )
        client = TelegramClient(
            StringSession(decrypt_string_session(session.pending_session_encrypted)),
            api_id=credentials.api_id,
            api_hash=credentials.api_hash,
        )
        attempts = int(session.code_attempts or "0")

        try:
            await client.connect()
            me = await client.sign_in(
                phone=session.phone_number,
                code=normalized_code,
                phone_code_hash=session.phone_code_hash,
            )
            if expected_tg_user_id is not None and int(me.id) != int(expected_tg_user_id):
                await get_redis_login_manager().update_status(
                    login_id,
                    LoginStatus.ERROR,
                    error="当前登录方式仅允许验证指定的 Telegram 账号",
                )
                raise HTTPException(status_code=400, detail="当前登录方式仅允许验证指定的 Telegram 账号")
            encrypted_session = encrypt_string_session(StringSession.save(client.session))
            await get_redis_login_manager().save_string_session(
                login_id=login_id,
                string_session=encrypted_session,
                tg_user_id=me.id,
                username=me.username or me.first_name or "",
                phone=me.phone or "",
            )
            finalized = await self._upsert_login_account(
                login_id=login_id,
                user_id=user_id,
            )
            bind_link = await self.create_system_bind_link(user_id)
            return {
                "status": LoginStatus.CONFIRMED.value,
                "account_id": finalized["account_id"],
                "tg_user_id": finalized["tg_user_id"],
                "username": finalized["username"],
                "bot_bind_url": bind_link["bot_bind_url"],
                "bot_username": bind_link["bot_username"],
                "trial_authorization": finalized.get("trial_authorization"),
            }
        except SessionPasswordNeededError:
            password_info = await client(GetPasswordRequest())
            pending_session = encrypt_string_session(StringSession.save(client.session))
            await get_redis_login_manager().update_status(
                login_id,
                LoginStatus.PASSWORD_REQUIRED,
                pending_session_encrypted=pending_session,
                password_hint=password_info.hint or "",
                error="",
            )
            return {
                "status": LoginStatus.PASSWORD_REQUIRED.value,
                "password_hint": password_info.hint or "",
            }
        except (PhoneCodeInvalidError, PhoneCodeExpiredError) as exc:
            attempts += 1
            next_status = LoginStatus.ERROR if attempts >= self.PHONE_CODE_MAX_ATTEMPTS else LoginStatus.CODE_INPUT_REQUIRED
            error_type = type(exc).__name__
            is_expired = isinstance(exc, PhoneCodeExpiredError)
            message = "验证码已过期，请重新发送验证码" if is_expired else "验证码错误，请重新输入"
            logger.warning(
                "手机号验证码校验失败: login_id={}, user_id={}, phone={}, developer_app_id={}, error_type={}, attempts={}, next_status={}",
                login_id,
                int(user_id),
                f"{session.phone_number[:4]}***" if session.phone_number else "",
                session.developer_app_id,
                error_type,
                attempts,
                next_status.value,
            )
            await get_redis_login_manager().update_status(
                login_id,
                next_status,
                code_attempts=str(attempts),
                error=message,
            )
            if next_status == LoginStatus.ERROR:
                raise HTTPException(status_code=400, detail="验证码错误次数过多，请重新开始登录") from exc
            raise HTTPException(status_code=400, detail=message) from exc
        except HTTPException:
            raise
        except Exception as exc:
            await get_redis_login_manager().update_status(
                login_id,
                LoginStatus.ERROR,
                error=f"验证码登录失败: {type(exc).__name__}",
            )
            raise HTTPException(status_code=400, detail="验证码验证失败，请重新开始登录") from exc
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

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
            "phone_number": session.phone_number,
        }
        if session.status == LoginStatus.CONFIRMED:
            finalized = await self._upsert_login_account(
                login_id=login_id,
                user_id=user_id,
            )
            bind_link = await self.create_system_bind_link(user_id)
            response_data.update(
                {
                    "account_id": finalized["account_id"],
                    "tg_user_id": finalized["tg_user_id"],
                    "username": finalized["username"],
                    "bot_bind_url": bind_link["bot_bind_url"],
                    "bot_username": bind_link["bot_username"],
                    "trial_authorization": finalized.get("trial_authorization"),
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
        del request, user_id
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="账号级绑定已下线，请使用“系统账号绑定到 TG Bot”入口")

    async def submit_password_data(
        self,
        *,
        login_id: str,
        user_id: int,
        password: str,
        expected_tg_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not login_id:
            raise HTTPException(status_code=400, detail="缺少登录会话 ID")
        if not password:
            raise HTTPException(status_code=400, detail="请输入 Telegram 二步密码")

        session = await self._load_session_for_user(login_id=login_id, user_id=user_id)
        if session.status != LoginStatus.PASSWORD_REQUIRED:
            raise HTTPException(status_code=400, detail="当前会话无需输入二步密码")
        if not session.pending_session_encrypted:
            raise HTTPException(status_code=400, detail="会话缺少待验证状态，请重新绑定")

        credentials = await self._resolve_login_credentials(
            user_id=user_id,
            developer_app_id=session.developer_app_id,
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
            if expected_tg_user_id is not None and int(me.id) != int(expected_tg_user_id):
                await get_redis_login_manager().update_status(
                    login_id,
                    LoginStatus.ERROR,
                    error="当前登录方式仅允许验证指定的 Telegram 账号",
                )
                raise HTTPException(status_code=400, detail="当前登录方式仅允许验证指定的 Telegram 账号")
            string_session = StringSession.save(client.session)
            string_session_encrypted = encrypt_string_session(string_session)
            await get_redis_login_manager().save_string_session(
                login_id=login_id,
                string_session=string_session_encrypted,
                tg_user_id=me.id,
                username=me.username or me.first_name or "",
                phone=me.phone or "",
            )
            finalized = await self._upsert_login_account(
                login_id=login_id,
                user_id=user_id,
            )
            bind_link = await self.create_system_bind_link(user_id)

            return {
                "account_id": finalized["account_id"],
                "tg_user_id": finalized["tg_user_id"],
                "username": finalized["username"],
                "bot_bind_url": bind_link["bot_bind_url"],
                "bot_username": bind_link["bot_username"],
                "trial_authorization": finalized.get("trial_authorization"),
            }
        except PasswordHashInvalidError as exc:
            await get_redis_login_manager().update_status(
                login_id,
                LoginStatus.PASSWORD_REQUIRED,
                error="二步密码错误，请重试",
            )
            raise HTTPException(status_code=400, detail="二步密码错误，请重试") from exc
        except Exception as exc:
            await get_redis_login_manager().update_status(
                login_id,
                LoginStatus.ERROR,
                error=f"二步密码验证失败: {type(exc).__name__}",
            )
            raise HTTPException(status_code=400, detail="二步密码验证失败，请重新开始登录") from exc
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def submit_password(self, request: Request, user_id: int) -> Dict[str, Any]:
        payload = await request.json()
        login_id = (payload.get("login_id") or "").strip()
        password = payload.get("password") or ""
        return await self.submit_password_data(
            login_id=login_id,
            user_id=user_id,
            password=password,
        )


_login_service: Optional[LoginService] = None


def get_login_service() -> LoginService:
    """Get singleton login service instance."""
    global _login_service
    if _login_service is None:
        _login_service = LoginService()
    return _login_service
