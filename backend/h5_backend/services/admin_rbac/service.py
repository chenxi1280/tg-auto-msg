"""RBAC service for backoffice admin console."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import selectinload

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    AdminAccount,
    AdminAccountRole,
    AdminAccountTgBinding,
    AdminAuditLog,
    AdminPermission,
    AdminRole,
    AdminRolePermission,
)
from backend.h5_backend.services.auth.service import get_auth_service

ROLE_SUPER_ADMIN = "super_admin"
ROLE_MASTER_AGENT = "master_agent"
ROLE_SUB_AGENT = "sub_agent"
ACCOUNT_TYPE_STAFF = "staff"
ACCOUNT_TYPE_AGENT = "agent"
BUSINESS_IDENTITY_MASTER_AGENT = "master_agent"
BUSINESS_IDENTITY_SUB_AGENT = "sub_agent"

PERMISSION_DEFINITIONS: List[Dict[str, str]] = [
    {"code": "dashboard.read", "module": "dashboard", "name": "查看仪表盘", "description": "允许进入后台仪表盘"},
    {"code": "system.stats.read", "module": "system_stats", "name": "查看系统统计", "description": "允许查看超管系统统计页"},
    {"code": "security.read", "module": "security", "name": "查看账户安全", "description": "允许查看自己的后台账号安全信息"},
    {"code": "security.update", "module": "security", "name": "修改账户安全", "description": "允许修改密码和 TG 绑定"},
    {"code": "agents.read", "module": "agents", "name": "查看代理", "description": "允许查看代理账号树和链路信息"},
    {"code": "agents.write", "module": "agents", "name": "管理代理", "description": "允许创建下级、调额和设置结算模式"},
    {"code": "agents.master.create", "module": "agents", "name": "创建总代", "description": "允许创建省级总代"},
    {"code": "agents.credit.master.write", "module": "agents", "name": "管理总代额度", "description": "允许设置总代总额度和授信白名单"},
    {"code": "agents.child.create", "module": "agents", "name": "创建下级代理", "description": "允许创建直属下级代理"},
    {"code": "pricing.read", "module": "pricing", "name": "查看统一价格", "description": "允许查看统一价格"},
    {"code": "pricing.write", "module": "pricing", "name": "管理统一价格", "description": "允许更新统一价格"},
    {"code": "ledgers.read", "module": "ledgers", "name": "查看自有流水", "description": "允许查看自己的资金流水"},
    {"code": "ledgers.scope.read", "module": "ledgers", "name": "查看范围流水", "description": "允许查看自己权限范围内的资金流水审计"},
    {"code": "operation_logs.read", "module": "operation_logs", "name": "查看自有操作日志", "description": "允许查看自己的业务操作日志"},
    {"code": "operation_logs.scope.read", "module": "operation_logs", "name": "查看范围操作日志", "description": "允许查看自己权限范围内的业务操作日志"},
    {"code": "batches.read", "module": "batches", "name": "查看卡密批次", "description": "允许查看批次和卡密明细"},
    {"code": "batches.generate", "module": "batches", "name": "生成卡密批次", "description": "允许直接生成卡密批次"},
    {"code": "batches.export", "module": "batches", "name": "导出卡密", "description": "允许导出卡密 Excel"},
    {"code": "batches.copy", "module": "batches", "name": "复制卡密", "description": "允许复制卡密"},
    {"code": "audit.read", "module": "audit", "name": "查看审计", "description": "允许查看审计日志"},
    {"code": "audit.system.read", "module": "audit", "name": "查看系统审计", "description": "允许查看系统级全量审计日志"},
    {"code": "system.settings.read", "module": "system_settings", "name": "查看系统配置", "description": "允许查看购买入口和 Bot 公告栏"},
    {"code": "system.settings.update", "module": "system_settings", "name": "修改系统配置", "description": "允许更新购买入口和 Bot 公告栏"},
    {"code": "developer_apps.read", "module": "developer_apps", "name": "查看开发者应用", "description": "允许查看开发者应用池"},
    {"code": "developer_apps.write", "module": "developer_apps", "name": "管理开发者应用", "description": "允许新增和编辑开发者应用"},
    {"code": "developer_apps.check", "module": "developer_apps", "name": "检查开发者应用", "description": "允许健康检查与设置默认应用"},
    {"code": "system_proxies.read", "module": "system_proxies", "name": "查看系统代理", "description": "允许查看系统代理池"},
    {"code": "system_proxies.write", "module": "system_proxies", "name": "管理系统代理", "description": "允许新增和删除系统代理"},
    {"code": "system_proxies.check", "module": "system_proxies", "name": "检查系统代理", "description": "允许检测系统代理健康"},
    {"code": "system_proxies.assign", "module": "system_proxies", "name": "分配系统代理", "description": "允许分配或解绑系统代理"},
    {"code": "legacy_cards.read", "module": "legacy_cards", "name": "查看旧卡密", "description": "允许查看旧卡密规格、卡密和授权"},
    {"code": "legacy_cards.write", "module": "legacy_cards", "name": "管理旧卡密", "description": "允许修改旧卡密规格和生成卡密"},
    {"code": "legacy_cards.export", "module": "legacy_cards", "name": "导出旧卡密", "description": "允许导出旧卡密列表"},
    {"code": "users.read", "module": "users", "name": "查看用户授权", "description": "允许查看用户、TG 账号和授权"},
    {"code": "users.write", "module": "users", "name": "管理用户授权", "description": "允许设置用户开发者应用和删除账号"},
    {"code": "users.reset_password", "module": "users", "name": "重置用户密码", "description": "允许重置用户密码"},
    {"code": "admin_accounts.read", "module": "admin_accounts", "name": "查看后台账号", "description": "允许查看后台账号列表"},
    {"code": "admin_accounts.write", "module": "admin_accounts", "name": "管理后台账号", "description": "允许创建、编辑和分配后台账号角色"},
    {"code": "admin_accounts.reset_password", "module": "admin_accounts", "name": "重置后台密码", "description": "允许重置后台账号密码"},
    {"code": "rbac.roles.read", "module": "rbac_roles", "name": "查看角色", "description": "允许查看角色和角色权限"},
    {"code": "rbac.roles.write", "module": "rbac_roles", "name": "管理角色", "description": "允许创建角色和修改角色权限"},
    {"code": "rbac.permissions.read", "module": "rbac_permissions", "name": "查看权限", "description": "允许查看权限点字典"},
]

ROLE_DEFAULT_PERMISSION_CODES: Dict[str, List[str]] = {
    ROLE_SUPER_ADMIN: [item["code"] for item in PERMISSION_DEFINITIONS],
    ROLE_MASTER_AGENT: [
        "dashboard.read",
        "security.read",
        "security.update",
        "agents.read",
        "agents.write",
        "agents.child.create",
        "pricing.read",
        "ledgers.read",
        "ledgers.scope.read",
        "operation_logs.read",
        "operation_logs.scope.read",
        "batches.read",
        "batches.generate",
        "batches.export",
        "batches.copy",
        "audit.read",
    ],
    ROLE_SUB_AGENT: [
        "dashboard.read",
        "security.read",
        "security.update",
        "agents.read",
        "agents.write",
        "agents.child.create",
        "pricing.read",
        "ledgers.read",
        "operation_logs.read",
        "operation_logs.scope.read",
        "batches.read",
        "batches.generate",
        "batches.export",
        "batches.copy",
        "audit.read",
    ],
}

SYSTEM_ROLE_META: Dict[str, Dict[str, str]] = {
    ROLE_SUPER_ADMIN: {"display_name": "超管", "description": "系统超管，拥有后台全部能力"},
    ROLE_MASTER_AGENT: {"display_name": "总代默认角色", "description": "省总代账号默认角色"},
    ROLE_SUB_AGENT: {"display_name": "下级代理默认角色", "description": "下级代理账号默认角色"},
}


class AdminRbacService:
    """RBAC service for admin roles, permissions and accounts."""

    @staticmethod
    def _normalize_limit(limit: int, offset: int) -> Tuple[int, int]:
        return max(1, min(500, int(limit))), max(0, int(offset))

    @staticmethod
    def _slugify_role_key(value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", (value or "").strip()).strip("_").lower()
        return normalized[:64]

    @staticmethod
    def _resolve_account_type(account: AdminAccount) -> str:
        if getattr(account, "account_type", None) in {ACCOUNT_TYPE_STAFF, ACCOUNT_TYPE_AGENT}:
            return str(account.account_type)
        if str(getattr(account, "role_code", "") or "").strip().lower() in {ROLE_MASTER_AGENT, ROLE_SUB_AGENT}:
            return ACCOUNT_TYPE_AGENT
        return ACCOUNT_TYPE_STAFF

    @staticmethod
    def _resolve_business_identity(account: AdminAccount) -> Optional[str]:
        identity = str(getattr(account, "business_identity", "") or "").strip().lower()
        if identity in {BUSINESS_IDENTITY_MASTER_AGENT, BUSINESS_IDENTITY_SUB_AGENT}:
            return identity
        normalized_role = str(getattr(account, "role_code", "") or "").strip().lower()
        if normalized_role == ROLE_MASTER_AGENT:
            return BUSINESS_IDENTITY_MASTER_AGENT
        if normalized_role == ROLE_SUB_AGENT:
            return BUSINESS_IDENTITY_SUB_AGENT
        return None

    def _default_role_keys_for_account(self, account: AdminAccount) -> List[str]:
        role_keys: List[str] = []
        if str(getattr(account, "role_code", "") or "").strip().lower() == ROLE_SUPER_ADMIN:
            role_keys.append(ROLE_SUPER_ADMIN)
        business_identity = self._resolve_business_identity(account)
        if business_identity == BUSINESS_IDENTITY_MASTER_AGENT:
            role_keys.append(ROLE_MASTER_AGENT)
        elif business_identity == BUSINESS_IDENTITY_SUB_AGENT:
            role_keys.append(ROLE_SUB_AGENT)
        return role_keys

    @staticmethod
    def _mask_actor(account: AdminAccount) -> str:
        return f"{account.username}#{account.id}"

    @staticmethod
    def _serialize_tg_binding(binding: Optional[AdminAccountTgBinding]) -> Dict[str, Any]:
        if binding is None:
            return {
                "bind_status": "unbound",
                "tg_user_id": None,
                "tg_username": None,
                "bound_at": None,
            }
        return {
            "bind_status": binding.bind_status,
            "tg_user_id": binding.tg_user_id,
            "tg_username": binding.tg_username,
            "bound_at": binding.bound_at.isoformat() if binding.bound_at else None,
        }

    @staticmethod
    def _serialize_permission(permission: AdminPermission) -> Dict[str, Any]:
        return {
            "id": permission.id,
            "permission_code": permission.permission_code,
            "module_key": permission.module_key,
            "display_name": permission.display_name,
            "description": permission.description,
        }

    def _serialize_role(self, role: AdminRole) -> Dict[str, Any]:
        permission_bindings = role.__dict__.get("permission_bindings") or []
        account_bindings = role.__dict__.get("account_bindings") or []
        permission_codes = sorted(
            {
                binding.permission.permission_code
                for binding in permission_bindings
                if getattr(binding, "permission", None) is not None
            }
        )
        return {
            "id": role.id,
            "role_key": role.role_key,
            "display_name": role.display_name,
            "description": role.description,
            "status": role.status,
            "is_system": role.is_system,
            "permission_codes": permission_codes,
            "permission_count": len(permission_codes),
            "account_count": len(account_bindings),
            "created_at": role.created_at.isoformat() if role.created_at else None,
            "updated_at": role.updated_at.isoformat() if role.updated_at else None,
        }

    def _serialize_admin_account(self, account: AdminAccount) -> Dict[str, Any]:
        role_bindings = account.__dict__.get("role_bindings") or []
        roles = [
            {
                "role_id": binding.role.id,
                "role_key": binding.role.role_key,
                "display_name": binding.role.display_name,
                "is_system": bool(binding.role.is_system),
            }
            for binding in role_bindings
            if getattr(binding, "role", None) is not None
        ]
        roles = sorted(roles, key=lambda item: (not item["is_system"], item["role_key"]))
        return {
            "id": account.id,
            "username": account.username,
            "display_name": account.display_name,
            "role_code": account.role_code,
            "account_type": self._resolve_account_type(account),
            "business_identity": self._resolve_business_identity(account),
            "province_code": account.province_code,
            "parent_account_id": account.parent_account_id,
            "root_master_account_id": account.root_master_account_id,
            "level_depth": account.level_depth,
            "status": account.status,
            "settlement_mode": account.settlement_mode,
            "is_credit_whitelisted": bool(account.is_credit_whitelisted),
            "credit_limit_cents": int(account.credit_limit_cents or 0),
            "allocated_credit_limit_cents": int(account.allocated_credit_limit_cents or 0),
            "credit_used_cents": int(account.credit_used_cents or 0),
            "credit_prepay_cents": int(getattr(account, "credit_prepay_cents", 0) or 0),
            "balance_cents": int(account.balance_cents or 0),
            "force_password_change": bool(account.force_password_change),
            "contact_name": account.contact_name,
            "contact_phone": account.contact_phone,
            "last_login_at": account.last_login_at.isoformat() if account.last_login_at else None,
            "created_at": account.created_at.isoformat() if account.created_at else None,
            "updated_at": account.updated_at.isoformat() if account.updated_at else None,
            "tg_binding": self._serialize_tg_binding(account.__dict__.get("tg_binding")),
            "assigned_roles": roles,
        }

    async def _append_audit(
        self,
        session: Any,
        *,
        actor: AdminAccount,
        action: str,
        target_type: Optional[str],
        target_id: Optional[str],
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        session.add(
            AdminAuditLog(
                actor=self._mask_actor(actor),
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=detail or {},
            )
        )

    async def load_account_with_rbac(self, account_id: int) -> Optional[AdminAccount]:
        async with get_async_session() as session:
            return (
                await session.execute(
                    select(AdminAccount)
                    .options(
                        selectinload(AdminAccount.tg_binding),
                        selectinload(AdminAccount.role_bindings)
                        .selectinload(AdminAccountRole.role)
                        .selectinload(AdminRole.permission_bindings)
                        .selectinload(AdminRolePermission.permission),
                    )
                    .where(AdminAccount.id == int(account_id))
                    .limit(1)
                )
            ).scalar_one_or_none()

    def get_role_keys_for_account(self, account: AdminAccount) -> List[str]:
        role_bindings = account.__dict__.get("role_bindings") or []
        role_keys = {
            binding.role.role_key
            for binding in role_bindings
            if getattr(binding, "role", None) is not None and binding.role.status == "active"
        }
        if not role_keys:
            role_keys.update(self._default_role_keys_for_account(account))
        return sorted(role_keys)

    def get_permission_codes_for_account(self, account: AdminAccount) -> List[str]:
        role_bindings = account.__dict__.get("role_bindings") or []
        permission_codes = {
            binding.permission.permission_code
            for role_binding in role_bindings
            if getattr(role_binding, "role", None) is not None and role_binding.role.status == "active"
            for binding in (role_binding.role.__dict__.get("permission_bindings") or [])
            if getattr(binding, "permission", None) is not None
        }
        if not permission_codes:
            for role_key in self._default_role_keys_for_account(account):
                permission_codes.update(ROLE_DEFAULT_PERMISSION_CODES.get(role_key, []))
        return sorted(permission_codes)

    async def ensure_builtin_rbac(self) -> None:
        async with get_async_session() as session:
            existing_permissions = {
                item.permission_code: item
                for item in (await session.execute(select(AdminPermission))).scalars().all()
            }
            for definition in PERMISSION_DEFINITIONS:
                permission = existing_permissions.get(definition["code"])
                if permission is None:
                    permission = AdminPermission(
                        permission_code=definition["code"],
                        module_key=definition["module"],
                        display_name=definition["name"],
                        description=definition["description"],
                    )
                    session.add(permission)
                    await session.flush()
                    existing_permissions[definition["code"]] = permission
                else:
                    permission.module_key = definition["module"]
                    permission.display_name = definition["name"]
                    permission.description = definition["description"]

            existing_roles = {
                item.role_key: item
                for item in (
                    await session.execute(
                        select(AdminRole).options(selectinload(AdminRole.permission_bindings))
                    )
                ).scalars().all()
            }
            for role_key, meta in SYSTEM_ROLE_META.items():
                role = existing_roles.get(role_key)
                if role is None:
                    role = AdminRole(
                        role_key=role_key,
                        display_name=meta["display_name"],
                        description=meta["description"],
                        status="active",
                        is_system=True,
                    )
                    session.add(role)
                    await session.flush()
                    existing_roles[role_key] = role
                else:
                    role.display_name = meta["display_name"]
                    role.description = meta["description"]
                    role.status = "active"
                    role.is_system = True

                existing_bindings = {
                    binding.permission_id: binding
                    for binding in (role.__dict__.get("permission_bindings") or [])
                }
                expected_permission_ids = {
                    existing_permissions[code].id
                    for code in ROLE_DEFAULT_PERMISSION_CODES.get(role_key, [])
                    if code in existing_permissions
                }
                for permission_id in list(existing_bindings.keys()):
                    if permission_id not in expected_permission_ids:
                        await session.delete(existing_bindings[permission_id])
                for permission_id in expected_permission_ids:
                    if permission_id not in existing_bindings:
                        session.add(AdminRolePermission(role_id=int(role.id), permission_id=int(permission_id)))

            accounts = (await session.execute(select(AdminAccount))).scalars().all()
            for account in accounts:
                for role_key in self._default_role_keys_for_account(account):
                    role = existing_roles.get(role_key)
                    if role is None:
                        continue
                    binding_exists = (
                        await session.execute(
                            select(AdminAccountRole.id)
                            .where(
                                AdminAccountRole.admin_account_id == int(account.id),
                                AdminAccountRole.role_id == int(role.id),
                            )
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    if binding_exists is None:
                        session.add(AdminAccountRole(admin_account_id=int(account.id), role_id=int(role.id)))

    async def list_permissions(self) -> Dict[str, Any]:
        async with get_async_session() as session:
            permissions = (
                await session.execute(
                    select(AdminPermission).order_by(AdminPermission.module_key.asc(), AdminPermission.permission_code.asc())
                )
            ).scalars().all()
        return {
            "items": [self._serialize_permission(item) for item in permissions],
            "total": len(permissions),
        }

    async def list_roles(self) -> Dict[str, Any]:
        async with get_async_session() as session:
            roles = (
                await session.execute(
                    select(AdminRole)
                    .options(
                        selectinload(AdminRole.permission_bindings).selectinload(AdminRolePermission.permission),
                        selectinload(AdminRole.account_bindings),
                    )
                    .order_by(AdminRole.is_system.desc(), AdminRole.role_key.asc())
                )
            ).scalars().all()
        return {"items": [self._serialize_role(item) for item in roles], "total": len(roles)}

    async def create_role(
        self,
        *,
        current_admin: AdminAccount,
        role_key: str,
        display_name: str,
        description: Optional[str],
    ) -> Dict[str, Any]:
        normalized_key = self._slugify_role_key(role_key)
        if not normalized_key:
            raise HTTPException(status_code=400, detail="角色标识不能为空")
        async with get_async_session() as session:
            exists = (
                await session.execute(select(AdminRole.id).where(AdminRole.role_key == normalized_key).limit(1))
            ).scalar_one_or_none()
            if exists is not None:
                raise HTTPException(status_code=409, detail="角色标识已存在")
            role = AdminRole(
                role_key=normalized_key,
                display_name=(display_name or "").strip() or normalized_key,
                description=(description or "").strip() or None,
                status="active",
                is_system=False,
            )
            session.add(role)
            await session.flush()
            await self._append_audit(
                session,
                actor=current_admin,
                action="rbac.create_role",
                target_type="role",
                target_id=normalized_key,
                detail={"role_key": normalized_key},
            )
            await session.refresh(role)
            return self._serialize_role(role)

    async def update_role(
        self,
        *,
        current_admin: AdminAccount,
        role_id: int,
        display_name: Optional[str],
        description: Optional[str],
        status: Optional[str],
    ) -> Dict[str, Any]:
        async with get_async_session() as session:
            role = await session.get(AdminRole, int(role_id))
            if role is None:
                raise HTTPException(status_code=404, detail="角色不存在")
            if display_name is not None:
                role.display_name = display_name.strip() or role.display_name
            if description is not None:
                role.description = description.strip() or None
            if status is not None:
                normalized_status = status.strip().lower()
                if normalized_status not in {"active", "disabled"}:
                    raise HTTPException(status_code=400, detail="角色状态不合法")
                role.status = normalized_status
            await self._append_audit(
                session,
                actor=current_admin,
                action="rbac.update_role",
                target_type="role",
                target_id=role.role_key,
                detail={"role_id": int(role.id)},
            )
            await session.flush()
            role = (
                await session.execute(
                    select(AdminRole)
                    .options(
                        selectinload(AdminRole.permission_bindings).selectinload(AdminRolePermission.permission),
                        selectinload(AdminRole.account_bindings),
                    )
                    .where(AdminRole.id == int(role.id))
                    .limit(1)
                )
            ).scalar_one()
            return self._serialize_role(role)

    async def update_role_permissions(
        self,
        *,
        current_admin: AdminAccount,
        role_id: int,
        permission_codes: Sequence[str],
    ) -> Dict[str, Any]:
        normalized_codes = sorted({str(code or "").strip() for code in permission_codes if str(code or "").strip()})
        async with get_async_session() as session:
            role = (
                await session.execute(
                    select(AdminRole)
                    .options(selectinload(AdminRole.permission_bindings))
                    .where(AdminRole.id == int(role_id))
                    .limit(1)
                )
            ).scalar_one_or_none()
            if role is None:
                raise HTTPException(status_code=404, detail="角色不存在")
            permissions = (
                await session.execute(
                    select(AdminPermission).where(AdminPermission.permission_code.in_(normalized_codes))
                )
            ).scalars().all()
            permission_map = {item.permission_code: item for item in permissions}
            missing = [code for code in normalized_codes if code not in permission_map]
            if missing:
                raise HTTPException(status_code=400, detail=f"权限点不存在: {', '.join(missing)}")
            existing_bindings = {binding.permission_id: binding for binding in (role.__dict__.get("permission_bindings") or [])}
            target_permission_ids = {int(permission_map[code].id) for code in normalized_codes}
            for permission_id, binding in list(existing_bindings.items()):
                if permission_id not in target_permission_ids:
                    await session.delete(binding)
            for permission_id in target_permission_ids:
                if permission_id not in existing_bindings:
                    session.add(AdminRolePermission(role_id=int(role.id), permission_id=int(permission_id)))
            await self._append_audit(
                session,
                actor=current_admin,
                action="rbac.update_role_permissions",
                target_type="role",
                target_id=role.role_key,
                detail={"permission_codes": normalized_codes},
            )
            await session.flush()
            role = (
                await session.execute(
                    select(AdminRole)
                    .options(
                        selectinload(AdminRole.permission_bindings).selectinload(AdminRolePermission.permission),
                        selectinload(AdminRole.account_bindings),
                    )
                    .where(AdminRole.id == int(role.id))
                    .limit(1)
                )
            ).scalar_one()
            return self._serialize_role(role)

    async def list_admin_accounts(
        self,
        *,
        search: Optional[str] = None,
        status: Optional[str] = None,
        role_key: Optional[str] = None,
        account_type: Optional[str] = None,
        business_identity: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit, offset = self._normalize_limit(limit, offset)
        async with get_async_session() as session:
            stmt = select(AdminAccount).options(
                selectinload(AdminAccount.tg_binding),
                selectinload(AdminAccount.role_bindings).selectinload(AdminAccountRole.role),
            )
            count_stmt = select(func.count(AdminAccount.id))
            normalized_search = (search or "").strip()
            if normalized_search:
                keyword = f"%{normalized_search}%"
                condition = or_(
                    AdminAccount.username.ilike(keyword),
                    AdminAccount.display_name.ilike(keyword),
                    AdminAccount.contact_name.ilike(keyword),
                )
                stmt = stmt.where(condition)
                count_stmt = count_stmt.where(condition)
            normalized_status = (status or "").strip().lower()
            if normalized_status and normalized_status != "all":
                stmt = stmt.where(AdminAccount.status == normalized_status)
                count_stmt = count_stmt.where(AdminAccount.status == normalized_status)
            normalized_account_type = (account_type or "").strip().lower()
            if normalized_account_type and normalized_account_type != "all":
                stmt = stmt.where(AdminAccount.account_type == normalized_account_type)
                count_stmt = count_stmt.where(AdminAccount.account_type == normalized_account_type)
            normalized_business_identity = (business_identity or "").strip().lower()
            if normalized_business_identity and normalized_business_identity != "all":
                stmt = stmt.where(AdminAccount.business_identity == normalized_business_identity)
                count_stmt = count_stmt.where(AdminAccount.business_identity == normalized_business_identity)
            normalized_role_key = (role_key or "").strip()
            if normalized_role_key:
                stmt = stmt.join(AdminAccountRole, AdminAccountRole.admin_account_id == AdminAccount.id).join(
                    AdminRole, AdminRole.id == AdminAccountRole.role_id
                ).where(AdminRole.role_key == normalized_role_key)
                count_stmt = count_stmt.join(AdminAccountRole, AdminAccountRole.admin_account_id == AdminAccount.id).join(
                    AdminRole, AdminRole.id == AdminAccountRole.role_id
                ).where(AdminRole.role_key == normalized_role_key)
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (
                await session.execute(
                    stmt.order_by(AdminAccount.created_at.desc(), AdminAccount.id.desc()).limit(limit).offset(offset)
                )
            ).scalars().unique().all()
            return {
                "items": [self._serialize_admin_account(item) for item in rows],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    async def create_admin_account(
        self,
        *,
        current_admin: AdminAccount,
        username: str,
        password: str,
        display_name: str,
        role_keys: Sequence[str],
        account_type: str = ACCOUNT_TYPE_STAFF,
        business_identity: Optional[str] = None,
        contact_name: Optional[str] = None,
        contact_phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        if len(password or "") < 6:
            raise HTTPException(status_code=400, detail="密码至少 6 位")
        normalized_account_type = (account_type or "").strip().lower() or ACCOUNT_TYPE_STAFF
        if normalized_account_type != ACCOUNT_TYPE_STAFF:
            raise HTTPException(status_code=400, detail="后台账号仅支持创建员工账号")
        normalized_business_identity = (business_identity or "").strip().lower() or None
        if normalized_business_identity is not None:
            raise HTTPException(status_code=400, detail="后台账号不能设置代理业务身份")
        normalized_role_keys = sorted({str(key or "").strip() for key in role_keys if str(key or "").strip()})
        if not normalized_role_keys:
            raise HTTPException(status_code=400, detail="请至少绑定一个后台角色")
        async with get_async_session() as session:
            exists = (
                await session.execute(select(AdminAccount.id).where(AdminAccount.username == (username or "").strip()).limit(1))
            ).scalar_one_or_none()
            if exists is not None:
                raise HTTPException(status_code=409, detail="后台用户名已存在")
            account = AdminAccount(
                username=(username or "").strip(),
                password_hash=get_auth_service().get_password_hash(password),
                role_code=ACCOUNT_TYPE_STAFF,
                account_type=ACCOUNT_TYPE_STAFF,
                business_identity=None,
                province_code=current_admin.province_code,
                parent_account_id=None,
                root_master_account_id=None,
                level_depth=0,
                status="active",
                settlement_mode="prepaid",
                is_credit_whitelisted=False,
                credit_limit_cents=0,
                allocated_credit_limit_cents=0,
                credit_used_cents=0,
                balance_cents=0,
                force_password_change=True,
                display_name=(display_name or "").strip() or (username or "").strip(),
                contact_name=(contact_name or "").strip() or None,
                contact_phone=(contact_phone or "").strip() or None,
                created_by=int(current_admin.id),
            )
            session.add(account)
            await session.flush()
            roles = (
                await session.execute(select(AdminRole).where(AdminRole.role_key.in_(normalized_role_keys)))
            ).scalars().all()
            role_map = {item.role_key: item for item in roles}
            missing = [key for key in normalized_role_keys if key not in role_map]
            if missing:
                raise HTTPException(status_code=400, detail=f"角色不存在: {', '.join(missing)}")
            for item in role_map.values():
                session.add(AdminAccountRole(admin_account_id=int(account.id), role_id=int(item.id)))
            await self._append_audit(
                session,
                actor=current_admin,
                action="admin_account.create",
                target_type="admin_account",
                target_id=str(account.id),
                detail={"username": account.username, "account_type": ACCOUNT_TYPE_STAFF, "role_keys": normalized_role_keys},
            )
            account = (
                await session.execute(
                    select(AdminAccount)
                    .options(
                        selectinload(AdminAccount.tg_binding),
                        selectinload(AdminAccount.role_bindings).selectinload(AdminAccountRole.role),
                    )
                    .where(AdminAccount.id == int(account.id))
                    .limit(1)
                )
            ).scalar_one()
            return self._serialize_admin_account(account)

    async def update_admin_account(
        self,
        *,
        current_admin: AdminAccount,
        account_id: int,
        display_name: Optional[str] = None,
        status: Optional[str] = None,
        contact_name: Optional[str] = None,
        contact_phone: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with get_async_session() as session:
            account = await session.get(AdminAccount, int(account_id))
            if account is None:
                raise HTTPException(status_code=404, detail="后台账号不存在")
            if display_name is not None:
                account.display_name = display_name.strip() or account.display_name
            if contact_name is not None:
                account.contact_name = contact_name.strip() or None
            if contact_phone is not None:
                account.contact_phone = contact_phone.strip() or None
            if status is not None:
                normalized_status = status.strip().lower()
                if normalized_status not in {"active", "disabled"}:
                    raise HTTPException(status_code=400, detail="后台账号状态不合法")
                account.status = normalized_status
            await self._append_audit(
                session,
                actor=current_admin,
                action="admin_account.update",
                target_type="admin_account",
                target_id=str(account.id),
                detail={"status": account.status},
            )
            await session.flush()
            account = (
                await session.execute(
                    select(AdminAccount)
                    .options(
                        selectinload(AdminAccount.tg_binding),
                        selectinload(AdminAccount.role_bindings).selectinload(AdminAccountRole.role),
                    )
                    .where(AdminAccount.id == int(account.id))
                    .limit(1)
                )
            ).scalar_one()
            return self._serialize_admin_account(account)

    async def update_admin_account_roles(
        self,
        *,
        current_admin: AdminAccount,
        account_id: int,
        role_keys: Sequence[str],
    ) -> Dict[str, Any]:
        normalized_role_keys = sorted({str(key or "").strip() for key in role_keys if str(key or "").strip()})
        if not normalized_role_keys:
            raise HTTPException(status_code=400, detail="至少保留一个角色")
        async with get_async_session() as session:
            account = (
                await session.execute(
                    select(AdminAccount)
                    .options(selectinload(AdminAccount.role_bindings))
                    .where(AdminAccount.id == int(account_id))
                    .limit(1)
                )
            ).scalar_one_or_none()
            if account is None:
                raise HTTPException(status_code=404, detail="后台账号不存在")
            roles = (
                await session.execute(select(AdminRole).where(AdminRole.role_key.in_(normalized_role_keys)))
            ).scalars().all()
            role_map = {item.role_key: item for item in roles}
            missing = [key for key in normalized_role_keys if key not in role_map]
            if missing:
                raise HTTPException(status_code=400, detail=f"角色不存在: {', '.join(missing)}")
            current_bindings = {binding.role_id: binding for binding in (account.__dict__.get("role_bindings") or [])}
            target_role_ids = {int(role_map[key].id) for key in normalized_role_keys}
            for role_id, binding in list(current_bindings.items()):
                if role_id not in target_role_ids:
                    await session.delete(binding)
            for role_id in target_role_ids:
                if role_id not in current_bindings:
                    session.add(AdminAccountRole(admin_account_id=int(account.id), role_id=role_id))
            await self._append_audit(
                session,
                actor=current_admin,
                action="admin_account.update_roles",
                target_type="admin_account",
                target_id=str(account.id),
                detail={"role_keys": normalized_role_keys},
            )
            await session.flush()
            account = (
                await session.execute(
                    select(AdminAccount)
                    .options(
                        selectinload(AdminAccount.tg_binding),
                        selectinload(AdminAccount.role_bindings).selectinload(AdminAccountRole.role),
                    )
                    .where(AdminAccount.id == int(account.id))
                    .limit(1)
                )
            ).scalar_one()
            return self._serialize_admin_account(account)

    async def reset_admin_account_password(
        self,
        *,
        current_admin: AdminAccount,
        account_id: int,
        new_password: str,
    ) -> Dict[str, Any]:
        if len(new_password or "") < 6:
            raise HTTPException(status_code=400, detail="新密码至少 6 位")
        async with get_async_session() as session:
            account = await session.get(AdminAccount, int(account_id))
            if account is None:
                raise HTTPException(status_code=404, detail="后台账号不存在")
            account.password_hash = get_auth_service().get_password_hash(new_password)
            account.force_password_change = True
            await self._append_audit(
                session,
                actor=current_admin,
                action="admin_account.reset_password",
                target_type="admin_account",
                target_id=str(account.id),
                detail={"username": account.username},
            )
            await session.flush()
            return {"account_id": int(account.id), "username": account.username, "force_password_change": True}


_service: Optional[AdminRbacService] = None


def get_admin_rbac_service() -> AdminRbacService:
    global _service
    if _service is None:
        _service = AdminRbacService()
    return _service
