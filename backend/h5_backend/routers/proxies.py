"""Proxy management API routes."""
from fastapi import APIRouter, Depends

from backend.database.schema.models import User
from backend.h5_backend.routers.auth import get_current_user
from backend.h5_backend.services.proxy.service import get_proxy_service

router = APIRouter(tags=["代理"])


@router.get("/api/proxies/")
async def get_proxies(current_user: User = Depends(get_current_user)):
    """获取所有代理"""
    service = get_proxy_service()
    data = await service.list_proxies(current_user.id)
    return {"success": True, "data": data}


@router.post("/api/proxies/")
async def add_proxy(proxy_data: dict, current_user: User = Depends(get_current_user)):
    """添加新代理"""
    service = get_proxy_service()
    data = await service.add_proxy(proxy_data)
    return {"success": True, "data": data}


@router.post("/api/proxies/{proxy_id}/check")
async def check_proxy_health(proxy_id: int, current_user: User = Depends(get_current_user)):
    """检查代理健康状态"""
    service = get_proxy_service()
    data = await service.check_health(proxy_id, current_user.id)
    return {"success": True, "data": data}


@router.delete("/api/proxies/{proxy_id}")
async def delete_proxy(proxy_id: int, current_user: User = Depends(get_current_user)):
    """删除代理"""
    service = get_proxy_service()
    await service.delete_proxy(proxy_id, current_user.id)
    return {"success": True, "message": "代理已删除"}


@router.post("/api/proxies/{proxy_id}/assign")
async def assign_proxy(proxy_id: int, account_id: str, current_user: User = Depends(get_current_user)):
    """将代理分配给账号"""
    service = get_proxy_service()
    await service.assign_proxy(proxy_id, account_id, current_user.id)
    return {"success": True, "message": "代理已分配"}


@router.post("/api/proxies/{proxy_id}/unassign")
async def unassign_proxy(proxy_id: int, current_user: User = Depends(get_current_user)):
    """解绑代理"""
    service = get_proxy_service()
    await service.unassign_proxy(proxy_id, current_user.id)
    return {"success": True, "message": "代理已解绑"}
