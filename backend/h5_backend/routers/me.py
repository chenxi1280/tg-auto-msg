"""My page API routes: profile, license slots and password."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.database.schema.models import User
from backend.h5_backend.routers.auth import get_current_user
from backend.h5_backend.services.me.service import get_me_service

router = APIRouter(tags=["我的"])


class ActivateCardRequest(BaseModel):
    """Card activation request."""

    card_code: str = Field(..., min_length=4, max_length=64, description="卡密")
    account_id: str | None = Field(default=None, min_length=8, max_length=64, description="可选，按 TG 账号定位现有套餐位进行续费")
    slot_id: str | None = Field(default=None, min_length=8, max_length=64, description="可选，指定套餐位续费")


class ChangePasswordRequest(BaseModel):
    """Password change request."""

    old_password: str = Field(..., min_length=6, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=128)


class UpdateProfileRequest(BaseModel):
    """Editable profile fields."""

    email: str | None = Field(default=None, max_length=100)


@router.get("/api/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """获取我的信息（基础信息 + 套餐位概览 + Key规格）"""
    service = get_me_service()
    data = await service.get_profile(current_user.id)
    return {"success": True, "data": data}


@router.get("/api/me/license-status")
async def get_license_status(current_user: User = Depends(get_current_user)):
    """获取套餐位状态"""
    service = get_me_service()
    data = await service.get_license_status(current_user.id)
    return {"success": True, "data": data}


@router.get("/api/me/plans")
async def get_plans(active_only: bool = True, current_user: User = Depends(get_current_user)):
    """获取可购买的 Key 规格列表。"""
    service = get_me_service()
    if active_only:
        data = await service.list_active_plans()
    else:
        data = await service.list_active_plans()
    _ = current_user
    return {"success": True, "data": data}


@router.post("/api/me/activate-card")
async def activate_card(payload: ActivateCardRequest, current_user: User = Depends(get_current_user)):
    """激活卡密"""
    service = get_me_service()
    data = await service.activate_card(current_user.id, payload.card_code, payload.account_id, payload.slot_id)
    return {"success": True, "message": "卡密激活成功", "data": data}


@router.post("/api/me/change-password")
async def change_password(payload: ChangePasswordRequest, current_user: User = Depends(get_current_user)):
    """修改登录密码"""
    service = get_me_service()
    await service.change_password(current_user.id, payload.old_password, payload.new_password)
    return {"success": True, "message": "密码修改成功"}


@router.put("/api/me/profile")
async def update_profile(payload: UpdateProfileRequest, current_user: User = Depends(get_current_user)):
    """修改基础信息（当前支持邮箱）"""
    service = get_me_service()
    data = await service.update_profile(current_user.id, payload.email)
    return {"success": True, "message": "基本信息已更新", "data": data}
