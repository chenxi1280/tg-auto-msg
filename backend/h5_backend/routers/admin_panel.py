"""RBAC admin panel and agent management API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.database.schema.models import AdminAccount
from backend.h5_backend.dependencies import (
    get_current_admin_account,
    require_admin_permissions,
)
from backend.h5_backend.services.admin_panel.service import (
    get_admin_panel_service,
)

router = APIRouter(tags=["后台代理运营"])


class CreateMasterAgentRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)
    credit_limit_cents: int = Field(default=0, ge=0)
    is_credit_whitelisted: bool = False
    contact_name: Optional[str] = Field(default=None, max_length=100)
    contact_phone: Optional[str] = Field(default=None, max_length=50)


class UpdateCreditLimitRequest(BaseModel):
    credit_limit_cents: int = Field(..., ge=0)
    is_credit_whitelisted: Optional[bool] = None


class UpdateWhitelistRequest(BaseModel):
    is_credit_whitelisted: bool


class CreateAgentAccountRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)
    settlement_mode: str = Field(default="prepaid", min_length=1, max_length=20)
    credit_limit_cents: int = Field(default=0, ge=0)
    contact_name: Optional[str] = Field(default=None, max_length=100)
    contact_phone: Optional[str] = Field(default=None, max_length=50)


class UpdateSettlementModeRequest(BaseModel):
    settlement_mode: str = Field(..., min_length=1, max_length=20)


class UpdatePricingPlanRequest(BaseModel):
    price_cents: int = Field(..., ge=1)


class GenerateCardBatchRequest(BaseModel):
    plan_code: str = Field(..., min_length=1, max_length=32)
    quantity: int = Field(..., ge=1, le=500)
    prefix: str = Field(default="", max_length=20)
    valid_days: Optional[int] = Field(default=None, ge=1)
    funding_source: str = Field(..., min_length=1, max_length=20)


class CopyCardsRequest(BaseModel):
    card_ids: List[int] = Field(..., min_length=1, max_length=10)
    with_meta: bool = False


class CreateApprovalRequest(BaseModel):
    request_type: str = Field(..., min_length=1, max_length=32)
    amount_cents: Optional[int] = Field(default=None, ge=0)
    credit_delta_cents: Optional[int] = None
    subject_account_id: Optional[int] = Field(default=None, ge=1)
    payload_json: Optional[Dict[str, Any]] = None


class BatchApprovalRequest(BaseModel):
    request_ids: List[str] = Field(..., min_length=1, max_length=50)


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


@router.post("/api/admin/provinces/{province_code}/master-agent")
async def create_master_agent(
    province_code: str,
    payload: CreateMasterAgentRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("agents.master.create")),
):
    if province_code != current_admin.province_code:
        raise HTTPException(status_code=403, detail="当前超管只能管理本省总代")
    service = get_admin_panel_service()
    data = await service.create_master_agent(
        current_admin=current_admin,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        credit_limit_cents=payload.credit_limit_cents,
        is_credit_whitelisted=payload.is_credit_whitelisted,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "总代账号已创建", "data": data}


@router.put("/api/admin/accounts/{account_id}/credit-limit")
async def set_master_credit_limit(
    account_id: int,
    payload: UpdateCreditLimitRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("agents.credit.master.write")),
):
    service = get_admin_panel_service()
    data = await service.set_master_credit_limit(
        current_admin=current_admin,
        account_id=account_id,
        credit_limit_cents=payload.credit_limit_cents,
        is_credit_whitelisted=payload.is_credit_whitelisted,
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "总代总额度已更新", "data": data}


@router.put("/api/admin/accounts/{account_id}/credit-whitelist")
async def set_credit_whitelist(
    account_id: int,
    payload: UpdateWhitelistRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("agents.credit.master.write")),
):
    service = get_admin_panel_service()
    data = await service.set_credit_whitelist(
        current_admin=current_admin,
        account_id=account_id,
        is_credit_whitelisted=payload.is_credit_whitelisted,
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "授信白名单已更新", "data": data}


@router.get("/api/agent/accounts")
async def list_accounts(
    search: Optional[str] = Query(default=None),
    role_code: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    parent_account_id: Optional[int] = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("agents.read")),
):
    service = get_admin_panel_service()
    return {
        "success": True,
        "data": await service.list_accounts(
            current_admin=current_admin,
            search=search,
            role_code=role_code,
            status=status,
            parent_account_id=parent_account_id,
            limit=limit,
            offset=offset,
        ),
    }


@router.post("/api/agent/accounts")
async def create_child_agent(
    payload: CreateAgentAccountRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("agents.child.create")),
):
    service = get_admin_panel_service()
    data = await service.create_child_agent(
        current_admin=current_admin,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        settlement_mode=payload.settlement_mode,
        credit_limit_cents=payload.credit_limit_cents,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "下级代理已创建", "data": data}


@router.put("/api/agent/accounts/{account_id}/settlement-mode")
async def set_settlement_mode(
    account_id: int,
    payload: UpdateSettlementModeRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("agents.write")),
):
    service = get_admin_panel_service()
    data = await service.set_settlement_mode(
        current_admin=current_admin,
        account_id=account_id,
        settlement_mode=payload.settlement_mode,
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "结算模式已更新", "data": data}


@router.put("/api/agent/accounts/{account_id}/credit-limit")
async def set_child_credit_limit(
    account_id: int,
    payload: UpdateCreditLimitRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("agents.write")),
):
    service = get_admin_panel_service()
    data = await service.set_child_credit_limit(
        current_admin=current_admin,
        account_id=account_id,
        credit_limit_cents=payload.credit_limit_cents,
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "下级受限额度已更新", "data": data}


@router.get("/api/admin/pricing/plans")
async def list_pricing_plans(
    search: Optional[str] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("pricing.read")),
):
    service = get_admin_panel_service()
    return {
        "success": True,
        "data": await service.list_pricing_plans(
            current_admin=current_admin,
            search=search,
            is_active=is_active,
            limit=limit,
            offset=offset,
        ),
    }


@router.put("/api/admin/pricing/plans/{plan_code}")
async def update_pricing_plan(
    plan_code: str,
    payload: UpdatePricingPlanRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("pricing.write")),
):
    service = get_admin_panel_service()
    data = await service.update_pricing_plan(
        current_admin=current_admin,
        plan_code=plan_code,
        price_cents=payload.price_cents,
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "统一价格已更新", "data": data}


@router.get("/api/agent/plans")
async def list_plans(
    search: Optional[str] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("pricing.read")),
):
    service = get_admin_panel_service()
    return {
        "success": True,
        "data": await service.list_pricing_plans(
            current_admin=current_admin,
            search=search,
            is_active=is_active,
            limit=limit,
            offset=offset,
        ),
    }


@router.post("/api/agent/card-batches/generate")
async def generate_card_batch(
    payload: GenerateCardBatchRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("batches.generate")),
):
    service = get_admin_panel_service()
    data = await service.generate_card_batch(
        current_admin=current_admin,
        plan_code=payload.plan_code,
        quantity=payload.quantity,
        prefix=payload.prefix,
        valid_days=payload.valid_days,
        funding_source=payload.funding_source,
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "卡密批次生成成功", "data": data}


@router.get("/api/agent/card-batches")
async def list_card_batches(
    plan_code: Optional[str] = Query(default=None),
    payment_status: Optional[str] = Query(default=None),
    settlement_status: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("batches.read")),
):
    service = get_admin_panel_service()
    return {
        "success": True,
        "data": await service.list_card_batches(
            current_admin=current_admin,
            plan_code=plan_code,
            payment_status=payment_status,
            settlement_status=settlement_status,
            keyword=keyword,
            limit=limit,
            offset=offset,
        ),
    }


@router.get("/api/agent/fund-ledgers")
async def list_self_fund_ledgers(
    biz_type: Optional[str] = Query(default=None),
    direction: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("ledgers.read")),
):
    service = get_admin_panel_service()
    return {
        "success": True,
        "data": await service.list_self_fund_ledgers(
            current_admin=current_admin,
            biz_type=biz_type,
            direction=direction,
            keyword=keyword,
            limit=limit,
            offset=offset,
        ),
    }


@router.get("/api/admin/fund-ledgers")
async def list_visible_fund_ledgers(
    biz_type: Optional[str] = Query(default=None),
    direction: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    account_id: Optional[int] = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("ledgers.scope.read")),
):
    service = get_admin_panel_service()
    return {
        "success": True,
        "data": await service.list_visible_fund_ledgers(
            current_admin=current_admin,
            biz_type=biz_type,
            direction=direction,
            keyword=keyword,
            limit=limit,
            account_id=account_id,
            offset=offset,
        ),
    }


@router.get("/api/agent/cards")
async def list_cards(
    plan_code: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    source_type: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("batches.read")),
):
    service = get_admin_panel_service()
    return {
        "success": True,
        "data": await service.list_cards(
            current_admin=current_admin,
            plan_code=plan_code,
            status=status,
            source_type=source_type,
            keyword=keyword,
            limit=limit,
            offset=offset,
        ),
    }


@router.get("/api/agent/cards/export")
async def export_cards(
    plan_code: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    source_type: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    current_admin: AdminAccount = Depends(require_admin_permissions("batches.export")),
):
    service = get_admin_panel_service()
    file_bytes, total = await service.export_cards_xlsx(
        current_admin=current_admin,
        plan_code=plan_code,
        status=status,
        source_type=source_type,
        keyword=keyword,
    )
    headers = {
        "Content-Disposition": f'attachment; filename="agent-cards-{total}.xlsx"',
    }
    return StreamingResponse(
        iter([file_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.post("/api/agent/cards/copy")
async def copy_cards(
    payload: CopyCardsRequest,
    current_admin: AdminAccount = Depends(require_admin_permissions("batches.copy")),
):
    service = get_admin_panel_service()
    return {"success": True, "data": await service.copy_cards(current_admin=current_admin, card_ids=payload.card_ids, with_meta=payload.with_meta)}


@router.post("/api/agent/approval-requests/recharge")
async def create_recharge_request(
    payload: CreateApprovalRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("agents.write")),
):
    service = get_admin_panel_service()
    data = await service.create_approval_request(
        current_admin=current_admin,
        request_type="recharge",
        amount_cents=payload.amount_cents,
        subject_account_id=payload.subject_account_id,
        payload_json=payload.payload_json,
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "充值审批已发起", "data": data}


@router.post("/api/agent/approval-requests/settlement")
async def create_settlement_request(
    payload: CreateApprovalRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("agents.write")),
):
    service = get_admin_panel_service()
    data = await service.create_approval_request(
        current_admin=current_admin,
        request_type="settlement",
        amount_cents=payload.amount_cents,
        subject_account_id=payload.subject_account_id,
        payload_json=payload.payload_json,
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "结算审批已发起", "data": data}


@router.post("/api/agent/approval-requests/credit-adjust")
async def create_credit_adjust_request(
    payload: CreateApprovalRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("agents.write")),
):
    service = get_admin_panel_service()
    data = await service.create_approval_request(
        current_admin=current_admin,
        request_type="credit_adjust",
        credit_delta_cents=payload.credit_delta_cents,
        subject_account_id=payload.subject_account_id,
        payload_json=payload.payload_json,
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "调额审批已发起", "data": data}


@router.post("/api/agent/approval-requests/batch-purchase")
async def create_batch_purchase_request(
    payload: CreateApprovalRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("batches.generate")),
):
    service = get_admin_panel_service()
    data = await service.create_approval_request(
        current_admin=current_admin,
        request_type="batch_purchase",
        amount_cents=payload.amount_cents,
        subject_account_id=payload.subject_account_id,
        payload_json=payload.payload_json,
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "批次申请已发起", "data": data}


@router.get("/api/agent/approval-requests/pending")
async def list_pending_approvals(current_admin: AdminAccount = Depends(require_admin_permissions("approvals.read"))):
    service = get_admin_panel_service()
    return {"success": True, "data": await service.list_pending_approvals(current_admin=current_admin)}


@router.get("/api/agent/approval-requests")
async def list_approval_requests(
    status: Optional[str] = Query(default="all"),
    request_type: Optional[str] = Query(default="all"),
    keyword: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("approvals.read")),
):
    service = get_admin_panel_service()
    return {
        "success": True,
        "data": await service.list_approval_requests(
            current_admin=current_admin,
            status=status,
            request_type=request_type,
            keyword=keyword,
            limit=limit,
            offset=offset,
        ),
    }


@router.post("/api/agent/approval-requests/{request_id}/approve")
async def approve_request(
    request_id: str,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("approvals.approve")),
):
    service = get_admin_panel_service()
    data = await service.approve_request(current_admin=current_admin, request_id=request_id, ip_address=_client_ip(request))
    return {"success": True, "message": "审批已通过", "data": data}


@router.post("/api/agent/approval-requests/{request_id}/reject")
async def reject_request(
    request_id: str,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("approvals.reject")),
):
    service = get_admin_panel_service()
    data = await service.reject_request(current_admin=current_admin, request_id=request_id, ip_address=_client_ip(request))
    return {"success": True, "message": "审批已驳回", "data": data}


@router.post("/api/agent/approval-requests/batch-approve")
async def batch_approve_requests(
    payload: BatchApprovalRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("approvals.batch")),
):
    service = get_admin_panel_service()
    data = await service.batch_process_requests(
        current_admin=current_admin,
        request_ids=payload.request_ids,
        decision="approve",
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "批量审批已执行", "data": data}


@router.post("/api/agent/approval-requests/batch-reject")
async def batch_reject_requests(
    payload: BatchApprovalRequest,
    request: Request,
    current_admin: AdminAccount = Depends(require_admin_permissions("approvals.batch")),
):
    service = get_admin_panel_service()
    data = await service.batch_process_requests(
        current_admin=current_admin,
        request_ids=payload.request_ids,
        decision="reject",
        ip_address=_client_ip(request),
    )
    return {"success": True, "message": "批量驳回已执行", "data": data}


@router.post("/api/internal/tg-admin/approve-callback")
async def tg_approve_callback(
    request_id: str,
    tg_user_id: int,
):
    service = get_admin_panel_service()
    return {"success": True, "data": await service.handle_tg_approval_callback(tg_user_id=tg_user_id, request_id=request_id, decision="approve")}


@router.post("/api/internal/tg-admin/reject-callback")
async def tg_reject_callback(
    request_id: str,
    tg_user_id: int,
):
    service = get_admin_panel_service()
    return {"success": True, "data": await service.handle_tg_approval_callback(tg_user_id=tg_user_id, request_id=request_id, decision="reject")}


@router.get("/api/agent/audit-logs")
async def list_audit_logs(
    action: Optional[str] = Query(default=None),
    target_type: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_admin: AdminAccount = Depends(require_admin_permissions("audit.read")),
):
    service = get_admin_panel_service()
    return {
        "success": True,
        "data": await service.list_audit_logs(
            current_admin=current_admin,
            action=action,
            target_type=target_type,
            keyword=keyword,
            limit=limit,
            offset=offset,
        ),
    }
