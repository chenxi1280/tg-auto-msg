"""Authentication domain service for H5 API."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Tuple

from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.config.core.settings import settings
from backend.database.schema.models import User
from backend.database.runtime.session import get_async_session

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7


class AuthService:
    """Auth business service."""

    def __init__(self) -> None:
        # Use PBKDF2 for new hashes and keep bcrypt verification for legacy users.
        self._pwd_context = CryptContext(
            schemes=["pbkdf2_sha256", "bcrypt"],
            deprecated="auto",
        )
        self._secret_key = settings.secret_key

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify plaintext password against hash."""
        return self._pwd_context.verify(plain_password, hashed_password)

    def get_password_hash(self, password: str) -> str:
        """Generate password hash."""
        return self._pwd_context.hash(password)

    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """Create JWT token."""
        to_encode = data.copy()
        if "sub" in to_encode and to_encode["sub"] is not None:
            to_encode["sub"] = str(to_encode["sub"])

        expire = datetime.utcnow() + (expires_delta or timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, self._secret_key, algorithm=ALGORITHM)

    async def get_current_user(self, token: str) -> User:
        """Resolve current user from JWT token."""
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )

        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[ALGORITHM])
            user_id_raw = payload.get("sub")
            if user_id_raw is None:
                raise credentials_exception
            try:
                user_id = int(user_id_raw)
            except (TypeError, ValueError) as exc:
                raise credentials_exception from exc
        except JWTError as exc:
            raise credentials_exception from exc

        async with get_async_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

        if user is None:
            raise credentials_exception

        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户已被禁用")

        return user

    async def register_user(self, username: str, password: str, email: Optional[str]) -> Tuple[str, User]:
        """Register user and return token + user."""
        normalized_email = (email or "").strip().lower() or None

        async with get_async_session() as session:
            result = await session.execute(select(User).where(User.username == username))
            existing_user = result.scalar_one_or_none()
            if existing_user:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已存在")

            if normalized_email:
                existing_email = await session.execute(
                    select(User.id).where(func.lower(User.email) == normalized_email).limit(1)
                )
                if existing_email.scalar_one_or_none() is not None:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邮箱已被占用")

            new_user = User(
                username=username,
                password_hash=self.get_password_hash(password),
                email=normalized_email,
                is_active=True,
            )
            session.add(new_user)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名或邮箱已存在") from exc
            await session.refresh(new_user)

        access_token = self.create_access_token(data={"sub": new_user.id, "username": new_user.username})
        return access_token, new_user

    async def login_user(self, username: str, password: str) -> Tuple[str, User]:
        """Login user and return token + user."""
        async with get_async_session() as session:
            result = await session.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()

        if not user or not self.verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户已被禁用")

        access_token = self.create_access_token(data={"sub": user.id, "username": user.username})
        return access_token, user


_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """Get singleton auth service instance."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
