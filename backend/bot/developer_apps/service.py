"""Telegram developer app credential management and selection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Any, Dict, List

from fastapi import HTTPException
from sqlalchemy import and_, func, select, update

from backend.config.core.settings import settings
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account, AppSetting, TelegramDeveloperApp
from backend.utils.security.crypto import decrypt_proxy_password, encrypt_proxy_password

DEFAULT_APP_SETTING_KEY = "default_developer_app_id"
USER_APP_SETTING_PREFIX = "user_dev_app:"


@dataclass
class DeveloperAppCredentials:
    """Resolved Telegram API credentials."""

    app_id: Optional[int]
    api_id: int
    api_hash: str
    credentials_version: int
    source: str


def _user_app_key(user_id: int) -> str:
    return f"{USER_APP_SETTING_PREFIX}{int(user_id)}"


class DeveloperAppService:
    """Service for multi-developer Telegram app credential pool."""

    @staticmethod
    def _snapshot_app(row: TelegramDeveloperApp) -> Dict[str, Any]:
        return {
            "id": int(row.id),
            "app_name": row.app_name,
            "api_id": int(row.api_id),
            "is_active": bool(row.is_active),
            "max_accounts": int(row.max_accounts or 0),
            "credentials_version": int(row.credentials_version or 1),
            "last_rotated_at": row.last_rotated_at.isoformat() if row.last_rotated_at else None,
            "notes": row.notes,
        }

    @staticmethod
    def _env_credentials_or_error() -> DeveloperAppCredentials:
        """Resolve fallback credentials from env, or raise when unavailable."""
        if not settings.api_id or not settings.api_hash:
            raise HTTPException(status_code=503, detail="未配置可用的 Telegram 开发者凭证")
        return DeveloperAppCredentials(
            app_id=None,
            api_id=int(settings.api_id),
            api_hash=str(settings.api_hash),
            credentials_version=0,
            source="env",
        )

    async def _is_capacity_available(
        self,
        session: Any,
        app_id: int,
        *,
        exclude_account_id: Optional[str] = None,
    ) -> bool:
        """Check whether one app can accept one more account."""
        app = await session.get(TelegramDeveloperApp, int(app_id))
        if not app or not app.is_active:
            return False
        if int(app.max_accounts or 0) <= 0:
            return True

        query = select(func.count(Account.account_id)).where(Account.developer_app_id == int(app_id))
        if exclude_account_id:
            query = query.where(Account.account_id != str(exclude_account_id))
        usage = int((await session.execute(query)).scalar() or 0)
        return usage < int(app.max_accounts)

    async def resolve_assignable_app_id(
        self,
        *,
        user_id: int,
        preferred_app_id: Optional[int] = None,
        exclude_account_id: Optional[str] = None,
    ) -> Optional[int]:
        """
        Resolve one assignable developer app id for account/session creation.

        Priority:
        1) preferred_app_id
        2) user preferred app
        3) global default app
        4) other active apps by id asc
        """
        async with get_async_session() as session:
            candidate_ids: List[int] = []

            def _add_candidate(candidate: Optional[int]) -> None:
                if candidate is None:
                    return
                value = int(candidate)
                if value not in candidate_ids:
                    candidate_ids.append(value)

            _add_candidate(preferred_app_id)
            _add_candidate(await self.get_user_preferred_app_id(session, int(user_id)))
            _add_candidate(await self.get_default_app_id(session))

            all_active = await session.execute(
                select(TelegramDeveloperApp.id)
                .where(TelegramDeveloperApp.is_active.is_(True))
                .order_by(TelegramDeveloperApp.id.asc())
            )
            active_ids = [int(item) for item in all_active.scalars().all()]
            for app_id in active_ids:
                _add_candidate(app_id)

            for app_id in candidate_ids:
                if await self._is_capacity_available(
                    session,
                    app_id,
                    exclude_account_id=exclude_account_id,
                ):
                    return int(app_id)

            if preferred_app_id is not None:
                row = await session.get(TelegramDeveloperApp, int(preferred_app_id))
                if row is None:
                    raise HTTPException(status_code=404, detail="开发者应用不存在")
                if not row.is_active:
                    raise HTTPException(status_code=400, detail="开发者应用未启用")
                raise HTTPException(status_code=409, detail="开发者应用容量已满")

            if active_ids:
                raise HTTPException(status_code=409, detail="开发者凭证池容量已满，请联系管理员扩容")

            # No active DB credentials: allow env fallback.
            return None

    async def ensure_env_default_app(self) -> Optional[int]:
        """
        Ensure one DB credential row exists for env TG_API_ID/TG_API_HASH.
        Returns DB app id when available.
        """
        if not settings.api_id or not settings.api_hash:
            return None

        encrypted_hash = encrypt_proxy_password(settings.api_hash)

        async with get_async_session() as session:
            result = await session.execute(
                select(TelegramDeveloperApp).where(TelegramDeveloperApp.api_id == int(settings.api_id)).limit(1)
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = TelegramDeveloperApp(
                    app_name="env-default",
                    api_id=int(settings.api_id),
                    api_hash_encrypted=encrypted_hash,
                    is_active=True,
                    max_accounts=0,
                    credentials_version=1,
                    notes="自动从环境变量初始化",
                )
                session.add(row)
                await session.flush()
            else:
                should_rotate = False
                try:
                    current_hash = decrypt_proxy_password(row.api_hash_encrypted)
                    should_rotate = current_hash != str(settings.api_hash)
                except Exception:
                    should_rotate = True
                row.api_hash_encrypted = encrypted_hash
                if should_rotate:
                    now = datetime.now()
                    row.credentials_version = int(row.credentials_version or 1) + 1
                    row.last_rotated_at = now
                    await session.execute(
                        update(Account)
                        .where(Account.developer_app_id == int(row.id))
                        .values(
                            reauth_required=True,
                            reauth_reason="api_hash_rotated",
                            reauth_required_at=now,
                            health_status="offline",
                        )
                    )
                if not row.is_active:
                    row.is_active = True

            default_row = await session.get(AppSetting, DEFAULT_APP_SETTING_KEY)
            if default_row is None:
                session.add(AppSetting(key=DEFAULT_APP_SETTING_KEY, value=str(row.id)))
            elif not (default_row.value or "").strip():
                default_row.value = str(row.id)

            await session.commit()
            return int(row.id)

    async def get_default_app_id(self, session: Any) -> Optional[int]:
        """Get global default app id from app_settings with active fallback."""
        setting = await session.get(AppSetting, DEFAULT_APP_SETTING_KEY)
        if setting and (setting.value or "").strip():
            try:
                app_id = int(setting.value.strip())
                row = await session.get(TelegramDeveloperApp, app_id)
                if row and row.is_active:
                    return app_id
            except Exception:
                pass

        result = await session.execute(
            select(TelegramDeveloperApp.id)
            .where(TelegramDeveloperApp.is_active.is_(True))
            .order_by(TelegramDeveloperApp.id.asc())
            .limit(1)
        )
        candidate = result.scalar_one_or_none()
        if candidate is None:
            return None

        if setting is None:
            session.add(AppSetting(key=DEFAULT_APP_SETTING_KEY, value=str(candidate)))
        else:
            setting.value = str(candidate)
        return int(candidate)

    async def get_user_preferred_app_id(self, session: Any, user_id: int) -> Optional[int]:
        """Get user-level preferred app id from app_settings."""
        row = await session.get(AppSetting, _user_app_key(user_id))
        if not row:
            return None
        value = (row.value or "").strip()
        if not value:
            return None
        try:
            app_id = int(value)
        except Exception:
            return None
        app = await session.get(TelegramDeveloperApp, app_id)
        if not app or not app.is_active:
            return None
        return app_id

    async def set_user_preferred_app_id(self, user_id: int, app_id: Optional[int]) -> Dict[str, Optional[int]]:
        """Set/clear user-level preferred app id."""
        async with get_async_session() as session:
            key = _user_app_key(user_id)
            row = await session.get(AppSetting, key)
            old_app_id: Optional[int] = None
            if row and (row.value or "").strip():
                try:
                    old_app_id = int((row.value or "").strip())
                except Exception:
                    old_app_id = None
            if app_id is None:
                if row is not None:
                    await session.delete(row)
                await session.commit()
                return {"old_app_id": old_app_id, "new_app_id": None}

            app = await session.get(TelegramDeveloperApp, int(app_id))
            if not app:
                raise HTTPException(status_code=404, detail="开发者应用不存在")
            if row is None:
                session.add(AppSetting(key=key, value=str(int(app_id))))
            else:
                row.value = str(int(app_id))
            await session.commit()
            return {"old_app_id": old_app_id, "new_app_id": int(app_id)}

    async def resolve_credentials(
        self,
        *,
        session: Any,
        developer_app_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> DeveloperAppCredentials:
        """
        Resolve credentials with priority:
        explicit developer_app_id -> user preferred app -> global default app -> env fallback.
        """
        target_id: Optional[int] = int(developer_app_id) if developer_app_id else None

        if target_id is None and user_id is not None:
            target_id = await self.get_user_preferred_app_id(session, int(user_id))

        if target_id is None:
            target_id = await self.get_default_app_id(session)

        explicit_app_requested = developer_app_id is not None
        if target_id is not None:
            row = await session.get(TelegramDeveloperApp, int(target_id))
            if row and row.is_active:
                api_hash = decrypt_proxy_password(row.api_hash_encrypted)
                return DeveloperAppCredentials(
                    app_id=int(row.id),
                    api_id=int(row.api_id),
                    api_hash=api_hash,
                    credentials_version=int(row.credentials_version or 1),
                    source="db",
                )
            if explicit_app_requested:
                if row is None:
                    raise HTTPException(status_code=404, detail="开发者应用不存在")
                raise HTTPException(status_code=400, detail="开发者应用未启用")

        return self._env_credentials_or_error()

    async def resolve_credentials_for_account(self, account_id: str) -> DeveloperAppCredentials:
        """Resolve credentials by account binding."""
        async with get_async_session() as session:
            result = await session.execute(
                select(Account.developer_app_id, Account.user_id)
                .where(Account.account_id == account_id)
                .limit(1)
            )
            row = result.first()
            if not row:
                raise HTTPException(status_code=404, detail="账号不存在")
            return await self.resolve_credentials(
                session=session,
                developer_app_id=row.developer_app_id,
                user_id=row.user_id,
            )

    async def choose_login_credentials_for_user(self, user_id: int) -> DeveloperAppCredentials:
        """
        Choose credentials for new QR-login session:
        1) most recent account's developer_app_id
        2) user preferred app
        3) global default
        4) env fallback
        """
        async with get_async_session() as session:
            recent_app = await session.execute(
                select(Account.developer_app_id)
                .where(
                    and_(
                        Account.user_id == int(user_id),
                        Account.developer_app_id.is_not(None),
                    )
                )
                .order_by(Account.created_at.desc())
                .limit(1)
            )
            preferred_app_id = recent_app.scalar_one_or_none()

        assignable_app_id = await self.resolve_assignable_app_id(
            user_id=int(user_id),
            preferred_app_id=preferred_app_id,
            exclude_account_id=None,
        )

        async with get_async_session() as session:
            return await self.resolve_credentials(
                session=session,
                developer_app_id=assignable_app_id,
                user_id=user_id,
            )

    async def list_apps(self) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(TelegramDeveloperApp).order_by(TelegramDeveloperApp.id.asc())
                )
            ).scalars().all()
            default_id = await self.get_default_app_id(session)

            usage_result = await session.execute(
                select(
                    Account.developer_app_id,
                    func.count(Account.account_id),
                )
                .where(Account.developer_app_id.is_not(None))
                .group_by(Account.developer_app_id)
            )
            usage_map = {int(row[0]): int(row[1]) for row in usage_result.all() if row[0] is not None}

            data: List[Dict[str, Any]] = []
            for row in rows:
                data.append(
                    {
                        "id": int(row.id),
                        "app_name": row.app_name,
                        "api_id": int(row.api_id),
                        "is_active": bool(row.is_active),
                        "max_accounts": int(row.max_accounts or 0),
                        "credentials_version": int(row.credentials_version or 1),
                        "last_rotated_at": row.last_rotated_at.isoformat() if row.last_rotated_at else None,
                        "notes": row.notes,
                        "is_default": int(row.id) == int(default_id) if default_id is not None else False,
                        "account_usage": int(usage_map.get(int(row.id), 0)),
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    }
                )
            return data

    async def create_app(
        self,
        *,
        app_name: str,
        api_id: int,
        api_hash: str,
        is_active: bool = True,
        max_accounts: int = 0,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        app_name = (app_name or "").strip()
        if not app_name:
            raise HTTPException(status_code=400, detail="应用名称不能为空")
        if not api_hash:
            raise HTTPException(status_code=400, detail="API_HASH 不能为空")

        encrypted_hash = encrypt_proxy_password(api_hash.strip())

        async with get_async_session() as session:
            existing = await session.execute(
                select(TelegramDeveloperApp.id).where(TelegramDeveloperApp.api_id == int(api_id)).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                raise HTTPException(status_code=400, detail="该 API_ID 已存在")

            row = TelegramDeveloperApp(
                app_name=app_name,
                api_id=int(api_id),
                api_hash_encrypted=encrypted_hash,
                is_active=bool(is_active),
                max_accounts=max(0, int(max_accounts or 0)),
                credentials_version=1,
                notes=(notes or "").strip() or None,
            )
            session.add(row)
            await session.flush()

            default_row = await session.get(AppSetting, DEFAULT_APP_SETTING_KEY)
            if default_row is None:
                session.add(AppSetting(key=DEFAULT_APP_SETTING_KEY, value=str(row.id)))

            await session.commit()
            return {
                "id": int(row.id),
                "app_name": row.app_name,
                "api_id": int(row.api_id),
                "is_active": bool(row.is_active),
                "max_accounts": int(row.max_accounts or 0),
                "credentials_version": int(row.credentials_version or 1),
                "last_rotated_at": row.last_rotated_at.isoformat() if row.last_rotated_at else None,
                "notes": row.notes,
            }

    async def update_app(
        self,
        app_id: int,
        *,
        app_name: Optional[str] = None,
        api_hash: Optional[str] = None,
        is_active: Optional[bool] = None,
        max_accounts: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with get_async_session() as session:
            row = await session.get(TelegramDeveloperApp, int(app_id))
            if not row:
                raise HTTPException(status_code=404, detail="开发者应用不存在")

            old_value = self._snapshot_app(row)
            rotated_accounts = 0
            if app_name is not None:
                normalized = app_name.strip()
                if not normalized:
                    raise HTTPException(status_code=400, detail="应用名称不能为空")
                row.app_name = normalized
            if api_hash is not None:
                normalized_hash = api_hash.strip()
                if not normalized_hash:
                    raise HTTPException(status_code=400, detail="API_HASH 不能为空")
                should_rotate = True
                try:
                    current_hash = decrypt_proxy_password(row.api_hash_encrypted)
                    should_rotate = current_hash != normalized_hash
                except Exception:
                    should_rotate = True

                row.api_hash_encrypted = encrypt_proxy_password(normalized_hash)
                if should_rotate:
                    now = datetime.now()
                    row.credentials_version = int(row.credentials_version or 1) + 1
                    row.last_rotated_at = now
                    result = await session.execute(
                        update(Account)
                        .where(Account.developer_app_id == int(row.id))
                        .values(
                            reauth_required=True,
                            reauth_reason="api_hash_rotated",
                            reauth_required_at=now,
                            health_status="offline",
                        )
                    )
                    rotated_accounts = int(result.rowcount or 0)
            if is_active is not None:
                row.is_active = bool(is_active)
            if max_accounts is not None:
                row.max_accounts = max(0, int(max_accounts))
            if notes is not None:
                row.notes = notes.strip() or None

            await session.commit()
            new_value = self._snapshot_app(row)
            return {
                "id": int(row.id),
                "app_name": row.app_name,
                "api_id": int(row.api_id),
                "is_active": bool(row.is_active),
                "max_accounts": int(row.max_accounts or 0),
                "credentials_version": int(row.credentials_version or 1),
                "last_rotated_at": row.last_rotated_at.isoformat() if row.last_rotated_at else None,
                "rotated_accounts": rotated_accounts,
                "old_value": old_value,
                "new_value": new_value,
                "notes": row.notes,
            }

    async def set_default_app(self, app_id: int) -> Dict[str, Optional[int]]:
        async with get_async_session() as session:
            row = await session.get(TelegramDeveloperApp, int(app_id))
            if not row:
                raise HTTPException(status_code=404, detail="开发者应用不存在")
            if not row.is_active:
                raise HTTPException(status_code=400, detail="开发者应用未启用，不能设为默认")

            setting = await session.get(AppSetting, DEFAULT_APP_SETTING_KEY)
            old_default_id = None
            if setting and (setting.value or "").strip():
                try:
                    old_default_id = int((setting.value or "").strip())
                except Exception:
                    old_default_id = None
            if setting is None:
                session.add(AppSetting(key=DEFAULT_APP_SETTING_KEY, value=str(int(app_id))))
            else:
                setting.value = str(int(app_id))
            await session.commit()
            return {
                "old_default_app_id": old_default_id,
                "new_default_app_id": int(app_id),
            }


_developer_app_service: Optional[DeveloperAppService] = None


def get_developer_app_service() -> DeveloperAppService:
    """Get singleton developer app service."""
    global _developer_app_service
    if _developer_app_service is None:
        _developer_app_service = DeveloperAppService()
    return _developer_app_service
