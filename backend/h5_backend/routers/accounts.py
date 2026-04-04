"""Account and resource API routes."""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel

from backend.database.schema.models import User
from backend.h5_backend.routers.auth import get_current_user
from backend.h5_backend.services.account.service import get_account_service

router = APIRouter(tags=["账号"])

class RenewAuthorizationRequest(BaseModel):
    card_code: str


@router.get("/api/accounts/")
async def get_accounts(
    probe: bool = False,
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的所有账号"""
    service = get_account_service()
    data = await service.list_accounts(current_user.id, probe=probe)
    return {"success": True, "data": data}


@router.post("/api/accounts/{account_id}/sync")
async def sync_account_resources(
    account_id: str,
    background_tasks: BackgroundTasks,
    wait: bool = False,
    current_user: User = Depends(get_current_user),
):
    """同步账号的 Telegram 资源"""
    service = get_account_service()
    result = await service.sync_resources(account_id, current_user.id, background_tasks, wait=wait)
    return {"success": True, **result}


@router.post("/api/accounts/sync-all")
async def sync_all_account_resources(
    background_tasks: BackgroundTasks,
    wait: bool = False,
    current_user: User = Depends(get_current_user),
):
    """同步当前用户下所有已登录账号的 Telegram 资源。"""
    service = get_account_service()
    result = await service.sync_all_resources(current_user.id, background_tasks, wait=wait)
    return {"success": True, **result}


@router.get("/api/accounts/{account_id}/resources")
async def get_account_resources(
    account_id: str,
    peer_type: Optional[str] = None,
    is_active: bool = True,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """获取账号的资源列表"""
    service = get_account_service()
    data = await service.list_resources(
        account_id,
        current_user.id,
        peer_type=peer_type,
        is_active=is_active,
        search=search,
    )
    return {"success": True, "data": data}


@router.post("/api/accounts/{account_id}/disable")
async def disable_account(account_id: str, current_user: User = Depends(get_current_user)):
    """禁用账号"""
    service = get_account_service()
    await service.set_account_enabled(account_id, current_user.id, enabled=False)
    return {"success": True, "message": "账号已禁用"}


@router.post("/api/accounts/{account_id}/enable")
async def enable_account(account_id: str, current_user: User = Depends(get_current_user)):
    """启用账号"""
    service = get_account_service()
    await service.set_account_enabled(account_id, current_user.id, enabled=True)
    return {"success": True, "message": "账号已启用"}


@router.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str, current_user: User = Depends(get_current_user)):
    """解绑当前 TG 账号"""
    service = get_account_service()
    await service.delete_account(account_id, current_user.id)
    return {"success": True, "message": "账号已解绑"}


@router.post("/api/accounts/{account_id}/renew-authorization")
async def renew_account_authorization(
    account_id: str,
    payload: RenewAuthorizationRequest,
    current_user: User = Depends(get_current_user),
):
    """使用卡密续费当前账号对应的唯一授权。"""
    service = get_account_service()
    data = await service.renew_account_authorization(account_id, current_user.id, payload.card_code)
    return {"success": True, "message": "授权续费成功", "data": data}
