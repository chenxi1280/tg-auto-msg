"""Authentication domain service for H5 API."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import warnings
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional, Tuple

import bcrypt
from fastapi import HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.config.core.settings import settings
from backend.database.schema.models import User
from backend.database.runtime.session import get_async_session

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7
PBKDF2_SCHEME = "pbkdf2_sha256"
PBKDF2_DEFAULT_ROUNDS = 200_000
PBKDF2_SALT_BYTES = 16


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


@lru_cache(maxsize=1)
def _get_legacy_passlib_context():
    # Keep verification compatibility for historical passlib PBKDF2 hashes without
    # leaking the Python 3.13 `crypt` deprecation warning into app startup/tests.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=".*'crypt' is deprecated and slated for removal in Python 3.13.*",
            category=DeprecationWarning,
        )
        from passlib.context import CryptContext  # type: ignore

    return CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")


class AuthService:
    """Auth business service."""

    def __init__(self) -> None:
        self._secret_key = settings.secret_key

    @staticmethod
    def _hash_pbkdf2(password: str, *, salt: bytes, rounds: int) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)

    @classmethod
    def _verify_current_pbkdf2_hash(cls, plain_password: str, hashed_password: str) -> bool:
        try:
            _scheme, rounds_raw, salt_encoded, digest_encoded = hashed_password.split("$", 3)
            rounds = int(rounds_raw)
            salt = _b64decode(salt_encoded)
            expected_digest = _b64decode(digest_encoded)
        except (TypeError, ValueError, base64.binascii.Error):
            return False
        actual_digest = cls._hash_pbkdf2(plain_password, salt=salt, rounds=rounds)
        return hmac.compare_digest(actual_digest, expected_digest)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify plaintext password against hash."""
        normalized_hash = str(hashed_password or "").strip()
        if not normalized_hash:
            return False
        if normalized_hash.startswith(f"{PBKDF2_SCHEME}$"):
            return self._verify_current_pbkdf2_hash(plain_password, normalized_hash)
        if normalized_hash.startswith("$pbkdf2-sha256$"):
            return bool(_get_legacy_passlib_context().verify(plain_password, normalized_hash))
        if normalized_hash.startswith("$2"):
            try:
                return bcrypt.checkpw(plain_password.encode("utf-8"), normalized_hash.encode("utf-8"))
            except ValueError:
                return False
        return False

    def get_password_hash(self, password: str) -> str:
        """Generate password hash."""
        salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
        digest = self._hash_pbkdf2(password, salt=salt, rounds=PBKDF2_DEFAULT_ROUNDS)
        return f"{PBKDF2_SCHEME}${PBKDF2_DEFAULT_ROUNDS}${_b64encode(salt)}${_b64encode(digest)}"

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
            if str(payload.get("scope") or "user") != "user":
                raise credentials_exception
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

        access_token = self.create_access_token(data={"sub": new_user.id, "username": new_user.username, "scope": "user"})
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

        access_token = self.create_access_token(data={"sub": user.id, "username": user.username, "scope": "user"})
        return access_token, user


_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """Get singleton auth service instance."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
