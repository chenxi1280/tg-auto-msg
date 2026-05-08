"""JWT/RBAC routes for legacy super-admin system capabilities."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.database.schema.models import AdminAccount
from backend.h5_backend.dependencies import require_admin_permissions
from backend.h5_backend.services.admin.service import get_admin_license_service

router = APIRouter(tags=["后台系统配置"])


class UpdatePlanRequest(BaseModel):
    plan_code: Optional[str] = Field(default=None, min_length=1, max_length=32)
    display_name: Optional[str] = Field(default=None, max_length=100)
    billing_cycle: Optional[str] = Field(default=None, min_length=1, max_length=20)
    price_cents: Optional[int] = Field(default=None, ge=1)
    duration_days: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class GenerateCardRequest(BaseModel):
    plan_code: str = Field(..., min_length=1, max_length=32)
    quantity: int = Field(default=1, ge=1, le=500)
    valid_days: Optional[int] = Field(default=None, ge=1)
    prefix: str = Field(default="", max_length=20)


class ResetUserPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


class AddProxyRequest(BaseModel):
    proxy_type: str = Field(default="socks5", min_length=3, max_length=10)
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(..., ge=1, le=65535)
    username: Optional[str] = Field(default=None, max_length=100)
    password: Optional[str] = Field(default=None, max_length=255)


class AssignProxyRequest(BaseModel):
    account_id: str = Field(..., min_length=6, max_length=64)


class PurchaseButtonRequest(BaseModel):
    text: str = Field(default="", max_length=50)
    url: str = Field(default="", max_length=500)


class UpdatePurchaseSettingsRequest(BaseModel):
    purchase_url: str = Field(default="", max_length=500)
    purchase_button_text: str = Field(default="联系 Telegram 购买", max_length=50)
    purchase_buttons: Optional[List[PurchaseButtonRequest]] = Field(default=None, max_length=2)


class UpdateBotNoticeSettingsRequest(BaseModel):
    enabled: bool = False
    entry_button_text: str = Field(default="📢 公告栏", max_length=20)
    message_text: str = Field(default="", max_length=3000)
    target_url: str = Field(default="", max_length=500)


class CreateDeveloperAppRequest(BaseModel):
    app_name: str = Field(..., min_length=1, max_length=100)
    api_id: int = Field(..., ge=1)
    api_hash: str = Field(..., min_length=8, max_length=255)
    is_active: bool = True
    max_accounts: int = Field(default=0, ge=0)
    selection_weight: int = Field(default=100, ge=1, le=100000)
    notes: Optional[str] = Field(default=None, max_length=255)


class UpdateDeveloperAppRequest(BaseModel):
    app_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    api_hash: Optional[str] = Field(default=None, min_length=8, max_length=255)
    is_active: Optional[bool] = None
    max_accounts: Optional[int] = Field(default=None, ge=0)
    selection_weight: Optional[int] = Field(default=None, ge=1, le=100000)
    notes: Optional[str] = Field(default=None, max_length=255)


class UpdateDeveloperAppSettingsRequest(BaseModel):
    assignment_mode: str = Field(default="round_robin", min_length=1, max_length=20)
    alert_tg_user_ids: str = Field(default="", max_length=1000)


class SetUserDeveloperAppRequest(BaseModel):
    developer_app_id: Optional[int] = Field(default=None, ge=1)


def _actor(current_admin: AdminAccount) -> str:
    return f"{current_admin.username}#{current_admin.id}"


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


@router.get("/api/admin/system/purchase-settings")
async def get_purchase_settings(
    current_admin: AdminAccount = Depends(require_admin_permissions("system.settings.read")),
):
    service = get_admin_license_service()
    return {"success": True, "data": await service.get_purchase_settings()}


@router.put("/api/admin/system/purchase-settings")
async def update_purchase_settings(
    payload: UpdatePurchaseSettingsRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("system.settings.update")),
):
    service = get_admin_license_service()
    data = await service.update_purchase_settings(
        purchase_url=payload.purchase_url,
        purchase_button_text=payload.purchase_button_text,
        purchase_buttons=[item.model_dump() for item in payload.purchase_buttons] if payload.purchase_buttons is not None else None,
        actor=_actor(current_admin),
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "购买入口已更新", "data": data}


@router.get("/api/admin/system/bot-notice")
async def get_bot_notice_settings(
    current_admin: AdminAccount = Depends(require_admin_permissions("system.settings.read")),
):
    service = get_admin_license_service()
    return {"success": True, "data": await service.get_bot_notice_settings()}


@router.get("/api/admin/system/stats/today")
async def get_today_system_stats(
    current_admin: AdminAccount = Depends(require_admin_permissions("system.stats.read")),
):
    service = get_admin_license_service()
    return {"success": True, "data": await service.get_today_system_stats()}


@router.put("/api/admin/system/bot-notice")
async def update_bot_notice_settings(
    payload: UpdateBotNoticeSettingsRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("system.settings.update")),
):
    service = get_admin_license_service()
    data = await service.update_bot_notice_settings(
        enabled=payload.enabled,
        entry_button_text=payload.entry_button_text,
        message_text=payload.message_text,
        target_url=payload.target_url,
        actor=_actor(current_admin),
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "Bot 公告栏已更新", "data": data}


@router.get("/api/admin/developer-apps")
async def list_developer_apps(
    search: Optional[str] = None,
    health_status: Optional[str] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("developer_apps.read")),
):
    service = get_admin_license_service()
    return {
        "success": True,
        "data": await service.list_developer_apps(
            search=search,
            health_status=health_status,
            is_active=is_active,
            limit=limit,
            offset=offset,
        ),
    }


@router.post("/api/admin/developer-apps")
async def create_developer_app(
    payload: CreateDeveloperAppRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("developer_apps.write")),
):
    service = get_admin_license_service()
    data = await service.create_developer_app(
        app_name=payload.app_name,
        api_id=payload.api_id,
        api_hash=payload.api_hash,
        is_active=payload.is_active,
        max_accounts=payload.max_accounts,
        selection_weight=payload.selection_weight,
        notes=payload.notes,
        actor=_actor(current_admin),
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "开发者应用已创建", "data": data}


@router.put("/api/admin/developer-apps/{app_id}")
async def update_developer_app(
    app_id: int,
    payload: UpdateDeveloperAppRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("developer_apps.write")),
):
    service = get_admin_license_service()
    data = await service.update_developer_app(
        app_id,
        app_name=payload.app_name,
        api_hash=payload.api_hash,
        is_active=payload.is_active,
        max_accounts=payload.max_accounts,
        selection_weight=payload.selection_weight,
        notes=payload.notes,
        actor=_actor(current_admin),
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "开发者应用已更新", "data": data}


@router.get("/api/admin/developer-apps/settings")
async def get_developer_app_settings(
    current_admin: AdminAccount = Depends(require_admin_permissions("developer_apps.read")),
):
    service = get_admin_license_service()
    data = await service.list_developer_apps()
    return {"success": True, "data": data.get("settings", {})}


@router.put("/api/admin/developer-apps/settings")
async def update_developer_app_settings(
    payload: UpdateDeveloperAppSettingsRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("developer_apps.write")),
):
    service = get_admin_license_service()
    data = await service.update_developer_app_settings(
        assignment_mode=payload.assignment_mode,
        alert_tg_user_ids=payload.alert_tg_user_ids,
        actor=_actor(current_admin),
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "开发者应用策略已更新", "data": data}


@router.post("/api/admin/developer-apps/{app_id}/set-default")
async def set_default_developer_app(
    app_id: int,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("developer_apps.check")),
):
    service = get_admin_license_service()
    await service.set_default_developer_app(
        app_id,
        actor=_actor(current_admin),
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "默认开发者应用已更新"}


@router.post("/api/admin/developer-apps/{app_id}/check")
async def check_developer_app(
    app_id: int,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("developer_apps.check")),
):
    service = get_admin_license_service()
    data = await service.check_developer_app_health(
        app_id,
        actor=_actor(current_admin),
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "开发者应用健康检查已完成", "data": data}


@router.get("/api/admin/system-proxies")
async def list_system_proxies(
    search: Optional[str] = None,
    is_healthy: Optional[bool] = Query(default=None),
    is_assigned: Optional[bool] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("system_proxies.read")),
):
    service = get_admin_license_service()
    return {
        "success": True,
        "data": await service.list_proxies(
            search=search,
            is_healthy=is_healthy,
            is_assigned=is_assigned,
            limit=limit,
            offset=offset,
        ),
    }


@router.post("/api/admin/system-proxies")
async def add_system_proxy(
    payload: AddProxyRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("system_proxies.write")),
):
    service = get_admin_license_service()
    data = await service.add_proxy(
        proxy_type=payload.proxy_type,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password,
        actor=_actor(current_admin),
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "代理已新增", "data": data}


@router.delete("/api/admin/system-proxies/{proxy_id}")
async def delete_system_proxy(
    proxy_id: int,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("system_proxies.write")),
):
    service = get_admin_license_service()
    await service.delete_proxy(proxy_id, actor=_actor(current_admin), ip_address=_client_ip(request))
    return {"success": True, "message": "代理已删除"}


@router.post("/api/admin/system-proxies/{proxy_id}/check")
async def check_system_proxy(
    proxy_id: int,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("system_proxies.check")),
):
    service = get_admin_license_service()
    data = await service.check_proxy_health(proxy_id, actor=_actor(current_admin), ip_address=_client_ip(request))
    return {"success": True, "message": "代理检查完成", "data": data}


@router.post("/api/admin/system-proxies/{proxy_id}/assign")
async def assign_system_proxy(
    proxy_id: int,
    payload: AssignProxyRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("system_proxies.assign", "users.read")),
):
    service = get_admin_license_service()
    await service.assign_proxy(
        proxy_id,
        payload.account_id,
        actor=_actor(current_admin),
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "代理已分配"}


@router.post("/api/admin/system-proxies/{proxy_id}/unassign")
async def unassign_system_proxy(
    proxy_id: int,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("system_proxies.assign")),
):
    service = get_admin_license_service()
    await service.unassign_proxy(proxy_id, actor=_actor(current_admin), ip_address=_client_ip(request))
    return {"success": True, "message": "代理已解绑"}


@router.get("/api/admin/license-plans")
async def list_license_plans(
    current_admin: AdminAccount = Depends(require_admin_permissions("legacy_cards.read")),
):
    service = get_admin_license_service()
    return {"success": True, "data": await service.list_all_plans()}


@router.post("/api/admin/license-plans")
async def create_license_plan(
    payload: UpdatePlanRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("legacy_cards.write")),
):
    if not payload.plan_code or not payload.display_name or payload.price_cents is None or payload.duration_days is None:
        raise HTTPException(status_code=400, detail="plan_code、display_name、price_cents、duration_days 为必填项")
    service = get_admin_license_service()
    data = await service.create_plan(
        plan_code=payload.plan_code,
        display_name=payload.display_name,
        billing_cycle=payload.billing_cycle or "custom",
        price_cents=payload.price_cents,
        duration_days=payload.duration_days,
        is_active=True if payload.is_active is None else payload.is_active,
        sort_order=payload.sort_order or 0,
        actor=_actor(current_admin),
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "卡密规格已创建", "data": data}


@router.put("/api/admin/license-plans/{plan_code}")
async def update_license_plan(
    plan_code: str,
    payload: UpdatePlanRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("legacy_cards.write")),
):
    service = get_admin_license_service()
    data = await service.update_plan(
        plan_code=plan_code,
        display_name=payload.display_name,
        billing_cycle=payload.billing_cycle,
        price_cents=payload.price_cents,
        duration_days=payload.duration_days,
        is_active=payload.is_active,
        sort_order=payload.sort_order,
        actor=_actor(current_admin),
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "卡密规格已更新", "data": data}


@router.delete("/api/admin/license-plans/{plan_code}")
async def delete_license_plan(
    plan_code: str,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("legacy_cards.write")),
):
    service = get_admin_license_service()
    data = await service.delete_plan(plan_code, actor=_actor(current_admin), ip_address=_client_ip(request))
    return {"success": True, "message": "卡密规格已删除", "data": data}


@router.post("/api/admin/license-cards/generate")
async def generate_license_cards(
    payload: GenerateCardRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("legacy_cards.write")),
):
    if str(getattr(current_admin, "account_type", "") or "").strip().lower() != "staff":
        raise HTTPException(status_code=403, detail="旧系统卡密只允许超管生成")
    owner_account_id = int(current_admin.id)
    root_master_account_id = int(current_admin.id)
    service = get_admin_license_service()
    actor = _actor(current_admin)
    ip_address = _client_ip(request)
    if payload.quantity == 1:
        data = await service.create_single_card(
            plan_code=payload.plan_code,
            valid_days=payload.valid_days,
            prefix=payload.prefix,
            creator_account_id=owner_account_id,
            owner_account_id=owner_account_id,
            root_master_account_id=root_master_account_id,
            direct_parent_account_id=None,
            card_source_type="legacy",
            actor=actor,
            ip_address=ip_address,
        )
        return {"success": True, "message": "卡密生成成功", "data": [data]}
    expires_at = None
    if payload.valid_days is not None:
        expires_at = datetime.now() + timedelta(days=payload.valid_days)
    data = await service.generate_cards(
        plan_code=payload.plan_code,
        quantity=payload.quantity,
        expires_at=expires_at,
        prefix=payload.prefix,
        creator_account_id=owner_account_id,
        owner_account_id=owner_account_id,
        root_master_account_id=root_master_account_id,
        direct_parent_account_id=None,
        card_source_type="legacy",
        actor=actor,
        ip_address=ip_address,
    )
    return {"success": True, "message": "卡密生成成功", "data": data}


@router.get("/api/admin/license-cards")
async def list_license_cards(
    plan_code: Optional[str] = None,
    is_used: Optional[bool] = None,
    is_active: Optional[bool] = None,
    keyword: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("legacy_cards.read")),
):
    service = get_admin_license_service()
    data = await service.list_cards(
        plan_code=plan_code,
        is_used=is_used,
        is_active=is_active,
        keyword=keyword,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": data}


@router.get("/api/admin/license-cards/export")
async def export_license_cards(
    plan_code: Optional[str] = None,
    is_used: Optional[bool] = None,
    is_active: Optional[bool] = None,
    current_admin: AdminAccount = Depends(require_admin_permissions("legacy_cards.export")),
):
    service = get_admin_license_service()
    file_bytes, _ = await service.export_cards_xlsx(
        plan_code=plan_code,
        is_used=is_used,
        is_active=is_active,
    )
    filename = f"cards_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        iter([file_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/admin/license-cards/{card_code}/enable")
async def enable_license_card(
    card_code: str,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("legacy_cards.write")),
):
    service = get_admin_license_service()
    data = await service.set_card_active(card_code, True, actor=_actor(current_admin), ip_address=_client_ip(request))
    return {"success": True, "message": "卡密已启用", "data": data}


@router.post("/api/admin/license-cards/{card_code}/disable")
async def disable_license_card(
    card_code: str,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("legacy_cards.write")),
):
    service = get_admin_license_service()
    data = await service.set_card_active(card_code, False, actor=_actor(current_admin), ip_address=_client_ip(request))
    return {"success": True, "message": "卡密已停用", "data": data}


@router.get("/api/admin/license-slots")
async def list_license_slots(
    status: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("legacy_cards.read")),
):
    service = get_admin_license_service()
    data = await service.list_authorizations(status=status, limit=limit, offset=offset)
    return {"success": True, "data": data}


@router.get("/api/admin/users")
async def list_users(
    search: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("users.read")),
):
    service = get_admin_license_service()
    return {"success": True, "data": await service.list_users(search=search, limit=limit, offset=offset)}


@router.get("/api/admin/users/{user_id}/accounts")
async def list_user_accounts(
    user_id: int,
    current_admin: AdminAccount = Depends(require_admin_permissions("users.read")),
):
    service = get_admin_license_service()
    return {"success": True, "data": await service.list_user_accounts(user_id)}


@router.get("/api/admin/users/{user_id}/accounts/{account_id}/send-logs")
async def list_user_account_send_logs(
    user_id: int,
    account_id: str,
    result: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("users.read")),
):
    service = get_admin_license_service()
    return {
        "success": True,
        "data": await service.list_account_send_logs(
            user_id,
            account_id,
            result=result,
            limit=limit,
            offset=offset,
        ),
    }


@router.post("/api/admin/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    payload: ResetUserPasswordRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("users.reset_password")),
):
    service = get_admin_license_service()
    await service.reset_user_password(user_id, payload.new_password, actor=_actor(current_admin), ip_address=_client_ip(request))
    return {"success": True, "message": "密码已重置"}


@router.put("/api/admin/users/{user_id}/developer-app")
async def set_user_developer_app(
    user_id: int,
    payload: SetUserDeveloperAppRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("users.write")),
):
    service = get_admin_license_service()
    data = await service.set_user_developer_app(
        user_id,
        payload.developer_app_id,
        actor=_actor(current_admin),
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "用户开发者应用已更新", "data": data}


@router.get("/api/admin/accounts/options")
async def list_account_options(
    search: Optional[str] = None,
    limit: int = Query(default=300, ge=1, le=1000),
    current_admin: AdminAccount = Depends(require_admin_permissions("users.read")),
):
    service = get_admin_license_service()
    return {"success": True, "data": await service.list_account_options(search=search, limit=limit)}


@router.delete("/api/admin/accounts/{account_id}")
async def delete_account(
    account_id: str,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("users.write")),
):
    service = get_admin_license_service()
    await service.admin_delete_account(account_id, actor=_actor(current_admin), ip_address=_client_ip(request))
    return {"success": True, "message": "账号已删除"}


@router.get("/api/admin/audit-logs")
async def list_audit_logs(
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    developer_app_id: Optional[int] = None,
    keyword: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("audit.system.read")),
):
    service = get_admin_license_service()
    data = await service.list_audit_logs(
        action=action,
        target_type=target_type,
        target_id=target_id,
        developer_app_id=developer_app_id,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": data}
