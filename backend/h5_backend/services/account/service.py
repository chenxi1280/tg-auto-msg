"""Account domain service for H5 API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, HTTPException

from backend.bot.account.manager import get_account_manager
from backend.bot.resources.manager import get_resource_manager
from backend.h5_backend.dependencies import check_account_permission


class AccountService:
    """Account and resource business service."""

    async def list_accounts(self, user_id: int) -> List[Dict[str, Any]]:
        account_manager = get_account_manager()
        accounts = await account_manager.get_accounts(user_id, is_active=False)
        now = datetime.now()
        return [self._serialize_account(acc, now) for acc in accounts]

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

    async def issue_bind_code(self, account_id: str, user_id: int, refresh: bool = True) -> Dict[str, Any]:
        await check_account_permission(account_id, user_id)
        account_manager = get_account_manager()
        try:
            issued = await account_manager.issue_bind_code(account_id, refresh=refresh)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if not issued:
            raise HTTPException(status_code=404, detail="账号不存在")

        expires_at = issued["expires_at"]
        ttl_seconds = issued.get("ttl_seconds")
        if ttl_seconds is None and expires_at:
            ttl_seconds = max(0, int((expires_at - datetime.now()).total_seconds()))
        return {
            "bind_code": issued["bind_code"],
            "expires_at": expires_at.isoformat() if expires_at else None,
            "ttl_seconds": ttl_seconds,
        }

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

    def _serialize_account(self, account: Any, now: datetime) -> Dict[str, Any]:
        bind_code_valid = (
            account.bind_code
            and account.bind_code_expires_at
            and account.bind_code_expires_at > now
        )

        return {
            "account_id": account.account_id,
            "username": account.username,
            "first_name": account.first_name,
            "phone": account.phone,
            "is_active": account.is_active,
            "is_banned": account.is_banned,
            "health_status": account.health_status,
            "is_flooding": account.is_flooding,
            "flood_until": account.flood_until.isoformat() if account.flood_until else None,
            "messages_sent": account.messages_sent,
            "last_used_at": account.last_used_at.isoformat() if account.last_used_at else None,
            "created_at": account.created_at.isoformat() if account.created_at else None,
            "bind_code": account.bind_code if bind_code_valid else None,
            "bind_code_expires_at": account.bind_code_expires_at.isoformat() if bind_code_valid else None,
        }


_account_service: Optional[AccountService] = None


def get_account_service() -> AccountService:
    """Get singleton account service instance."""
    global _account_service
    if _account_service is None:
        _account_service = AccountService()
    return _account_service
