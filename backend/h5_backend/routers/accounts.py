"""Account and resource API routes."""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends

from backend.database.schema.models import User
from backend.h5_backend.routers.auth import get_current_user
from backend.h5_backend.services.account.service import get_account_service

router = APIRouter(tags=["账号"])


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


@router.post("/api/accounts/{account_id}/bind-code")
async def refresh_account_bind_code(
    account_id: str,
    refresh: bool = True,
    current_user: User = Depends(get_current_user),
):
    """获取或刷新账号绑定码（用于 /bind 快捷操作）。"""
    service = get_account_service()
    data = await service.issue_bind_code(account_id, current_user.id, refresh=refresh)
    return {"success": True, "data": data}


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
    """删除账号"""
    service = get_account_service()
    await service.delete_account(account_id, current_user.id)
    return {"success": True, "message": "账号已删除"}
