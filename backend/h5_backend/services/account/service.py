"""Account domain service for H5 API."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, HTTPException

from backend.bot.account.manager import get_account_manager
from backend.bot.resources.manager import get_resource_manager
from backend.h5_backend.dependencies import check_account_permission
from backend.h5_backend.services.licensing.service import (
    activate_card_for_user,
    bind_slot_to_account,
    get_account_authorization_summary,
)

_SYNCING_USERS: set[int] = set()


class AccountService:
    """Account and resource business service."""

    async def list_accounts(self, user_id: int, probe: bool = False) -> List[Dict[str, Any]]:
        account_manager = get_account_manager()
        accounts = await account_manager.get_accounts(user_id, is_active=False)

        if probe:
            # 刷新状态时尝试自动重连探测：会话仍有效可自动恢复在线
            for account in accounts:
                if not account.is_active or account.is_banned:
                    continue
                if account.health_status == "online":
                    continue
                try:
                    await account_manager.health_check(account.account_id)
                except Exception:
                    # 探测失败保持原状态，不影响整体列表返回
                    pass
            accounts = await account_manager.get_accounts(user_id, is_active=False)

        now = datetime.now()
        return [await self._serialize_account(acc, now) for acc in accounts]

    async def sync_resources(
        self,
        account_id: str,
        user_id: int,
        background_tasks: BackgroundTasks,
        wait: bool = False,
    ) -> Dict[str, Any]:
        await check_account_permission(account_id, user_id)
        resource_manager = get_resource_manager()

        if wait:
            result = await resource_manager.full_sync(account_id)
            if result.error:
                raise HTTPException(status_code=400, detail=f"资源同步失败: {result.error}")
            if result.synced == 0 and result.failed > 0:
                raise HTTPException(status_code=400, detail=f"资源同步失败: 全部 {result.failed} 项同步失败")

            message = "资源同步完成"
            if result.failed > 0:
                message = f"资源同步部分成功：失败 {result.failed} 条"
            return {
                "message": message,
                "data": {
                    "synced": result.synced,
                    "new": result.new,
                    "updated": result.updated,
                    "deleted": result.deleted,
                    "failed": result.failed,
                    "error": result.error or None,
                },
            }

        async def run_sync() -> None:
            from loguru import logger

            try:
                await resource_manager.full_sync(account_id)
            except Exception as exc:
                logger.error(f"资源同步失败: {exc}")

        background_tasks.add_task(run_sync)
        return {"message": "资源同步已启动，请稍后查看结果"}

    async def sync_all_resources(
        self,
        user_id: int,
        background_tasks: Optional[BackgroundTasks] = None,
        wait: bool = False,
    ) -> Dict[str, Any]:
        if int(user_id) in _SYNCING_USERS:
            return {"message": "资源同步已在进行中，请稍后查看结果", "already_running": True}

        async def run_sync_all() -> Dict[str, Any]:
            _SYNCING_USERS.add(int(user_id))
            try:
                account_manager = get_account_manager()
                resource_manager = get_resource_manager()
                accounts = await account_manager.get_accounts(user_id, is_active=True)

                total_new = 0
                total_updated = 0
                total_failed = 0
                synced_accounts = 0

                for account in accounts:
                    try:
                        result = await resource_manager.full_sync(account.account_id)
                        total_new += int(result.new or 0)
                        total_updated += int(result.updated or 0)
                        total_failed += int(result.failed or 0)
                        synced_accounts += 1
                    except Exception:
                        total_failed += 1

                return {
                    "synced_accounts": synced_accounts,
                    "new": total_new,
                    "updated": total_updated,
                    "failed": total_failed,
                }
            finally:
                _SYNCING_USERS.discard(int(user_id))

        if wait:
            data = await run_sync_all()
            return {"message": "账号资源同步完成", "data": data, "already_running": False}

        if background_tasks is not None:
            background_tasks.add_task(run_sync_all)
        else:
            asyncio.create_task(run_sync_all())
        return {"message": "账号资源同步已在后台启动", "already_running": False}

    async def list_resources(
        self,
        account_id: str,
        user_id: int,
        peer_type: Optional[str] = None,
        is_active: bool = True,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        await check_account_permission(account_id, user_id)
        resource_manager = get_resource_manager()

        if search:
            resources = await resource_manager.search_resources(account_id, search)
        else:
            resources = await resource_manager.get_resources(account_id, peer_type=peer_type, is_active=is_active)

        return [
            {
                "resource_id": r.resource_id,
                "peer_id": r.peer_id,
                "peer_type": r.peer_type,
                "access_hash": r.access_hash,
                "title": ((r.title or "").strip() or (f"@{r.username}" if r.username else f"{r.peer_type}:{r.peer_id}")),
                "username": r.username,
                "description": r.description,
                "is_muted": r.is_muted,
                "is_verified": r.is_verified,
                "participants_count": r.participants_count,
                "is_active": r.is_active,
                "last_sync_at": r.last_sync_at.isoformat() if r.last_sync_at else None,
            }
            for r in resources
        ]

    async def set_account_enabled(self, account_id: str, user_id: int, enabled: bool) -> None:
        await check_account_permission(account_id, user_id)
        account_manager = get_account_manager()
        await account_manager.update_account(account_id, is_active=enabled)

    async def delete_account(self, account_id: str, user_id: int) -> None:
        await check_account_permission(account_id, user_id)
        account_manager = get_account_manager()
        try:
            await account_manager.delete_account(account_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def bind_slot(self, account_id: str, user_id: int, slot_id: str) -> Dict[str, Any]:
        await check_account_permission(account_id, user_id)
        if not slot_id:
            raise HTTPException(status_code=400, detail="缺少套餐位 ID")
        slot = await bind_slot_to_account(user_id=int(user_id), slot_id=str(slot_id), account_id=str(account_id))
        auth_summary = await get_account_authorization_summary(account_id)
        return {
            "slot_id": slot.slot_id,
            "account_id": slot.current_account_id,
            "status": slot.status,
            "end_at": slot.end_at.isoformat() if slot.end_at else None,
            "license_status": auth_summary.license_status,
            "can_create_tasks": auth_summary.can_create_tasks,
        }

    async def renew_account_slot(self, account_id: str, user_id: int, card_code: str) -> Dict[str, Any]:
        await check_account_permission(account_id, user_id)
        if not card_code:
            raise HTTPException(status_code=400, detail="缺少卡密")
        async with get_async_session() as session:
            slot, _card = await activate_card_for_user(
                user_id=int(user_id),
                card_code=card_code,
                account_id=str(account_id),
                session=session,
            )
            auth_summary = await get_account_authorization_summary(account_id, session=session)
            await session.commit()
        return {
            "slot_id": slot.slot_id,
            "account_id": slot.current_account_id,
            "status": slot.status,
            "end_at": slot.end_at.isoformat() if slot.end_at else None,
            "license_status": auth_summary.license_status,
            "can_create_tasks": auth_summary.can_create_tasks,
            "license_key_count": auth_summary.license_key_count,
        }

    async def _serialize_account(self, account: Any, now: datetime) -> Dict[str, Any]:
        auth_summary = await get_account_authorization_summary(account.account_id)

        return {
            "account_id": account.account_id,
            "username": account.username,
            "first_name": account.first_name,
            "phone": account.phone,
            "developer_app_id": account.developer_app_id,
            "is_active": account.is_active,
            "is_banned": account.is_banned,
            "health_status": account.health_status,
            "developer_app_version": account.developer_app_version,
            "reauth_required": account.reauth_required,
            "reauth_reason": account.reauth_reason,
            "reauth_required_at": account.reauth_required_at.isoformat() if account.reauth_required_at else None,
            "is_flooding": account.is_flooding,
            "flood_until": account.flood_until.isoformat() if account.flood_until else None,
            "messages_sent": account.messages_sent,
            "last_used_at": account.last_used_at.isoformat() if account.last_used_at else None,
            "created_at": account.created_at.isoformat() if account.created_at else None,
            "license_status": auth_summary.license_status,
            "can_create_tasks": auth_summary.can_create_tasks,
            "license_end_at": auth_summary.license_end_at.isoformat() if auth_summary.license_end_at else None,
            "license_key_count": auth_summary.license_key_count,
            "slot_id": auth_summary.slot_id,
            "has_active_slot": auth_summary.can_create_tasks,
            "slot_end_at": auth_summary.license_end_at.isoformat() if auth_summary.license_end_at else None,
            "slot_grant_source": auth_summary.slot_grant_source,
            "slot_grant_source_label": (
                "Bot 首绑试用" if auth_summary.slot_grant_source == "bot_trial" else ("卡密激活" if auth_summary.slot_id else None)
            ),
            "slot_remaining_days": (
                max(0, int((auth_summary.license_end_at - now).total_seconds() // 86400))
                if auth_summary.license_end_at
                else None
            ),
            "can_renew_slot": auth_summary.slot_id is not None,
        }


_account_service: Optional[AccountService] = None


def get_account_service() -> AccountService:
    """Get singleton account service instance."""
    global _account_service
    if _account_service is None:
        _account_service = AccountService()
    return _account_service
