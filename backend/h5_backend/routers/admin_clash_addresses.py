"""Admin routes for Clash subscription/config address management."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from backend.database.schema.models import AdminAccount
from backend.h5_backend.dependencies import require_admin_permissions
from backend.h5_backend.services.admin.clash_address_service import get_clash_address_service

router = APIRouter(tags=["后台 Clash 地址"])


class CreateClashAddressRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., min_length=1, max_length=2000)
    is_active: bool = False
    remark: str = Field(default="", max_length=255)


class UpdateClashAddressRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: Optional[str] = Field(default=None, max_length=2000)
    is_active: bool = False
    remark: str = Field(default="", max_length=255)


def _actor(current_admin: AdminAccount) -> str:
    return f"{current_admin.username}#{current_admin.id}"


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


@router.get("/api/admin/system/clash-addresses")
async def list_clash_addresses(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("system.settings.read")),
):
    service = get_clash_address_service()
    data = await service.list_addresses(limit=limit, offset=offset)
    return {"success": True, "data": data}


@router.post("/api/admin/system/clash-addresses")
async def create_clash_address(
    payload: CreateClashAddressRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("system.settings.update")),
):
    service = get_clash_address_service()
    data = await service.create_address(
        name=payload.name,
        url=payload.url,
        is_active=payload.is_active,
        remark=payload.remark,
        actor=_actor(current_admin),
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "Clash 地址已新增", "data": data}


@router.put("/api/admin/system/clash-addresses/{address_id}")
async def update_clash_address(
    address_id: int,
    payload: UpdateClashAddressRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("system.settings.update")),
):
    service = get_clash_address_service()
    data = await service.update_address(
        address_id,
        name=payload.name,
        url=payload.url,
        is_active=payload.is_active,
        remark=payload.remark,
        actor=_actor(current_admin),
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "Clash 地址已更新", "data": data}


@router.delete("/api/admin/system/clash-addresses/{address_id}")
async def delete_clash_address(
    address_id: int,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("system.settings.update")),
):
    service = get_clash_address_service()
    await service.delete_address(address_id, actor=_actor(current_admin), ip_address=_client_ip(request))
    return {"success": True, "message": "Clash 地址已删除"}


@router.post("/api/admin/system/clash-addresses/{address_id}/activate")
async def activate_clash_address(
    address_id: int,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("system.settings.update")),
):
    service = get_clash_address_service()
    data = await service.activate_address(address_id, actor=_actor(current_admin), ip_address=_client_ip(request))
    return {"success": True, "message": "Clash 地址已启用", "data": data}
