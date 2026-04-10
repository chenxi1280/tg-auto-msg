"""Backoffice admin/agent authentication service."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Tuple

from fastapi import HTTPException, status
from jose import JWTError, jwt
from loguru import logger
from sqlalchemy import or_, select

from backend.config.core.settings import settings
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import AdminAccount, AdminAccountRole, AdminRole
from backend.h5_backend.services.auth.service import ALGORITHM, ACCESS_TOKEN_EXPIRE_DAYS, get_auth_service


class AdminAuthService:
    """Backoffice account auth and TG binding operations."""

    def __init__(self) -> None:
        self._secret_key = settings.secret_key

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return get_auth_service().verify_password(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        return get_auth_service().get_password_hash(password)

    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        to_encode = data.copy()
        if "sub" in to_encode and to_encode["sub"] is not None:
            to_encode["sub"] = str(to_encode["sub"])
        expire = datetime.utcnow() + (expires_delta or timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, self._secret_key, algorithm=ALGORITHM)

    async def get_current_admin(self, token: str) -> AdminAccount:
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的后台认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[ALGORITHM])
            if str(payload.get("scope") or "") != "admin":
                raise credentials_exception
            account_id_raw = payload.get("sub")
            if account_id_raw is None:
                raise credentials_exception
            try:
                account_id = int(account_id_raw)
            except (TypeError, ValueError) as exc:
                raise credentials_exception from exc
        except JWTError as exc:
            raise credentials_exception from exc

        async with get_async_session() as session:
            account = (
                await session.execute(
                    select(AdminAccount).where(AdminAccount.id == int(account_id)).limit(1)
                )
            ).scalar_one_or_none()

        if account is None:
            raise credentials_exception
        if account.status != "active":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="后台账号已禁用")
        return account

    async def login(self, username: str, password: str) -> Tuple[str, AdminAccount]:
        async with get_async_session() as session:
            account = (
                await session.execute(
                    select(AdminAccount).where(AdminAccount.username == (username or "").strip()).limit(1)
                )
            ).scalar_one_or_none()
            if not account or not self.verify_password(password, account.password_hash):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="后台用户名或密码错误")
            if account.status != "active":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="后台账号已禁用")
            account.last_login_at = datetime.now()

        access_token = self.create_access_token(
            data={
                "sub": account.id,
                "scope": "admin",
                "username": account.username,
                "role": account.role_code,
                "account_type": getattr(account, "account_type", None),
                "business_identity": getattr(account, "business_identity", None),
                "province_code": account.province_code,
            }
        )
        return access_token, account

    async def ensure_bootstrap_super_admin(self) -> Optional[AdminAccount]:
        username = (settings.admin_bootstrap_username or "").strip()
        password = (settings.admin_bootstrap_password or "").strip()
        display_name = (settings.admin_bootstrap_display_name or username or "超级管理员").strip()

        async with get_async_session() as session:
            existing_super_admin = (
                await session.execute(
                    select(AdminAccount)
                    .outerjoin(AdminAccountRole, AdminAccountRole.admin_account_id == AdminAccount.id)
                    .outerjoin(AdminRole, AdminRole.id == AdminAccountRole.role_id)
                    .where(
                        or_(
                            AdminAccount.role_code == "super_admin",
                            AdminRole.role_key == "super_admin",
                        ),
                        AdminAccount.province_code == settings.province_code,
                        AdminAccount.status == "active",
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing_super_admin is not None:
                return existing_super_admin

            if not username or not password:
                logger.warning(
                    "当前省份未检测到 super_admin，且未配置 ADMIN_BOOTSTRAP_USERNAME / ADMIN_BOOTSTRAP_PASSWORD，跳过自动初始化"
                )
                return None
            if len(password) < 6:
                logger.warning("ADMIN_BOOTSTRAP_PASSWORD 长度不足 6 位，跳过自动初始化 super_admin")
                return None

            username_conflict = (
                await session.execute(
                    select(AdminAccount).where(AdminAccount.username == username).limit(1)
                )
            ).scalar_one_or_none()
            if username_conflict is not None:
                logger.warning(
                    "未检测到当前省份 super_admin，但 ADMIN_BOOTSTRAP_USERNAME 已被现有后台账号占用: username={}",
                    username,
                )
                return None

            account = AdminAccount(
                username=username,
                password_hash=self.get_password_hash(password),
                role_code="super_admin",
                account_type="staff",
                business_identity=None,
                province_code=settings.province_code,
                parent_account_id=None,
                root_master_account_id=None,
                level_depth=0,
                status="active",
                settlement_mode="prepaid",
                is_credit_whitelisted=True,
                credit_limit_cents=0,
                allocated_credit_limit_cents=0,
                credit_used_cents=0,
                balance_cents=0,
                force_password_change=True,
                display_name=display_name,
                created_by=None,
            )
            session.add(account)
            await session.flush()
            logger.info(
                "已根据 .env 自动初始化 super_admin: username={}, province={}",
                account.username,
                account.province_code,
            )
            return account

    async def change_password(self, account: AdminAccount, current_password: str, new_password: str) -> AdminAccount:
        if len(new_password or "") < 6:
            raise HTTPException(status_code=400, detail="新密码至少 6 位")

        async with get_async_session() as session:
            current = await session.get(AdminAccount, int(account.id))
            if current is None:
                raise HTTPException(status_code=404, detail="后台账号不存在")
            if not self.verify_password(current_password, current.password_hash):
                raise HTTPException(status_code=400, detail="当前密码错误")
            current.password_hash = self.get_password_hash(new_password)
            current.force_password_change = False
            await session.flush()
            await session.refresh(current)
            return current


_admin_auth_service: Optional[AdminAuthService] = None


def get_admin_auth_service() -> AdminAuthService:
    global _admin_auth_service
    if _admin_auth_service is None:
        _admin_auth_service = AdminAuthService()
    return _admin_auth_service
