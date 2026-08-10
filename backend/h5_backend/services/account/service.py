"""Account domain service for H5 API."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, HTTPException
from loguru import logger

from backend.bot.account.manager import get_account_manager
from backend.bot.resources.manager import get_resource_manager
from backend.bot.resources.sync_ops import diagnose_client_unavailable
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import HealthStatus
from backend.h5_backend.dependencies import check_account_permission
from backend.h5_backend.services.account.auto_sync import (
    SYNC_TRIGGER_AUTO_TIMER,
    SYNC_TRIGGER_MANUAL,
    account_auto_sync_runtime,
)
from backend.h5_backend.services.licensing.service import (
    activate_card_for_user,
    get_account_authorization_summary,
    get_authorization_overview,
)


class AccountService:
    """Account and resource business service."""
    PROFILE_SYNC_TIMEOUT_SECONDS = 30
    RESOURCE_SYNC_TIMEOUT_SECONDS = 5 * 60
    MANUAL_SYNC_WAIT_TIMEOUT_SECONDS = 4 * 60 + 30

    async def _mark_account_offline_for_sync_failure(
        self,
        account_manager,
        account_id: str,
        *,
        trigger_source: str,
        reason: str,
    ) -> None:
        if trigger_source == SYNC_TRIGGER_AUTO_TIMER:
            logger.warning(
                "auto account sync failed without changing send health: account_id={}, reason={}",
                account_id,
                reason,
            )
            return
        await account_manager.update_account(account_id, health_status=HealthStatus.OFFLINE.value)

    async def list_accounts(self, user_id: int, probe: bool = False) -> List[Dict[str, Any]]:
        account_manager = get_account_manager()
        # 先执行一次授权归一化，确保历史多账号数据被收口到当前唯一账号模型。
        await get_authorization_overview(user_id)
        accounts = await account_manager.get_accounts(user_id, is_active=True)

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
            accounts = await account_manager.get_accounts(user_id, is_active=True)

        now = datetime.now()
        return [await self._serialize_account(acc, now) for acc in accounts]

    async def sync_resources(
        self,
        account_id: str,
        user_id: int,
        background_tasks: BackgroundTasks,
        wait: bool = False,
    ) -> Dict[str, Any]:
        del background_tasks
        await check_account_permission(account_id, user_id)
        enqueue_result = await account_auto_sync_runtime.enqueue_account(
            account_id,
            trigger_source=SYNC_TRIGGER_MANUAL,
            user_id=int(user_id),
        )
        if enqueue_result["status"] == "missing":
            raise HTTPException(status_code=404, detail="账号不存在或未启用")
        if wait:
            return await self._wait_for_manual_sync(account_id)
        return self._manual_enqueue_response(enqueue_result["status"])

    async def _wait_for_manual_sync(self, account_id: str) -> Dict[str, Any]:
        try:
            result = await account_auto_sync_runtime.wait_for_account(
                account_id,
                timeout_seconds=self.MANUAL_SYNC_WAIT_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail="等待账号资源同步完成超时，后台任务未被取消",
            ) from exc
        if not bool(result.get("resource_sync_ok")):
            detail = str(result.get("error") or "账号资源同步失败")
            raise HTTPException(status_code=502, detail=detail)
        synced_count = int(result.get("resource_synced_count") or 0)
        return {
            "message": f"资源同步完成，共刷新 {synced_count} 条",
            "status": "completed",
            "already_running": False,
            "data": result,
        }

    async def get_sync_status(self, account_id: str, user_id: int) -> Dict[str, Any]:
        await check_account_permission(account_id, user_id)
        snapshot = account_auto_sync_runtime.get_account_status(account_id)
        status = str(snapshot["status"])
        response: Dict[str, Any] = {
            "status": status,
            "message": self._sync_status_message(status, snapshot.get("data")),
        }
        if "data" in snapshot:
            response["data"] = snapshot["data"]
        return response

    @staticmethod
    def _sync_status_message(status: str, data: Any) -> str:
        if status == "completed":
            synced_count = int((data or {}).get("resource_synced_count") or 0)
            return f"资源同步完成，共刷新 {synced_count} 条"
        messages = {
            "idle": "当前没有可查询的账号同步任务",
            "queued": "该账号正在等待同步",
            "running": "该账号正在同步中",
            "failed": str((data or {}).get("error") or "账号资源同步失败"),
        }
        if status not in messages:
            raise RuntimeError(f"unexpected account sync status: {status}")
        return messages[status]

    @staticmethod
    def _manual_enqueue_response(status: str) -> Dict[str, Any]:
        messages = {
            "enqueued": "该账号已加入同步队列",
            "reprioritized": "该账号已提升为优先同步",
            "queued": "该账号已在同步队列中",
            "running": "该账号正在同步中",
        }
        if status not in messages:
            raise RuntimeError(f"unexpected account sync queue status: {status}")
        return {
            "message": messages[status],
            "status": status,
            "already_running": status in {"queued", "running"},
        }

    async def sync_all_resources(
        self,
        user_id: int,
        background_tasks: Optional[BackgroundTasks] = None,
        wait: bool = False,
    ) -> Dict[str, Any]:
        del background_tasks, wait
        account_manager = get_account_manager()
        accounts = await account_manager.get_accounts(user_id, is_active=True)
        if not accounts:
            return {"message": "当前没有可同步的账号", "status": "completed", "already_running": False}

        status_counts: dict[str, int] = {}
        for account in accounts:
            enqueue_result = await account_auto_sync_runtime.enqueue_account(
                account.account_id,
                trigger_source=SYNC_TRIGGER_MANUAL,
                user_id=int(user_id),
            )
            status = str(enqueue_result["status"])
            status_counts[status] = status_counts.get(status, 0) + 1

        queued_accounts = status_counts.get("enqueued", 0)
        reprioritized_accounts = status_counts.get("reprioritized", 0)
        already_running_accounts = status_counts.get("queued", 0) + status_counts.get("running", 0)
        if queued_accounts == 0 and reprioritized_accounts == 0 and already_running_accounts > 0:
            return {
                "message": "账号正在同步中，请稍后查看结果",
                "status": "running",
                "already_running": True,
            }
        return {
            "message": (
                f"账号已加入同步队列：新增 {queued_accounts} 个，"
                f"提升优先级 {reprioritized_accounts} 个，"
                f"已在队列或同步中 {already_running_accounts} 个"
            ),
            "status": "queued",
            "already_running": False,
            "data": {
                "queued_accounts": queued_accounts,
                "reprioritized_accounts": reprioritized_accounts,
                "already_running_accounts": already_running_accounts,
                "total_accounts": len(accounts),
            },
        }

    async def sync_account_snapshot(
        self,
        account_id: str,
        *,
        trigger_source: str,
    ) -> Dict[str, Any]:
        account_manager = get_account_manager()
        resource_manager = get_resource_manager()
        account = await account_manager.get_account(account_id)
        if not account or not account.is_active:
            return {
                "account_id": account_id,
                "user_id": getattr(account, "user_id", None),
                "trigger_source": trigger_source,
                "profile_sync_ok": False,
                "resource_sync_ok": False,
                "resource_synced_count": 0,
                "error": "账号不存在或未启用",
            }

        profile_sync_ok = False
        resource_sync_ok = False
        resource_synced_count = 0
        error: Optional[str] = None

        client = await account_manager.get_client(account_id)
        if not client:
            error = await diagnose_client_unavailable(account_manager, account_id)
            await self._mark_account_offline_for_sync_failure(
                account_manager,
                account_id,
                trigger_source=trigger_source,
                reason=error,
            )
            return {
                "account_id": account_id,
                "user_id": int(account.user_id),
                "trigger_source": trigger_source,
                "profile_sync_ok": False,
                "resource_sync_ok": False,
                "resource_synced_count": 0,
                "error": error,
            }

        try:
            me = await asyncio.wait_for(
                client.get_me(),
                timeout=self.PROFILE_SYNC_TIMEOUT_SECONDS,
            )
            if me is not None:
                await account_manager.update_account(
                    account_id,
                    tg_user_id=int(me.id),
                    username=getattr(me, "username", None),
                    first_name=getattr(me, "first_name", None),
                    phone=getattr(me, "phone", None),
                    health_status=HealthStatus.ONLINE.value,
                )
                profile_sync_ok = True
        except TimeoutError:
            error = f"账号资料同步超时: {self.PROFILE_SYNC_TIMEOUT_SECONDS}s"
            logger.warning(
                "account profile sync timed out: account_id={}, user_id={}, trigger_source={}, timeout_seconds={}",
                account_id,
                int(account.user_id),
                trigger_source,
                self.PROFILE_SYNC_TIMEOUT_SECONDS,
            )
            await self._mark_account_offline_for_sync_failure(
                account_manager,
                account_id,
                trigger_source=trigger_source,
                reason=error,
            )
        except Exception as exc:
            error = f"账号资料同步失败: {type(exc).__name__}: {exc}"
            logger.warning(
                "account profile sync failed: account_id={}, user_id={}, trigger_source={}, error={}",
                account_id,
                int(account.user_id),
                trigger_source,
                exc,
            )
            await self._mark_account_offline_for_sync_failure(
                account_manager,
                account_id,
                trigger_source=trigger_source,
                reason=error,
            )

        if profile_sync_ok:
            try:
                result = await asyncio.wait_for(
                    resource_manager.full_sync(account_id),
                    timeout=self.RESOURCE_SYNC_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                error = f"资源同步超时: {self.RESOURCE_SYNC_TIMEOUT_SECONDS}s"
                logger.warning(
                    "account resource sync timed out: account_id={}, user_id={}, trigger_source={}, timeout_seconds={}",
                    account_id,
                    int(account.user_id),
                    trigger_source,
                    self.RESOURCE_SYNC_TIMEOUT_SECONDS,
                )
                return {
                    "account_id": account_id,
                    "user_id": int(account.user_id),
                    "trigger_source": trigger_source,
                    "profile_sync_ok": profile_sync_ok,
                    "resource_sync_ok": False,
                    "resource_synced_count": 0,
                    "error": error,
                }
            resource_synced_count = int(result.synced or 0)
            resource_sync_ok = not bool(result.error) and not (
                int(result.synced or 0) == 0 and int(result.failed or 0) > 0
            )
            if result.error:
                error = result.error
            elif int(result.synced or 0) == 0 and int(result.failed or 0) > 0:
                error = f"资源同步失败: 全部 {result.failed} 项同步失败"

        return {
            "account_id": account_id,
            "user_id": int(account.user_id),
            "trigger_source": trigger_source,
            "profile_sync_ok": profile_sync_ok,
            "resource_sync_ok": resource_sync_ok,
            "resource_synced_count": resource_synced_count,
            "error": error,
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

    async def renew_account_authorization(self, account_id: str, user_id: int, card_code: str) -> Dict[str, Any]:
        await check_account_permission(account_id, user_id)
        if not card_code:
            raise HTTPException(status_code=400, detail="缺少卡密")
        current_summary = await get_account_authorization_summary(account_id)
        if current_summary.authorization_id is None:
            raise HTTPException(status_code=400, detail="当前账号还没有可续费的授权，请先绑定 TG 账号触发 7 天试用或输入卡密开通当前授权")
        async with get_async_session() as session:
            authorization, _card = await activate_card_for_user(
                user_id=int(user_id),
                card_code=card_code,
                session=session,
            )
            auth_summary = await get_account_authorization_summary(account_id, session=session)
            await session.commit()
        return {
            "authorization_id": authorization.authorization_id,
            "account_id": authorization.current_account_id,
            "status": authorization.status,
            "end_at": authorization.end_at.isoformat() if authorization.end_at else None,
            "authorization_status": auth_summary.authorization_status,
            "can_create_tasks": auth_summary.can_create_tasks,
            "authorization_card_count": auth_summary.authorization_card_count,
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
            "authorization_status": auth_summary.authorization_status,
            "can_create_tasks": auth_summary.can_create_tasks,
            "authorization_end_at": auth_summary.authorization_end_at.isoformat() if auth_summary.authorization_end_at else None,
            "authorization_card_count": auth_summary.authorization_card_count,
            "authorization_id": auth_summary.authorization_id,
            "has_active_authorization": auth_summary.can_create_tasks,
            "authorization_grant_source": auth_summary.authorization_grant_source,
            "authorization_grant_source_label": (
                "首次绑定 TG 赠送试用" if auth_summary.authorization_grant_source == "bot_trial" else ("卡密续费" if auth_summary.authorization_id else None)
            ),
            "authorization_remaining_days": (
                max(0, int((auth_summary.authorization_end_at - now).total_seconds() // 86400))
                if auth_summary.authorization_end_at
                else None
            ),
            "can_renew_authorization": auth_summary.authorization_id is not None,
        }


_account_service: Optional[AccountService] = None


def get_account_service() -> AccountService:
    """Get singleton account service instance."""
    global _account_service
    if _account_service is None:
        _account_service = AccountService()
    return _account_service
