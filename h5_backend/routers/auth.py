"""
系统用户认证 API

提供用户注册、登录、获取当前用户信息等接口
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import select

from config.settings import settings
from database.models import User
from database.session import get_async_session


# ============ 配置 ============

# JWT 配置
SECRET_KEY = settings.secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

# 密码哈希上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 密码流
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# 创建路由器
router = APIRouter(prefix="/api/auth", tags=["认证"])


# ============ Pydantic 模型 ============

class UserCreate(BaseModel):
    """用户注册请求模型"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名（3-50字符）")
    password: str = Field(..., min_length=6, description="密码（至少6字符）")
    email: Optional[str] = Field(None, max_length=100, description="邮箱（可选）")


class UserResponse(BaseModel):
    """用户信息响应模型"""
    id: int
    username: str
    email: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    """JWT Token 响应模型"""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ============ 辅助函数 ============

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建 JWT Token"""
    to_encode = data.copy()

    # python-jose 要求 sub 必须是字符串，否则 decode 会抛出 JWTClaimsError
    if "sub" in to_encode and to_encode["sub"] is not None:
        to_encode["sub"] = str(to_encode["sub"])

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """
    从 JWT Token 中获取当前用户

    Args:
        token: JWT Token

    Returns:
        User 对象

    Raises:
        HTTPException: Token 无效或用户不存在
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_raw = payload.get("sub")
        if user_id_raw is None:
            raise credentials_exception

        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # 从数据库查询用户
    async with get_async_session() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用"
        )

    return user


# ============ API 路由 ============

@router.post("/register", summary="用户注册")
async def register(user_data: UserCreate):
    """
    注册新用户

    Args:
        user_data: 用户注册信息

    Returns:
        JWT Token 和用户信息

    Raises:
        HTTPException: 用户名已存在
    """
    async with get_async_session() as session:
        # 检查用户名是否已存在
        result = await session.execute(
            select(User).where(User.username == user_data.username)
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名已存在"
            )

        # 创建新用户
        new_user = User(
            username=user_data.username,
            password_hash=get_password_hash(user_data.password),
            email=user_data.email,
            is_active=True
        )

        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)

        # 生成 JWT Token
        access_token = create_access_token(
            data={"sub": new_user.id, "username": new_user.username}
        )

        return {
            "success": True,
            "data": {
                "access_token": access_token,
                "token_type": "bearer",
                "user": UserResponse.model_validate(new_user)
            }
        }


@router.post("/login", summary="用户登录")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    用户登录

    Args:
        form_data: OAuth2 表单数据（username, password）

    Returns:
        JWT Token 和用户信息

    Raises:
        HTTPException: 用户名或密码错误
    """
    async with get_async_session() as session:
        # 查询用户
        result = await session.execute(
            select(User).where(User.username == form_data.username)
        )
        user = result.scalar_one_or_none()

        # 验证用户名和密码
        if not user or not verify_password(form_data.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 检查用户是否被禁用
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="用户已被禁用"
            )

        # 生成 JWT Token
        access_token = create_access_token(
            data={"sub": user.id, "username": user.username}
        )

        return {
            "success": True,
            "data": {
                "access_token": access_token,
                "token_type": "bearer",
                "user": UserResponse.model_validate(user)
            }
        }


@router.get("/me", response_model=UserResponse, summary="获取当前用户信息")
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    获取当前登录用户的信息

    Args:
        current_user: 当前用户（通过 JWT Token 认证）

    Returns:
        用户信息
    """
    return UserResponse.model_validate(current_user)


@router.post("/logout", summary="用户登出")
async def logout(current_user: User = Depends(get_current_user)):
    """
    用户登出（仅返回成功消息，Token 由前端清除）

    Args:
        current_user: 当前用户

    Returns:
        成功消息
    """
    return {"success": True, "message": "登出成功"}
