"""Admin billing routes for card/plan management."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.h5_backend.dependencies import require_admin_token
from backend.h5_backend.services.admin.service import get_admin_billing_service

router = APIRouter(prefix="/api/admin", tags=["管理员收费"])


class UpdatePlanRequest(BaseModel):
    """Plan update payload."""

    display_name: Optional[str] = Field(default=None, max_length=100)
    price_cents: Optional[int] = Field(default=None, ge=1)
    duration_days: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class GenerateCardRequest(BaseModel):
    """Card generation payload."""

    plan_code: str = Field(..., min_length=1, max_length=32)
    quantity: int = Field(default=1, ge=1, le=500)
    duration_days: Optional[int] = Field(default=None, ge=1)
    valid_days: Optional[int] = Field(default=None, ge=1)
    prefix: str = Field(default="", max_length=20)


class ResetUserPasswordRequest(BaseModel):
    """Reset user password payload."""

    new_password: str = Field(..., min_length=6, max_length=128)


class UpdateUserSubscriptionRequest(BaseModel):
    """Update user subscription payload."""

    plan_code: Optional[str] = Field(default=None, max_length=32)
    end_at: Optional[datetime] = Field(default=None, description="ISO 时间")
    extend_days: Optional[int] = Field(default=None, ge=-3650, le=3650)
    set_inactive: bool = False


class AddProxyRequest(BaseModel):
    """Add proxy payload."""

    proxy_type: str = Field(default="socks5", min_length=3, max_length=10)
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(..., ge=1, le=65535)
    username: Optional[str] = Field(default=None, max_length=100)
    password: Optional[str] = Field(default=None, max_length=255)


class AssignProxyRequest(BaseModel):
    """Assign proxy payload."""

    account_id: str = Field(..., min_length=6, max_length=64)


class UpdatePurchaseSettingsRequest(BaseModel):
    """Purchase entry settings payload."""

    purchase_url: str = Field(..., min_length=1, max_length=500)
    purchase_button_text: str = Field(default="联系 Telegram 购买", min_length=1, max_length=50)


class CreateDeveloperAppRequest(BaseModel):
    """Create Telegram developer app payload."""

    app_name: str = Field(..., min_length=1, max_length=100)
    api_id: int = Field(..., ge=1)
    api_hash: str = Field(..., min_length=8, max_length=255)
    is_active: bool = True
    max_accounts: int = Field(default=0, ge=0)
    notes: Optional[str] = Field(default=None, max_length=255)


class UpdateDeveloperAppRequest(BaseModel):
    """Update Telegram developer app payload."""

    app_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    api_hash: Optional[str] = Field(default=None, min_length=8, max_length=255)
    is_active: Optional[bool] = None
    max_accounts: Optional[int] = Field(default=None, ge=0)
    notes: Optional[str] = Field(default=None, max_length=255)


class SetUserDeveloperAppRequest(BaseModel):
    """Assign user preferred developer app payload."""

    developer_app_id: Optional[int] = Field(default=None, ge=1)


@router.get("/plans", dependencies=[Depends(require_admin_token)])
async def admin_list_plans():
    """管理员查看套餐配置。"""
    service = get_admin_billing_service()
    data = await service.list_plans()
    return {"success": True, "data": data}


@router.get("/developer-apps", dependencies=[Depends(require_admin_token)])
async def admin_list_developer_apps():
    """管理员查询开发者应用池。"""
    service = get_admin_billing_service()
    data = await service.list_developer_apps()
    return {"success": True, "data": data}


@router.post("/developer-apps", dependencies=[Depends(require_admin_token)])
async def admin_create_developer_app(payload: CreateDeveloperAppRequest, request: Request):
    """管理员新增开发者应用。"""
    service = get_admin_billing_service()
    data = await service.create_developer_app(
        app_name=payload.app_name,
        api_id=payload.api_id,
        api_hash=payload.api_hash,
        is_active=payload.is_active,
        max_accounts=payload.max_accounts,
        notes=payload.notes,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "开发者应用已创建", "data": data}


@router.put("/developer-apps/{app_id}", dependencies=[Depends(require_admin_token)])
async def admin_update_developer_app(app_id: int, payload: UpdateDeveloperAppRequest, request: Request):
    """管理员更新开发者应用。"""
    service = get_admin_billing_service()
    data = await service.update_developer_app(
        app_id,
        app_name=payload.app_name,
        api_hash=payload.api_hash,
        is_active=payload.is_active,
        max_accounts=payload.max_accounts,
        notes=payload.notes,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "开发者应用已更新", "data": data}


@router.post("/developer-apps/{app_id}/set-default", dependencies=[Depends(require_admin_token)])
async def admin_set_default_developer_app(app_id: int, request: Request):
    """管理员设置默认开发者应用。"""
    service = get_admin_billing_service()
    await service.set_default_developer_app(
        app_id,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "默认开发者应用已更新"}


@router.get("/settings/purchase", dependencies=[Depends(require_admin_token)])
async def admin_get_purchase_settings():
    """管理员获取购买入口配置。"""
    service = get_admin_billing_service()
    data = await service.get_purchase_settings()
    return {"success": True, "data": data}


@router.put("/settings/purchase", dependencies=[Depends(require_admin_token)])
async def admin_update_purchase_settings(payload: UpdatePurchaseSettingsRequest, request: Request):
    """管理员更新购买入口配置。"""
    service = get_admin_billing_service()
    data = await service.update_purchase_settings(
        purchase_url=payload.purchase_url,
        purchase_button_text=payload.purchase_button_text,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "购买入口已更新", "data": data}


@router.put("/plans/{plan_code}", dependencies=[Depends(require_admin_token)])
async def admin_update_plan(plan_code: str, payload: UpdatePlanRequest, request: Request):
    """管理员更新套餐价格和时长。"""
    service = get_admin_billing_service()
    data = await service.update_plan(
        plan_code=plan_code,
        display_name=payload.display_name,
        price_cents=payload.price_cents,
        duration_days=payload.duration_days,
        is_active=payload.is_active,
        sort_order=payload.sort_order,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "套餐已更新", "data": data}


@router.post("/cards/generate", dependencies=[Depends(require_admin_token)])
async def admin_generate_cards(payload: GenerateCardRequest, request: Request):
    """管理员批量生成卡密。"""
    service = get_admin_billing_service()
    if payload.quantity == 1:
        data = await service.create_single_card(
            plan_code=payload.plan_code,
            duration_days=payload.duration_days,
            valid_days=payload.valid_days,
            prefix=payload.prefix,
            actor=request.headers.get("X-Admin-Token", ""),
            ip_address=request.client.host if request.client else None,
        )
        return {"success": True, "message": "卡密生成成功", "data": [data]}

    expires_at = None
    if payload.valid_days is not None:
        expires_at = datetime.now() + timedelta(days=payload.valid_days)

    data = await service.generate_cards(
        plan_code=payload.plan_code,
        quantity=payload.quantity,
        duration_days=payload.duration_days,
        expires_at=expires_at,
        prefix=payload.prefix,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "卡密生成成功", "data": data}


@router.get("/cards", dependencies=[Depends(require_admin_token)])
async def admin_list_cards(
    plan_code: Optional[str] = None,
    is_used: Optional[bool] = None,
    is_active: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
):
    """管理员查询卡密。"""
    service = get_admin_billing_service()
    data = await service.list_cards(
        plan_code=plan_code,
        is_used=is_used,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": data}


@router.post("/cards/{card_code}/disable", dependencies=[Depends(require_admin_token)])
async def admin_disable_card(card_code: str, request: Request):
    """管理员停用卡密。"""
    service = get_admin_billing_service()
    data = await service.set_card_active(
        card_code,
        is_active=False,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "卡密已停用", "data": data}


@router.post("/cards/{card_code}/enable", dependencies=[Depends(require_admin_token)])
async def admin_enable_card(card_code: str, request: Request):
    """管理员启用卡密（仅未使用卡）。"""
    service = get_admin_billing_service()
    data = await service.set_card_active(
        card_code,
        is_active=True,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "卡密已启用", "data": data}


@router.get("/users", dependencies=[Depends(require_admin_token)])
async def admin_list_users(search: Optional[str] = None, limit: int = 100, offset: int = 0):
    """管理员查询用户及订阅摘要。"""
    service = get_admin_billing_service()
    data = await service.list_users(search=search, limit=limit, offset=offset)
    return {"success": True, "data": data}


@router.get("/users/{user_id}/accounts", dependencies=[Depends(require_admin_token)])
async def admin_list_user_accounts(user_id: int):
    """管理员查看用户下所有 TG 账号。"""
    service = get_admin_billing_service()
    data = await service.list_user_accounts(user_id)
    return {"success": True, "data": data}


@router.get("/accounts/options", dependencies=[Depends(require_admin_token)])
async def admin_list_account_options(search: Optional[str] = None, limit: int = 300):
    """管理员获取账号下拉选项（代理分配用）。"""
    service = get_admin_billing_service()
    data = await service.list_account_options(search=search, limit=limit)
    return {"success": True, "data": data}


@router.delete("/accounts/{account_id}", dependencies=[Depends(require_admin_token)])
async def admin_delete_account(account_id: str, request: Request):
    """管理员删除 TG 账号。"""
    service = get_admin_billing_service()
    await service.admin_delete_account(
        account_id,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "账号已删除"}


@router.post("/users/{user_id}/reset-password", dependencies=[Depends(require_admin_token)])
async def admin_reset_user_password(user_id: int, payload: ResetUserPasswordRequest, request: Request):
    """管理员重置系统用户密码。"""
    service = get_admin_billing_service()
    await service.reset_user_password(
        user_id,
        payload.new_password,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "密码已重置"}


@router.put("/users/{user_id}/subscription", dependencies=[Depends(require_admin_token)])
async def admin_update_user_subscription(user_id: int, payload: UpdateUserSubscriptionRequest, request: Request):
    """管理员修改用户套餐有效期。"""
    service = get_admin_billing_service()
    data = await service.update_user_subscription(
        user_id=user_id,
        plan_code=payload.plan_code,
        end_at=payload.end_at,
        extend_days=payload.extend_days,
        set_inactive=payload.set_inactive,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "订阅已更新", "data": data}


@router.put("/users/{user_id}/developer-app", dependencies=[Depends(require_admin_token)])
async def admin_set_user_developer_app(user_id: int, payload: SetUserDeveloperAppRequest, request: Request):
    """管理员设置用户首选开发者应用。"""
    service = get_admin_billing_service()
    data = await service.set_user_developer_app(
        user_id,
        payload.developer_app_id,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "用户开发者应用已更新", "data": data}


@router.get("/audit-logs", dependencies=[Depends(require_admin_token)])
async def admin_list_audit_logs(
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    developer_app_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
):
    """管理员查询操作审计日志。"""
    service = get_admin_billing_service()
    data = await service.list_audit_logs(
        action=action,
        target_type=target_type,
        target_id=target_id,
        developer_app_id=developer_app_id,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": data}


@router.get("/proxies", dependencies=[Depends(require_admin_token)])
async def admin_list_proxies():
    """管理员查询所有代理。"""
    service = get_admin_billing_service()
    data = await service.list_proxies()
    return {"success": True, "data": data}


@router.post("/proxies", dependencies=[Depends(require_admin_token)])
async def admin_add_proxy(payload: AddProxyRequest, request: Request):
    """管理员添加代理。"""
    service = get_admin_billing_service()
    data = await service.add_proxy(
        proxy_type=payload.proxy_type,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "代理添加成功", "data": data}


@router.post("/proxies/{proxy_id}/check", dependencies=[Depends(require_admin_token)])
async def admin_check_proxy_health(proxy_id: int, request: Request):
    """管理员检查代理健康状态。"""
    service = get_admin_billing_service()
    data = await service.check_proxy_health(
        proxy_id,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "data": data}


@router.delete("/proxies/{proxy_id}", dependencies=[Depends(require_admin_token)])
async def admin_delete_proxy(proxy_id: int, request: Request):
    """管理员删除代理。"""
    service = get_admin_billing_service()
    await service.delete_proxy(
        proxy_id,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "代理已删除"}


@router.post("/proxies/{proxy_id}/assign", dependencies=[Depends(require_admin_token)])
async def admin_assign_proxy(proxy_id: int, payload: AssignProxyRequest, request: Request):
    """管理员分配代理到账号。"""
    service = get_admin_billing_service()
    await service.assign_proxy(
        proxy_id,
        payload.account_id,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "代理已分配"}


@router.post("/proxies/{proxy_id}/unassign", dependencies=[Depends(require_admin_token)])
async def admin_unassign_proxy(proxy_id: int, request: Request):
    """管理员解绑代理。"""
    service = get_admin_billing_service()
    await service.unassign_proxy(
        proxy_id,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "代理已解绑"}
