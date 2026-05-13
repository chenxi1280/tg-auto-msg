"""Agent hierarchy operations extracted from AdminPanelService."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    AdminAccount,
    AdminAccountRole,
    AdminRole,
    AdminRolePermission,
    AgentCreditLimit,
)
from backend.h5_backend.services.admin_panel.shared_helpers import (
    ACCOUNT_TYPE_AGENT,
    BUSINESS_IDENTITY_MASTER_AGENT,
    BUSINESS_IDENTITY_SUB_AGENT,
    ROLE_MASTER_AGENT,
    ROLE_SUB_AGENT,
    _business_identity,
    append_audit,
    ensure_visible_account,
    has_permission,
    is_agent,
    is_master_agent,
    is_staff,
    serialize_admin_account,
    visible_account_ids,
)
from backend.h5_backend.services.shared.pagination import normalize_page
from backend.h5_backend.services.shared.search import LIKE_ESCAPE_CHAR, contains_like_pattern


class AgentHierarchyService:
    """Agent profile, creation, credit-limit and settlement operations."""

    # ──────────────────────────── Profile ────────────────────────────

    async def get_profile(self, current_admin: AdminAccount) -> Dict[str, Any]:
        async with get_async_session() as session:
            account = (
                await session.execute(
                    select(AdminAccount)
                    .options(selectinload(AdminAccount.tg_binding))
                    .options(
                        selectinload(AdminAccount.role_bindings)
                        .selectinload(AdminAccountRole.role)
                        .selectinload(AdminRole.permission_bindings)
                        .selectinload(AdminRolePermission.permission)
                    )
                    .where(AdminAccount.id == int(current_admin.id))
                    .limit(1)
                )
            ).scalar_one()
            visible_count = len(await visible_account_ids(session, account))
        from backend.h5_backend.services.admin_rbac.service import get_admin_rbac_service
        rbac_service = get_admin_rbac_service()
        return {
            "account": serialize_admin_account(account),
            "visible_account_count": visible_count,
            "province_code": account.province_code,
            "roles": rbac_service.get_role_keys_for_account(account),
            "permissions": rbac_service.get_permission_codes_for_account(account),
        }

    # ──────────────────────────── Master agent ────────────────────────────

    async def create_master_agent(
        self,
        *,
        current_admin: AdminAccount,
        username: str,
        password: str,
        display_name: str,
        credit_limit_cents: int = 0,
        is_credit_whitelisted: bool = False,
        contact_name: Optional[str] = None,
        contact_phone: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not has_permission(current_admin, "agents.master.create"):
            raise HTTPException(status_code=403, detail="只有超管可以创建总代")
        if len(password or "") < 6:
            raise HTTPException(status_code=400, detail="密码至少 6 位")
        async with get_async_session() as session:
            existing_master = (
                await session.execute(
                    select(AdminAccount)
                    .where(
                        AdminAccount.account_type == ACCOUNT_TYPE_AGENT,
                        AdminAccount.business_identity == BUSINESS_IDENTITY_MASTER_AGENT,
                        AdminAccount.province_code == current_admin.province_code,
                        AdminAccount.status == "active",
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing_master is not None:
                raise HTTPException(status_code=409, detail="当前省份已存在总代账号")
            exists = (
                await session.execute(
                    select(AdminAccount.id).where(AdminAccount.username == (username or "").strip()).limit(1)
                )
            ).scalar_one_or_none()
            if exists is not None:
                raise HTTPException(status_code=409, detail="后台用户名已存在")

            from backend.h5_backend.services.admin_auth.service import get_admin_auth_service
            auth = get_admin_auth_service()
            account = AdminAccount(
                username=(username or "").strip(),
                password_hash=auth.get_password_hash(password),
                role_code=ROLE_MASTER_AGENT,
                account_type=ACCOUNT_TYPE_AGENT,
                business_identity=BUSINESS_IDENTITY_MASTER_AGENT,
                province_code=current_admin.province_code,
                parent_account_id=None,
                root_master_account_id=None,
                level_depth=0,
                status="active",
                settlement_mode="prepaid",
                is_credit_whitelisted=bool(is_credit_whitelisted),
                credit_limit_cents=int(credit_limit_cents or 0),
                display_name=(display_name or "").strip() or (username or "").strip(),
                contact_name=(contact_name or "").strip() or None,
                contact_phone=(contact_phone or "").strip() or None,
                force_password_change=True,
                created_by=int(current_admin.id),
            )
            session.add(account)
            await session.flush()
            account.root_master_account_id = int(account.id)
            master_role = (
                await session.execute(select(AdminRole).where(AdminRole.role_key == ROLE_MASTER_AGENT).limit(1))
            ).scalar_one_or_none()
            if master_role is not None:
                session.add(AdminAccountRole(admin_account_id=int(account.id), role_id=int(master_role.id)))
            await append_audit(
                session,
                actor=current_admin,
                action="admin.create_master_agent",
                target_type="admin_account",
                target_id=str(account.id),
                detail={"role_code": ROLE_MASTER_AGENT, "username": account.username},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(account)
            return serialize_admin_account(account)

    # ──────────────────────────── Credit limits ────────────────────────────

    async def set_master_credit_limit(
        self,
        *,
        current_admin: AdminAccount,
        account_id: int,
        credit_limit_cents: int,
        is_credit_whitelisted: Optional[bool] = None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not has_permission(current_admin, "agents.credit.master.write"):
            raise HTTPException(status_code=403, detail="只有超管可以配置总代总额度")
        async with get_async_session() as session:
            target = await ensure_visible_account(session, current_admin, int(account_id))
            if not is_master_agent(target):
                raise HTTPException(status_code=400, detail="只能为总代设置总额度")
            if int(target.allocated_credit_limit_cents or 0) > int(credit_limit_cents or 0):
                raise HTTPException(status_code=400, detail="总代已分配给下级的额度超过目标总额度")
            target.credit_limit_cents = int(credit_limit_cents or 0)
            if is_credit_whitelisted is not None:
                target.is_credit_whitelisted = bool(is_credit_whitelisted)
            await append_audit(
                session,
                actor=current_admin,
                action="admin.set_master_credit_limit",
                target_type="admin_account",
                target_id=str(target.id),
                detail={"credit_limit_cents": int(credit_limit_cents or 0), "is_credit_whitelisted": is_credit_whitelisted},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(target)
            return serialize_admin_account(target)

    async def set_credit_whitelist(
        self,
        *,
        current_admin: AdminAccount,
        account_id: int,
        is_credit_whitelisted: bool,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not has_permission(current_admin, "agents.credit.master.write"):
            raise HTTPException(status_code=403, detail="只有超管可以设置授信白名单")
        async with get_async_session() as session:
            target = await ensure_visible_account(session, current_admin, int(account_id))
            target.is_credit_whitelisted = bool(is_credit_whitelisted)
            await append_audit(
                session,
                actor=current_admin,
                action="admin.set_credit_whitelist",
                target_type="admin_account",
                target_id=str(target.id),
                detail={"is_credit_whitelisted": bool(is_credit_whitelisted)},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(target)
            return serialize_admin_account(target)

    # ──────────────────────────── Account listing ────────────────────────────

    async def list_accounts(
        self,
        *,
        current_admin: AdminAccount,
        search: Optional[str] = None,
        role_code: Optional[str] = None,
        business_identity: Optional[str] = None,
        status: Optional[str] = None,
        parent_account_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit, offset = normalize_page(limit, offset)
        async with get_async_session() as session:
            visible_ids = await visible_account_ids(session, current_admin)
            stmt = (
                select(AdminAccount)
                .options(selectinload(AdminAccount.tg_binding))
                .options(selectinload(AdminAccount.role_bindings).selectinload(AdminAccountRole.role))
                .where(AdminAccount.id.in_(visible_ids))
                .where(AdminAccount.account_type == ACCOUNT_TYPE_AGENT)
            )
            count_stmt = (
                select(func.count(AdminAccount.id))
                .where(AdminAccount.id.in_(visible_ids))
                .where(AdminAccount.account_type == ACCOUNT_TYPE_AGENT)
            )
            normalized_search = (search or "").strip()
            if normalized_search:
                search_value = contains_like_pattern(normalized_search)
                search_condition = (
                    AdminAccount.username.ilike(search_value, escape=LIKE_ESCAPE_CHAR)
                    | AdminAccount.display_name.ilike(search_value, escape=LIKE_ESCAPE_CHAR)
                    | AdminAccount.contact_name.ilike(search_value, escape=LIKE_ESCAPE_CHAR)
                    | AdminAccount.contact_phone.ilike(search_value, escape=LIKE_ESCAPE_CHAR)
                )
                stmt = stmt.where(search_condition)
                count_stmt = count_stmt.where(search_condition)
            normalized_role = (role_code or "").strip().lower()
            if normalized_role and normalized_role != "all":
                stmt = stmt.where(AdminAccount.business_identity == normalized_role)
                count_stmt = count_stmt.where(AdminAccount.business_identity == normalized_role)
            normalized_business_identity = (business_identity or "").strip().lower()
            if normalized_business_identity and normalized_business_identity != "all":
                stmt = stmt.where(AdminAccount.business_identity == normalized_business_identity)
                count_stmt = count_stmt.where(AdminAccount.business_identity == normalized_business_identity)
            normalized_status = (status or "").strip().lower()
            if normalized_status and normalized_status != "all":
                stmt = stmt.where(AdminAccount.status == normalized_status)
                count_stmt = count_stmt.where(AdminAccount.status == normalized_status)
            if parent_account_id is not None:
                stmt = stmt.where(AdminAccount.parent_account_id == int(parent_account_id))
                count_stmt = count_stmt.where(AdminAccount.parent_account_id == int(parent_account_id))
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (
                await session.execute(
                    stmt.order_by(AdminAccount.level_depth.asc(), AdminAccount.id.asc()).limit(limit).offset(offset)
                )
            ).scalars().all()
            return {
                "items": [serialize_admin_account(row) for row in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    # ──────────────────────────── Child agent ────────────────────────────

    async def create_child_agent(
        self,
        *,
        current_admin: AdminAccount,
        username: str,
        password: str,
        display_name: str,
        settlement_mode: str = "prepaid",
        credit_limit_cents: int = 0,
        contact_name: Optional[str] = None,
        contact_phone: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not is_agent(current_admin) or _business_identity(current_admin) not in {
            BUSINESS_IDENTITY_MASTER_AGENT,
            BUSINESS_IDENTITY_SUB_AGENT,
        }:
            raise HTTPException(status_code=403, detail="当前角色不能创建下级代理")
        async with get_async_session() as session:
            parent = await session.get(AdminAccount, int(current_admin.id))
            exists = (
                await session.execute(select(AdminAccount.id).where(AdminAccount.username == (username or "").strip()).limit(1))
            ).scalar_one_or_none()
            if exists is not None:
                raise HTTPException(status_code=409, detail="后台用户名已存在")
            from backend.h5_backend.services.admin_auth.service import get_admin_auth_service
            auth = get_admin_auth_service()
            child = AdminAccount(
                username=(username or "").strip(),
                password_hash=auth.get_password_hash(password),
                role_code=ROLE_SUB_AGENT,
                account_type=ACCOUNT_TYPE_AGENT,
                business_identity=BUSINESS_IDENTITY_SUB_AGENT,
                province_code=parent.province_code,
                parent_account_id=int(parent.id),
                root_master_account_id=int(parent.root_master_account_id or parent.id),
                level_depth=int(parent.level_depth or 0) + 1,
                status="active",
                settlement_mode=(settlement_mode or "prepaid").strip() or "prepaid",
                is_credit_whitelisted=False,
                credit_limit_cents=int(credit_limit_cents or 0),
                display_name=(display_name or "").strip() or (username or "").strip(),
                contact_name=(contact_name or "").strip() or None,
                contact_phone=(contact_phone or "").strip() or None,
                force_password_change=True,
                created_by=int(parent.id),
            )
            session.add(child)
            await session.flush()
            sub_role = (
                await session.execute(select(AdminRole).where(AdminRole.role_key == ROLE_SUB_AGENT).limit(1))
            ).scalar_one_or_none()
            if sub_role is not None:
                session.add(AdminAccountRole(admin_account_id=int(child.id), role_id=int(sub_role.id)))

            credit_row = AgentCreditLimit(
                parent_account_id=int(parent.id),
                child_account_id=int(child.id),
                delegated_credit_limit_cents=int(credit_limit_cents or 0),
                delegated_credit_used_cents=0,
                is_active=True,
                last_adjusted_by=int(parent.id),
            )
            new_allocated = int(parent.allocated_credit_limit_cents or 0) + int(credit_limit_cents or 0)
            if new_allocated > int(parent.credit_limit_cents or 0):
                raise HTTPException(status_code=400, detail="分配给下级的额度超过上级可分配额度")
            parent.allocated_credit_limit_cents = new_allocated
            session.add(credit_row)

            await append_audit(
                session,
                actor=current_admin,
                action="agent.create_child_account",
                target_type="admin_account",
                target_id=str(child.id),
                detail={"parent_account_id": int(parent.id), "credit_limit_cents": int(credit_limit_cents or 0)},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(child)
            return serialize_admin_account(child)

    # ──────────────────────────── Settlement mode ────────────────────────────

    async def set_settlement_mode(
        self,
        *,
        current_admin: AdminAccount,
        account_id: int,
        settlement_mode: str,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if settlement_mode not in {"prepaid", "credit", "hybrid"}:
            raise HTTPException(status_code=400, detail="不支持的结算模式")
        async with get_async_session() as session:
            target = await ensure_visible_account(session, current_admin, int(account_id))
            if not is_agent(target):
                raise HTTPException(status_code=400, detail="只能调整代理账号的结算模式")
            if target.id == current_admin.id and not is_staff(current_admin):
                raise HTTPException(status_code=400, detail="不能修改自己的结算模式")
            if not is_staff(current_admin):
                if target.parent_account_id != current_admin.id and not (
                    is_master_agent(current_admin) and target.root_master_account_id == current_admin.id
                ):
                    raise HTTPException(status_code=403, detail="只能修改直系下级或总代链路内下级的结算模式")
            target.settlement_mode = settlement_mode
            await append_audit(
                session,
                actor=current_admin,
                action="agent.set_settlement_mode",
                target_type="admin_account",
                target_id=str(target.id),
                detail={"settlement_mode": settlement_mode},
                ip_address=ip_address,
            )
            await session.flush()
            await session.refresh(target)
            return serialize_admin_account(target)


# ──────────────────────────── Singleton ────────────────────────────

_agent_service: AgentHierarchyService | None = None


def get_agent_service() -> AgentHierarchyService:
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentHierarchyService()
    return _agent_service
