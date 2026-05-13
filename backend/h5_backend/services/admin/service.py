"""AdminLicenseService — thin facade delegating to domain services.

This module preserves backward compatibility: all existing callers
(`get_admin_license_service().xxx(...)`) continue to work. Each method
delegates to the appropriate domain service extracted in this package.

Domain services:
  - plan_service.PlansService
  - card_service.CardsService
  - proxy_service.ProxiesService
  - developer_app_service.DeveloperAppsService
  - user_service.UsersService
  - settings_service.SettingsService
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import Select, and_, func, select

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import AdminAuditLog
from backend.h5_backend.services.shared.audit import append_audit_log, mask_actor_name
from backend.h5_backend.services.shared.search import LIKE_ESCAPE_CHAR, contains_like_pattern

# ---------------------------------------------------------------------------
# Constants (kept here for backward compatibility; other modules may import)
# ---------------------------------------------------------------------------

AUDIT_ACTION_LABELS = {
    "admin.update_plan": "更新卡密规格配置",
    "admin.delete_plan": "删除卡密规格",
    "admin.generate_cards": "批量生成卡密",
    "admin.set_card_active": "修改卡密状态",
    "admin.reset_user_password": "重置用户密码",
    "admin.delete_account": "删除账号",
    "admin.add_proxy": "新增代理",
    "admin.check_proxy_health": "检测代理健康",
    "admin.delete_proxy": "删除代理",
    "admin.assign_proxy": "分配代理",
    "admin.unassign_proxy": "解绑代理",
    "admin.update_purchase_settings": "更新购买入口配置",
    "admin.update_bot_notice_settings": "更新 Bot 公告栏配置",
    "admin.create_developer_app": "新增开发者应用",
    "admin.update_developer_app": "更新开发者应用",
    "admin.set_default_developer_app": "设置默认开发者应用",
    "admin.set_user_developer_app": "设置用户开发者应用",
    "admin.update_developer_app_settings": "更新开发者应用策略",
    "admin.check_developer_app_health": "手动检测开发者应用",
    "rbac.create_role": "创建后台角色",
    "rbac.update_role": "更新后台角色",
    "rbac.update_role_permissions": "更新角色权限",
    "admin_account.create": "创建后台账号",
    "admin_account.update": "更新后台账号",
    "admin_account.update_roles": "更新后台账号角色",
    "admin_account.reset_password": "重置后台账号密码",
    "system.developer_app_health_changed": "开发者应用健康状态变更",
    "system.developer_app_health_recovered": "开发者应用健康恢复",
}
AUDIT_TARGET_TYPE_LABELS = {
    "user": "用户",
    "account": "账号",
    "plan": "卡密规格",
    "card": "卡密",
    "proxy": "代理",
    "settings": "配置",
    "developer_app": "开发者应用",
    "role": "后台角色",
    "admin_account": "后台账号",
}

MAX_CARD_EXPORT_ROWS = 5000

# Re-export constants that are used by settings_service but may also be
# imported directly from this module by other code.
DEFAULT_PURCHASE_URL = "https://t.me/"
DEFAULT_PURCHASE_BUTTON_TEXT = "联系 Telegram 购买"
DEFAULT_BOT_NOTICE_ENTRY_BUTTON_TEXT = "📢 公告栏"
TELEGRAM_PURCHASE_URL_PREFIXES = ("https://t.me/", "https://telegram.me/", "tg://")


class AdminLicenseService:
    """Thin facade — delegates every method to the appropriate domain service."""

    # ------------------------------------------------------------------
    # Shared helpers (kept for backward compat; new code should use shared/)
    # ------------------------------------------------------------------

    @staticmethod
    def _mask_actor(actor: str) -> str:
        return mask_actor_name(actor)

    async def _append_audit(self, session, *, actor: str, **kwargs) -> None:
        await append_audit_log(session, actor=mask_actor_name(actor), **kwargs)

    # ------------------------------------------------------------------
    # Plans → plan_service.PlansService
    # ------------------------------------------------------------------

    async def list_plans(self) -> List[Dict[str, Any]]:
        from backend.h5_backend.services.admin.plan_service import get_plan_service
        return await get_plan_service().list_plans()

    async def list_all_plans(self) -> List[Dict[str, Any]]:
        from backend.h5_backend.services.admin.plan_service import get_plan_service
        return await get_plan_service().list_all_plans()

    async def create_plan(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.plan_service import get_plan_service
        return await get_plan_service().create_plan(**kwargs)

    async def update_plan(self, plan_code: str, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.plan_service import get_plan_service
        return await get_plan_service().update_plan(plan_code, **kwargs)

    async def delete_plan(self, plan_code: str, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.plan_service import get_plan_service
        return await get_plan_service().delete_plan(plan_code, **kwargs)

    # ------------------------------------------------------------------
    # Cards → card_service.CardsService
    # ------------------------------------------------------------------

    async def generate_cards(self, **kwargs) -> List[Dict[str, Any]]:
        from backend.h5_backend.services.admin.card_service import get_card_service
        return await get_card_service().generate_cards(**kwargs)

    async def list_cards(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.card_service import get_card_service
        return await get_card_service().list_cards(**kwargs)

    async def export_cards_xlsx(self, **kwargs):
        from backend.h5_backend.services.admin.card_service import get_card_service
        return await get_card_service().export_cards_xlsx(**kwargs)

    async def set_card_active(self, card_code: str, is_active: bool, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.card_service import get_card_service
        return await get_card_service().set_card_active(card_code, is_active, **kwargs)

    async def create_single_card(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.card_service import get_card_service
        return await get_card_service().create_single_card(**kwargs)

    # ------------------------------------------------------------------
    # Proxies → proxy_service.ProxiesService
    # ------------------------------------------------------------------

    async def list_proxies(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.proxy_service import get_proxy_service
        return await get_proxy_service().list_proxies(**kwargs)

    async def add_proxy(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.proxy_service import get_proxy_service
        return await get_proxy_service().add_proxy(**kwargs)

    async def check_proxy_health(self, proxy_id: int, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.proxy_service import get_proxy_service
        return await get_proxy_service().check_proxy_health(proxy_id, **kwargs)

    async def delete_proxy(self, proxy_id: int, **kwargs) -> None:
        from backend.h5_backend.services.admin.proxy_service import get_proxy_service
        return await get_proxy_service().delete_proxy(proxy_id, **kwargs)

    async def assign_proxy(self, proxy_id: int, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.proxy_service import get_proxy_service
        return await get_proxy_service().assign_proxy(proxy_id, **kwargs)

    async def unassign_proxy(self, proxy_id: int, **kwargs) -> None:
        from backend.h5_backend.services.admin.proxy_service import get_proxy_service
        return await get_proxy_service().unassign_proxy(proxy_id, **kwargs)

    # ------------------------------------------------------------------
    # Developer Apps → developer_app_service.DeveloperAppsService
    # ------------------------------------------------------------------

    async def list_developer_apps(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.developer_app_service import get_developer_app_admin_service
        return await get_developer_app_admin_service().list_developer_apps(**kwargs)

    async def create_developer_app(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.developer_app_service import get_developer_app_admin_service
        return await get_developer_app_admin_service().create_developer_app(**kwargs)

    async def update_developer_app(self, app_id: int, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.developer_app_service import get_developer_app_admin_service
        return await get_developer_app_admin_service().update_developer_app(app_id, **kwargs)

    async def update_developer_app_settings(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.developer_app_service import get_developer_app_admin_service
        return await get_developer_app_admin_service().update_developer_app_settings(**kwargs)

    async def check_developer_app_health(self, app_id: int, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.developer_app_service import get_developer_app_admin_service
        return await get_developer_app_admin_service().check_developer_app_health(app_id, **kwargs)

    async def set_default_developer_app(self, app_id: int, **kwargs) -> None:
        from backend.h5_backend.services.admin.developer_app_service import get_developer_app_admin_service
        return await get_developer_app_admin_service().set_default_developer_app(app_id, **kwargs)

    async def set_user_developer_app(self, user_id: int, developer_app_id: Optional[int], **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.developer_app_service import get_developer_app_admin_service
        return await get_developer_app_admin_service().set_user_developer_app(user_id, developer_app_id, **kwargs)

    # ------------------------------------------------------------------
    # Users → user_service.UsersService
    # ------------------------------------------------------------------

    async def list_users(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.user_service import get_user_admin_service
        return await get_user_admin_service().list_users(**kwargs)

    async def list_account_options(self, **kwargs) -> List[Dict[str, Any]]:
        from backend.h5_backend.services.admin.user_service import get_user_admin_service
        return await get_user_admin_service().list_account_options(**kwargs)

    async def list_user_accounts(self, user_id: int, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.user_service import get_user_admin_service
        return await get_user_admin_service().list_user_accounts(user_id, **kwargs)

    async def list_account_send_logs(self, user_id: int, account_id: str, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.user_service import get_user_admin_service
        return await get_user_admin_service().list_account_send_logs(user_id, account_id, **kwargs)

    async def list_account_proxy_regions(self) -> List[Dict[str, Any]]:
        from backend.h5_backend.services.admin.user_service import get_user_admin_service
        return await get_user_admin_service().list_account_proxy_regions()

    async def select_account_reauth_proxy(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.user_service import get_user_admin_service
        return await get_user_admin_service().select_account_reauth_proxy(**kwargs)

    async def admin_delete_account(self, account_id: str, **kwargs) -> None:
        from backend.h5_backend.services.admin.user_service import get_user_admin_service
        return await get_user_admin_service().admin_delete_account(account_id, **kwargs)

    async def reset_user_password(self, user_id: int, new_password: str, **kwargs) -> None:
        from backend.h5_backend.services.admin.user_service import get_user_admin_service
        return await get_user_admin_service().reset_user_password(user_id, new_password, **kwargs)

    async def list_authorizations(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.user_service import get_user_admin_service
        return await get_user_admin_service().list_authorizations(**kwargs)

    # ------------------------------------------------------------------
    # Settings → settings_service.SettingsService
    # ------------------------------------------------------------------

    async def get_purchase_settings(self) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.settings_service import get_settings_service
        return await get_settings_service().get_purchase_settings()

    async def get_bot_notice_settings(self) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.settings_service import get_settings_service
        return await get_settings_service().get_bot_notice_settings()

    async def update_purchase_settings(self, **kwargs) -> Dict[str, str]:
        from backend.h5_backend.services.admin.settings_service import get_settings_service
        return await get_settings_service().update_purchase_settings(**kwargs)

    async def update_bot_notice_settings(self, **kwargs) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.settings_service import get_settings_service
        return await get_settings_service().update_bot_notice_settings(**kwargs)

    async def get_today_system_stats(self) -> Dict[str, Any]:
        from backend.h5_backend.services.admin.settings_service import get_settings_service
        return await get_settings_service().get_today_system_stats()

    # ------------------------------------------------------------------
    # Audit (stays here — not extracted to a separate domain service)
    # ------------------------------------------------------------------

    async def list_audit_logs(
        self,
        action: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        developer_app_id: Optional[int] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))

        stmt: Select = select(AdminAuditLog)
        count_stmt: Select = select(func.count(AdminAuditLog.id))
        conditions = []
        if action:
            conditions.append(AdminAuditLog.action == action)
        if target_type:
            conditions.append(AdminAuditLog.target_type == target_type)
        if target_id:
            conditions.append(AdminAuditLog.target_id == target_id)
        if developer_app_id is not None:
            conditions.append(AdminAuditLog.developer_app_id == int(developer_app_id))
        normalized_keyword = (keyword or "").strip()
        if normalized_keyword:
            keyword_value = contains_like_pattern(normalized_keyword)
            keyword_condition = (
                AdminAuditLog.actor.ilike(keyword_value, escape=LIKE_ESCAPE_CHAR)
                | AdminAuditLog.action.ilike(keyword_value, escape=LIKE_ESCAPE_CHAR)
                | AdminAuditLog.target_id.ilike(keyword_value, escape=LIKE_ESCAPE_CHAR)
            )
            conditions.append(keyword_condition)
        if conditions:
            stmt = stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))
        stmt = stmt.order_by(AdminAuditLog.id.desc()).limit(limit).offset(offset)

        async with get_async_session() as session:
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            rows = (await session.execute(stmt)).scalars().all()

        items = [
            {
                "id": row.id,
                "actor": row.actor,
                "action": row.action,
                "action_label": AUDIT_ACTION_LABELS.get(row.action, row.action),
                "target_type": row.target_type,
                "target_type_label": (
                    AUDIT_TARGET_TYPE_LABELS.get(row.target_type, row.target_type)
                    if row.target_type
                    else None
                ),
                "target_id": row.target_id,
                "developer_app_id": row.developer_app_id,
                "old_value": row.old_value,
                "new_value": row.new_value,
                "detail": row.detail,
                "ip_address": row.ip_address,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_admin_license_service: AdminLicenseService | None = None


def get_admin_license_service() -> AdminLicenseService:
    """Get singleton admin license service."""
    global _admin_license_service
    if _admin_license_service is None:
        _admin_license_service = AdminLicenseService()
    return _admin_license_service
