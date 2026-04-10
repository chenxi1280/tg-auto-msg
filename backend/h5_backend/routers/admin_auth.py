"""Backoffice admin / agent authentication API."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.database.schema.models import AdminAccount
from backend.h5_backend.dependencies import get_current_admin_account
from backend.h5_backend.services.admin_auth.service import get_admin_auth_service
from backend.h5_backend.services.admin_panel.service import get_admin_panel_service

router = APIRouter(prefix="/api/admin-auth", tags=["后台认证"])


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)


def _serialize_auth_payload(token: str, data: dict) -> dict:
    return {
        "success": True,
        "data": {
            "access_token": token,
            "token_type": "bearer",
            **data,
        },
    }


@router.post("/login")
async def admin_login(payload: AdminLoginRequest):
    service = get_admin_auth_service()
    panel_service = get_admin_panel_service()
    token, account = await service.login(payload.username, payload.password)
    profile = await panel_service.get_profile(account)
    return _serialize_auth_payload(token, profile)


@router.get("/me")
async def admin_me(current_admin: AdminAccount = Depends(get_current_admin_account)):
    panel_service = get_admin_panel_service()
    return {"success": True, "data": await panel_service.get_profile(current_admin)}


@router.post("/logout")
async def admin_logout(current_admin: AdminAccount = Depends(get_current_admin_account)):
    return {"success": True, "message": f"{current_admin.username} 已退出"}


@router.post("/change-password")
async def admin_change_password(
    payload: ChangePasswordRequest,
    current_admin: AdminAccount = Depends(get_current_admin_account),
):
    service = get_admin_auth_service()
    panel_service = get_admin_panel_service()
    updated = await service.change_password(current_admin, payload.current_password, payload.new_password)
    return {"success": True, "message": "密码已更新", "data": await panel_service.get_profile(updated)}
