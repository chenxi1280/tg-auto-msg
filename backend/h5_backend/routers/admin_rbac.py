"""RBAC routes for admin account, role and permission management."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.database.schema.models import AdminAccount
from backend.h5_backend.dependencies import require_admin_permissions
from backend.h5_backend.services.admin_rbac.service import get_admin_rbac_service

router = APIRouter(tags=["后台 RBAC"])


class CreateRoleRequest(BaseModel):
    role_key: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)


class UpdateRoleRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    status: Optional[str] = Field(default=None, min_length=1, max_length=20)


class UpdateRolePermissionsRequest(BaseModel):
    permission_codes: List[str] = Field(default_factory=list)


class CreateAdminAccountRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)
    role_code: str = Field(..., min_length=1, max_length=32)
    role_keys: List[str] = Field(default_factory=list)
    parent_account_id: Optional[int] = Field(default=None, ge=1)
    contact_name: Optional[str] = Field(default=None, max_length=100)
    contact_phone: Optional[str] = Field(default=None, max_length=50)


class UpdateAdminAccountRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    status: Optional[str] = Field(default=None, min_length=1, max_length=20)
    contact_name: Optional[str] = Field(default=None, max_length=100)
    contact_phone: Optional[str] = Field(default=None, max_length=50)


class UpdateAdminAccountRolesRequest(BaseModel):
    role_keys: List[str] = Field(..., min_length=1)


class ResetAdminAccountPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


@router.get("/api/admin/rbac/permissions")
async def list_permissions(
    current_admin: AdminAccount = Depends(require_admin_permissions("rbac.permissions.read")),
):
    service = get_admin_rbac_service()
    return {"success": True, "data": await service.list_permissions()}


@router.get("/api/admin/rbac/roles")
async def list_roles(
    current_admin: AdminAccount = Depends(require_admin_permissions("rbac.roles.read")),
):
    service = get_admin_rbac_service()
    return {"success": True, "data": await service.list_roles()}


@router.post("/api/admin/rbac/roles")
async def create_role(
    payload: CreateRoleRequest,
    current_admin: AdminAccount = Depends(require_admin_permissions("rbac.roles.write")),
):
    service = get_admin_rbac_service()
    data = await service.create_role(
        current_admin=current_admin,
        role_key=payload.role_key,
        display_name=payload.display_name,
        description=payload.description,
    )
    return {"success": True, "message": "角色已创建", "data": data}


@router.put("/api/admin/rbac/roles/{role_id}")
async def update_role(
    role_id: int,
    payload: UpdateRoleRequest,
    current_admin: AdminAccount = Depends(require_admin_permissions("rbac.roles.write")),
):
    service = get_admin_rbac_service()
    data = await service.update_role(
        current_admin=current_admin,
        role_id=role_id,
        display_name=payload.display_name,
        description=payload.description,
        status=payload.status,
    )
    return {"success": True, "message": "角色已更新", "data": data}


@router.put("/api/admin/rbac/roles/{role_id}/permissions")
async def update_role_permissions(
    role_id: int,
    payload: UpdateRolePermissionsRequest,
    current_admin: AdminAccount = Depends(require_admin_permissions("rbac.roles.write", "rbac.permissions.read")),
):
    service = get_admin_rbac_service()
    data = await service.update_role_permissions(
        current_admin=current_admin,
        role_id=role_id,
        permission_codes=payload.permission_codes,
    )
    return {"success": True, "message": "角色权限已更新", "data": data}


@router.get("/api/admin/admin-accounts")
async def list_admin_accounts(
    search: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    role_key: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("admin_accounts.read")),
):
    service = get_admin_rbac_service()
    data = await service.list_admin_accounts(
        search=search,
        status=status,
        role_key=role_key,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": data}


@router.post("/api/admin/admin-accounts")
async def create_admin_account(
    payload: CreateAdminAccountRequest,
    current_admin: AdminAccount = Depends(require_admin_permissions("admin_accounts.write")),
):
    service = get_admin_rbac_service()
    data = await service.create_admin_account(
        current_admin=current_admin,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        role_code=payload.role_code,
        role_keys=payload.role_keys,
        parent_account_id=payload.parent_account_id,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
    )
    return {"success": True, "message": "后台账号已创建", "data": data}


@router.put("/api/admin/admin-accounts/{account_id}")
async def update_admin_account(
    account_id: int,
    payload: UpdateAdminAccountRequest,
    current_admin: AdminAccount = Depends(require_admin_permissions("admin_accounts.write")),
):
    service = get_admin_rbac_service()
    data = await service.update_admin_account(
        current_admin=current_admin,
        account_id=account_id,
        display_name=payload.display_name,
        status=payload.status,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
    )
    return {"success": True, "message": "后台账号已更新", "data": data}


@router.put("/api/admin/admin-accounts/{account_id}/roles")
async def update_admin_account_roles(
    account_id: int,
    payload: UpdateAdminAccountRolesRequest,
    current_admin: AdminAccount = Depends(require_admin_permissions("admin_accounts.write", "rbac.roles.read")),
):
    service = get_admin_rbac_service()
    data = await service.update_admin_account_roles(
        current_admin=current_admin,
        account_id=account_id,
        role_keys=payload.role_keys,
    )
    return {"success": True, "message": "后台账号角色已更新", "data": data}


@router.post("/api/admin/admin-accounts/{account_id}/reset-password")
async def reset_admin_account_password(
    account_id: int,
    payload: ResetAdminAccountPasswordRequest,
    current_admin: AdminAccount = Depends(require_admin_permissions("admin_accounts.reset_password")),
):
    service = get_admin_rbac_service()
    data = await service.reset_admin_account_password(
        current_admin=current_admin,
        account_id=account_id,
        new_password=payload.new_password,
    )
    return {"success": True, "message": "后台账号密码已重置", "data": data}
