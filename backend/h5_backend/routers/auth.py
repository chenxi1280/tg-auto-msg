"""System user authentication API."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from backend.database.models import User
from backend.h5_backend.services.auth_service import get_auth_service

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
router = APIRouter(prefix="/api/auth", tags=["认证"])


class UserCreate(BaseModel):
    """User registration payload."""

    username: str = Field(..., min_length=3, max_length=50, description="用户名（3-50字符）")
    password: str = Field(..., min_length=6, description="密码（至少6字符）")
    email: Optional[str] = Field(None, max_length=100, description="邮箱（可选）")


class UserResponse(BaseModel):
    """User response."""

    id: int
    username: str
    email: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Resolve current user from bearer token."""
    service = get_auth_service()
    return await service.get_current_user(token)


@router.post("/register", summary="用户注册")
async def register(user_data: UserCreate):
    """注册新用户。"""
    service = get_auth_service()
    access_token, user = await service.register_user(
        username=user_data.username,
        password=user_data.password,
        email=user_data.email,
    )
    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "token_type": "bearer",
            "user": UserResponse.model_validate(user),
        },
    }


@router.post("/login", summary="用户登录")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """用户登录。"""
    service = get_auth_service()
    access_token, user = await service.login_user(
        username=form_data.username,
        password=form_data.password,
    )
    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "token_type": "bearer",
            "user": UserResponse.model_validate(user),
        },
    }


@router.get("/me", response_model=UserResponse, summary="获取当前用户信息")
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return UserResponse.model_validate(current_user)


@router.post("/logout", summary="用户登出")
async def logout(current_user: User = Depends(get_current_user)):
    """用户登出（前端清理 token）。"""
    return {"success": True, "message": "登出成功"}
