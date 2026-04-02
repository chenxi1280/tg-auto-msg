"""Admin license routes for card/key-spec and license-slot management."""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from backend.h5_backend.dependencies import require_admin_token
from backend.h5_backend.services.admin.service import get_admin_license_service

router = APIRouter(prefix="/api/admin", tags=["管理员授权"])


class UpdatePlanRequest(BaseModel):
    """Plan update payload."""

    plan_code: Optional[str] = Field(default=None, min_length=1, max_length=32)
    display_name: Optional[str] = Field(default=None, max_length=100)
    billing_cycle: Optional[str] = Field(default=None, min_length=1, max_length=20)
    price_cents: Optional[int] = Field(default=None, ge=1)
    duration_days: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class GenerateCardRequest(BaseModel):
    """Card generation payload."""

    plan_code: str = Field(..., min_length=1, max_length=32)
    quantity: int = Field(default=1, ge=1, le=500)
    valid_days: Optional[int] = Field(default=None, ge=1)
    prefix: str = Field(default="", max_length=20)


class ResetUserPasswordRequest(BaseModel):
    """Reset user password payload."""

    new_password: str = Field(..., min_length=6, max_length=128)


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
    selection_weight: int = Field(default=100, ge=1, le=100000)
    notes: Optional[str] = Field(default=None, max_length=255)


class UpdateDeveloperAppRequest(BaseModel):
    """Update Telegram developer app payload."""

    app_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    api_hash: Optional[str] = Field(default=None, min_length=8, max_length=255)
    is_active: Optional[bool] = None
    max_accounts: Optional[int] = Field(default=None, ge=0)
    selection_weight: Optional[int] = Field(default=None, ge=1, le=100000)
    notes: Optional[str] = Field(default=None, max_length=255)


class UpdateDeveloperAppSettingsRequest(BaseModel):
    """Developer-app assignment settings payload."""

    assignment_mode: str = Field(default="round_robin", min_length=1, max_length=20)
    alert_tg_user_ids: str = Field(default="", max_length=1000)


class SetUserDeveloperAppRequest(BaseModel):
    """Assign user preferred developer app payload."""

    developer_app_id: Optional[int] = Field(default=None, ge=1)


@router.get("/plans", dependencies=[Depends(require_admin_token)])
async def admin_list_plans():
    """管理员查看套餐配置。"""
    service = get_admin_license_service()
    data = await service.list_plans()
    return {"success": True, "data": data}


@router.post("/plans", dependencies=[Depends(require_admin_token)])
async def admin_create_plan(payload: UpdatePlanRequest, request: Request):
    """管理员新增 Key 规格。"""
    service = get_admin_license_service()
    if not payload.plan_code:
        raise HTTPException(status_code=400, detail="plan_code 不能为空")
    if not payload.display_name:
        raise HTTPException(status_code=400, detail="display_name 不能为空")
    if payload.price_cents is None:
        raise HTTPException(status_code=400, detail="price_cents 不能为空")
    if payload.duration_days is None:
        raise HTTPException(status_code=400, detail="duration_days 不能为空")
    data = await service.create_plan(
        plan_code=payload.plan_code,
        display_name=payload.display_name,
        billing_cycle=payload.billing_cycle or "custom",
        price_cents=payload.price_cents,
        duration_days=payload.duration_days,
        is_active=True if payload.is_active is None else payload.is_active,
        sort_order=payload.sort_order or 0,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "Key规格已创建", "data": data}


@router.get("/developer-apps", dependencies=[Depends(require_admin_token)])
async def admin_list_developer_apps():
    """管理员查询开发者应用池。"""
    service = get_admin_license_service()
    data = await service.list_developer_apps()
    return {"success": True, "data": data}


@router.post("/developer-apps", dependencies=[Depends(require_admin_token)])
async def admin_create_developer_app(payload: CreateDeveloperAppRequest, request: Request):
    """管理员新增开发者应用。"""
    service = get_admin_license_service()
    data = await service.create_developer_app(
        app_name=payload.app_name,
        api_id=payload.api_id,
        api_hash=payload.api_hash,
        is_active=payload.is_active,
        max_accounts=payload.max_accounts,
        selection_weight=payload.selection_weight,
        notes=payload.notes,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "开发者应用已创建", "data": data}


@router.put("/developer-apps/{app_id}", dependencies=[Depends(require_admin_token)])
async def admin_update_developer_app(app_id: int, payload: UpdateDeveloperAppRequest, request: Request):
    """管理员更新开发者应用。"""
    service = get_admin_license_service()
    data = await service.update_developer_app(
        app_id,
        app_name=payload.app_name,
        api_hash=payload.api_hash,
        is_active=payload.is_active,
        max_accounts=payload.max_accounts,
        selection_weight=payload.selection_weight,
        notes=payload.notes,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "开发者应用已更新", "data": data}


@router.get("/settings/developer-apps", dependencies=[Depends(require_admin_token)])
async def admin_get_developer_app_settings():
    """管理员获取开发者应用分配设置。"""
    service = get_admin_license_service()
    data = await service.list_developer_apps()
    return {"success": True, "data": data.get("settings", {})}


@router.put("/settings/developer-apps", dependencies=[Depends(require_admin_token)])
async def admin_update_developer_app_settings(payload: UpdateDeveloperAppSettingsRequest, request: Request):
    """管理员更新开发者应用分配设置。"""
    service = get_admin_license_service()
    data = await service.update_developer_app_settings(
        assignment_mode=payload.assignment_mode,
        alert_tg_user_ids=payload.alert_tg_user_ids,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "开发者应用分配设置已更新", "data": data}


@router.post("/developer-apps/{app_id}/set-default", dependencies=[Depends(require_admin_token)])
async def admin_set_default_developer_app(app_id: int, request: Request):
    """管理员设置默认开发者应用。"""
    service = get_admin_license_service()
    await service.set_default_developer_app(
        app_id,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "默认开发者应用已更新"}


@router.post("/developer-apps/{app_id}/check", dependencies=[Depends(require_admin_token)])
async def admin_check_developer_app_health(app_id: int, request: Request):
    """管理员手动检查开发者应用健康状态。"""
    service = get_admin_license_service()
    data = await service.check_developer_app_health(
        app_id,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "开发者应用健康检查已完成", "data": data}


@router.get("/settings/purchase", dependencies=[Depends(require_admin_token)])
async def admin_get_purchase_settings():
    """管理员获取购买入口配置。"""
    service = get_admin_license_service()
    data = await service.get_purchase_settings()
    return {"success": True, "data": data}


@router.put("/settings/purchase", dependencies=[Depends(require_admin_token)])
async def admin_update_purchase_settings(payload: UpdatePurchaseSettingsRequest, request: Request):
    """管理员更新购买入口配置。"""
    service = get_admin_license_service()
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
    service = get_admin_license_service()
    data = await service.update_plan(
        plan_code=plan_code,
        display_name=payload.display_name,
        billing_cycle=payload.billing_cycle,
        price_cents=payload.price_cents,
        duration_days=payload.duration_days,
        is_active=payload.is_active,
        sort_order=payload.sort_order,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "Key规格已更新", "data": data}


@router.delete("/plans/{plan_code}", dependencies=[Depends(require_admin_token)])
async def admin_delete_plan(plan_code: str, request: Request):
    """管理员删除 Key 规格，并停用该规格下所有未使用卡密。"""
    service = get_admin_license_service()
    data = await service.delete_plan(
        plan_code=plan_code,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "Key规格已删除", "data": data}


@router.post("/cards/generate", dependencies=[Depends(require_admin_token)])
async def admin_generate_cards(payload: GenerateCardRequest, request: Request):
    """管理员批量生成卡密。"""
    service = get_admin_license_service()
    actor = request.headers.get("X-Admin-Token", "")
    ip_address = request.client.host if request.client else None
    trace_id = f"cards-gen-{int(datetime.now().timestamp() * 1000)}"
    try:
        if payload.quantity == 1:
            data = await service.create_single_card(
                plan_code=payload.plan_code,
                valid_days=payload.valid_days,
                prefix=payload.prefix,
                actor=actor,
                ip_address=ip_address,
            )
            logger.info(
                "管理员生成卡密成功: trace_id={}, plan_code={}, quantity=1, admin={}",
                trace_id,
                payload.plan_code,
                "***" if not actor else f"{actor[:4]}***",
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
            actor=actor,
            ip_address=ip_address,
        )
        logger.info(
            "管理员生成卡密成功: trace_id={}, plan_code={}, quantity={}, admin={}",
            trace_id,
            payload.plan_code,
            payload.quantity,
            "***" if not actor else f"{actor[:4]}***",
        )
        return {"success": True, "message": "卡密生成成功", "data": data}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "管理员生成卡密异常: trace_id={}, plan_code={}, quantity={}, valid_days={}, prefix={}, error={}",
            trace_id,
            payload.plan_code,
            payload.quantity,
            payload.valid_days,
            payload.prefix,
            exc,
        )
        raise HTTPException(status_code=500, detail=f"卡密生成失败，请稍后重试（trace_id={trace_id}）") from exc


@router.get("/cards", dependencies=[Depends(require_admin_token)])
async def admin_list_cards(
    plan_code: Optional[str] = None,
    is_used: Optional[bool] = None,
    is_active: Optional[bool] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    limit: int = 50,
    offset: int = 0,
):
    """管理员查询卡密。"""
    service = get_admin_license_service()
    data = await service.list_cards(
        plan_code=plan_code,
        is_used=is_used,
        is_active=is_active,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    return {"success": True, "data": data}


@router.get("/license-slots", dependencies=[Depends(require_admin_token)])
async def admin_list_license_slots(
    status: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    """管理员查询套餐位列表。"""
    service = get_admin_license_service()
    data = await service.list_license_slots(status=status, limit=limit, offset=offset)
    return {"success": True, "data": data}


@router.get("/cards/export", dependencies=[Depends(require_admin_token)])
async def admin_export_cards(
    plan_code: Optional[str] = None,
    is_used: Optional[bool] = None,
    is_active: Optional[bool] = None,
):
    """管理员按筛选条件导出卡密（XLSX）。"""
    service = get_admin_license_service()
    trace_id = f"cards-export-{int(datetime.now().timestamp() * 1000)}"
    try:
        file_bytes, total = await service.export_cards_xlsx(
            plan_code=plan_code,
            is_used=is_used,
            is_active=is_active,
        )
        filename = f"cards_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        logger.info(
            "管理员导出卡密成功: trace_id={}, plan_code={}, is_used={}, is_active={}, total={}",
            trace_id,
            plan_code,
            is_used,
            is_active,
            total,
        )
        return StreamingResponse(
            iter([file_bytes]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "管理员导出卡密异常: trace_id={}, plan_code={}, is_used={}, is_active={}, error={}",
            trace_id,
            plan_code,
            is_used,
            is_active,
            exc,
        )
        raise HTTPException(status_code=500, detail=f"导出失败，请稍后重试（trace_id={trace_id}）") from exc


@router.post("/cards/{card_code}/disable", dependencies=[Depends(require_admin_token)])
async def admin_disable_card(card_code: str, request: Request):
    """管理员停用卡密。"""
    service = get_admin_license_service()
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
    service = get_admin_license_service()
    data = await service.set_card_active(
        card_code,
        is_active=True,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "卡密已启用", "data": data}


@router.get("/users", dependencies=[Depends(require_admin_token)])
async def admin_list_users(search: Optional[str] = None, limit: int = 100, offset: int = 0):
    """管理员查询用户与授权摘要。"""
    service = get_admin_license_service()
    data = await service.list_users(search=search, limit=limit, offset=offset)
    return {"success": True, "data": data}


@router.get("/users/{user_id}/accounts", dependencies=[Depends(require_admin_token)])
async def admin_list_user_accounts(user_id: int):
    """管理员查看用户下所有 TG 账号。"""
    service = get_admin_license_service()
    data = await service.list_user_accounts(user_id)
    return {"success": True, "data": data}


@router.get("/accounts/options", dependencies=[Depends(require_admin_token)])
async def admin_list_account_options(search: Optional[str] = None, limit: int = 300):
    """管理员获取账号下拉选项（代理分配用）。"""
    service = get_admin_license_service()
    data = await service.list_account_options(search=search, limit=limit)
    return {"success": True, "data": data}


@router.delete("/accounts/{account_id}", dependencies=[Depends(require_admin_token)])
async def admin_delete_account(account_id: str, request: Request):
    """管理员删除 TG 账号。"""
    service = get_admin_license_service()
    await service.admin_delete_account(
        account_id,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "账号已删除"}


@router.post("/users/{user_id}/reset-password", dependencies=[Depends(require_admin_token)])
async def admin_reset_user_password(user_id: int, payload: ResetUserPasswordRequest, request: Request):
    """管理员重置系统用户密码。"""
    service = get_admin_license_service()
    await service.reset_user_password(
        user_id,
        payload.new_password,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "密码已重置"}


@router.put("/users/{user_id}/developer-app", dependencies=[Depends(require_admin_token)])
async def admin_set_user_developer_app(user_id: int, payload: SetUserDeveloperAppRequest, request: Request):
    """管理员设置用户首选开发者应用。"""
    service = get_admin_license_service()
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
    service = get_admin_license_service()
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
    service = get_admin_license_service()
    data = await service.list_proxies()
    return {"success": True, "data": data}


@router.post("/proxies", dependencies=[Depends(require_admin_token)])
async def admin_add_proxy(payload: AddProxyRequest, request: Request):
    """管理员添加代理。"""
    service = get_admin_license_service()
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
    service = get_admin_license_service()
    data = await service.check_proxy_health(
        proxy_id,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "data": data}


@router.delete("/proxies/{proxy_id}", dependencies=[Depends(require_admin_token)])
async def admin_delete_proxy(proxy_id: int, request: Request):
    """管理员删除代理。"""
    service = get_admin_license_service()
    await service.delete_proxy(
        proxy_id,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "代理已删除"}


@router.post("/proxies/{proxy_id}/assign", dependencies=[Depends(require_admin_token)])
async def admin_assign_proxy(proxy_id: int, payload: AssignProxyRequest, request: Request):
    """管理员分配代理到账号。"""
    service = get_admin_license_service()
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
    service = get_admin_license_service()
    await service.unassign_proxy(
        proxy_id,
        actor=request.headers.get("X-Admin-Token", ""),
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": "代理已解绑"}
