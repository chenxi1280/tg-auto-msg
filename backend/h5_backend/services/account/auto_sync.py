"""Runtime queue for serialized Telegram account synchronization."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from typing import Any, Optional

from loguru import logger
from sqlalchemy import func, or_, select

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account, HealthStatus, Resource
from backend.bot.account.reauth import is_reauth_required_account
from backend.h5_backend.services.account.sync_queue import (
    SYNC_TRIGGER_AUTO_TIMER,
    SYNC_TRIGGER_LOGIN_SUCCESS,
    SYNC_TRIGGER_MANUAL,
    AccountSyncQueue,
    AccountSyncWorkItem,
)

AUTO_TIMER_RESOURCE_STALE_SECONDS = 24 * 60 * 60
AUTO_TIMER_UNLIMITED_CANDIDATES = 0


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def should_enqueue_auto_timer_sync(
    account: Any,
    *,
    latest_resource_sync_at: Optional[datetime],
    now: datetime,
    skip_proxy_accounts: bool = False,
) -> bool:
    if not bool(getattr(account, "is_active", False)):
        return False
    if bool(getattr(account, "is_banned", False)):
        return False
    if bool(getattr(account, "reauth_required", False)):
        return False
    if str(getattr(account, "health_status", "")) != HealthStatus.ONLINE.value:
        return False
    if skip_proxy_accounts and getattr(account, "proxy_id", None) is not None:
        return False
    if latest_resource_sync_at is None:
        return True
    stale_after = timedelta(seconds=AUTO_TIMER_RESOURCE_STALE_SECONDS)
    return latest_resource_sync_at <= now - stale_after


def _latest_resource_sync_subquery() -> Any:
    return (
        select(
            Resource.account_id,
            func.max(Resource.last_sync_at).label("latest_resource_sync_at"),
        )
        .where(Resource.is_active.is_(True))
        .group_by(Resource.account_id)
        .subquery()
    )


def _build_auto_timer_candidate_statement(
    *,
    cutoff: datetime,
    skip_proxy_accounts: bool,
    max_candidates: int,
) -> Any:
    latest_sync = _latest_resource_sync_subquery()
    stmt = (
        select(Account.account_id, Account.user_id)
        .outerjoin(latest_sync, latest_sync.c.account_id == Account.account_id)
        .where(Account.is_active.is_(True))
        .where(Account.is_banned.is_(False))
        .where(Account.reauth_required.is_(False))
        .where(Account.health_status == HealthStatus.ONLINE.value)
        .where(or_(latest_sync.c.latest_resource_sync_at.is_(None), latest_sync.c.latest_resource_sync_at <= cutoff))
        .order_by(latest_sync.c.latest_resource_sync_at.asc().nullsfirst(), Account.account_id.asc())
    )
    if skip_proxy_accounts:
        stmt = stmt.where(Account.proxy_id.is_(None))
    if max_candidates > AUTO_TIMER_UNLIMITED_CANDIDATES:
        stmt = stmt.limit(max_candidates)
    return stmt


class AccountAutoSyncRuntime:
    INTERVAL_SECONDS = 60 * 60
    ACCOUNT_SYNC_TIMEOUT_SECONDS = 6 * 60
    AUTO_TIMER_ACCOUNT_SYNC_TIMEOUT_SECONDS = 45
    AUTO_TIMER_MAX_CANDIDATES_PER_RUN = int(os.getenv("ACCOUNT_AUTO_SYNC_MAX_CANDIDATES_PER_RUN", "0"))
    AUTO_TIMER_SKIP_PROXY_ACCOUNTS = _env_bool("ACCOUNT_AUTO_SYNC_SKIP_PROXY_ACCOUNTS", False)

    def __init__(self) -> None:
        self._running = False
        self._sync_queue = AccountSyncQueue()
        self._worker_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._running = True
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("✅ 账号自动同步队列已启动（扫描间隔: {} 秒）", self.INTERVAL_SECONDS)
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("账号自动同步扫描异常: {}: {!r}", type(exc).__name__, exc)
            await asyncio.sleep(self.INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._running = False
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def enqueue_account(
        self,
        account_id: str,
        *,
        trigger_source: str,
        user_id: Optional[int] = None,
        skip_reauth_required: bool = False,
    ) -> dict[str, Any]:
        account = await self._load_active_account(account_id, user_id=user_id)
        if account is None:
            return self._missing_account_result(
                account_id=account_id,
                user_id=user_id,
                trigger_source=trigger_source,
            )

        normalized_account_id = str(account.account_id)
        normalized_user_id = int(account.user_id)
        skipped = self._skip_loaded_account(
            account,
            account_id=normalized_account_id,
            user_id=normalized_user_id,
            trigger_source=trigger_source,
            skip_reauth_required=skip_reauth_required,
        )
        if skipped is not None:
            return skipped

        status = await self._sync_queue.enqueue(
            account_id=normalized_account_id,
            user_id=normalized_user_id,
            trigger_source=trigger_source,
        )
        if status in {"queued", "running"}:
            return self._dedupe_result(
                status=status,
                account_id=normalized_account_id,
                user_id=normalized_user_id,
                trigger_source=trigger_source,
            )
        logger.info(
            "account sync enqueued: account_id={}, user_id={}, trigger_source={}, status={}, queue_size={}",
            normalized_account_id,
            normalized_user_id,
            trigger_source,
            status,
            self._sync_queue.pending_count(),
        )
        return {"status": status, "account_id": normalized_account_id, "user_id": normalized_user_id}

    async def run_once(self) -> None:
        loaded_rows = await self.load_auto_timer_candidates()
        rows = self._limit_auto_timer_candidates(loaded_rows)

        if not rows:
            logger.info(
                "account sync scan queued: total_accounts={}, selected_accounts=0, "
                "enqueued=0, deduped=0, queue_size={}",
                len(loaded_rows),
                self._sync_queue.pending_count(),
            )
            return

        enqueued = 0
        reprioritized = 0
        deduped = 0
        for row in rows:
            account_id = str(row.account_id)
            user_id = int(row.user_id)
            queue_result = await self.enqueue_account(
                account_id,
                trigger_source=SYNC_TRIGGER_AUTO_TIMER,
                user_id=user_id,
                skip_reauth_required=True,
            )
            if queue_result["status"] == "enqueued":
                enqueued += 1
            elif queue_result["status"] == "reprioritized":
                reprioritized += 1
            else:
                deduped += 1

        logger.info(
            "account sync scan queued: selected_accounts={}, enqueued={}, reprioritized={}, deduped={}, queue_size={}",
            len(loaded_rows),
            enqueued,
            reprioritized,
            deduped,
            self._sync_queue.pending_count(),
        )

    async def load_auto_timer_candidates(self) -> list[Any]:
        cutoff = datetime.now() - timedelta(seconds=AUTO_TIMER_RESOURCE_STALE_SECONDS)
        max_candidates = int(self.AUTO_TIMER_MAX_CANDIDATES_PER_RUN)
        stmt = _build_auto_timer_candidate_statement(
            cutoff=cutoff,
            skip_proxy_accounts=bool(self.AUTO_TIMER_SKIP_PROXY_ACCOUNTS),
            max_candidates=max_candidates,
        )

        async with get_async_session() as session:
            result = await session.execute(stmt)
            return result.all()

    def _limit_auto_timer_candidates(self, rows: list[Any]) -> list[Any]:
        max_candidates = int(self.AUTO_TIMER_MAX_CANDIDATES_PER_RUN)
        if max_candidates == AUTO_TIMER_UNLIMITED_CANDIDATES:
            return list(rows)
        if max_candidates < AUTO_TIMER_UNLIMITED_CANDIDATES:
            raise ValueError("ACCOUNT_AUTO_SYNC_MAX_CANDIDATES_PER_RUN must be >= 0")
        return list(rows)[:max_candidates]

    async def _worker_loop(self) -> None:
        from backend.h5_backend.services.account.service import get_account_service

        service = get_account_service()
        while True:
            item = await self._sync_queue.get()
            logger.info(
                "account sync started: account_id={}, user_id={}, trigger_source={}, queue_size={}",
                item.account_id,
                item.user_id,
                item.trigger_source,
                self._sync_queue.pending_count(),
            )
            try:
                result = await self._execute_account_sync(
                    service,
                    account_id=item.account_id,
                    user_id=item.user_id,
                    trigger_source=item.trigger_source,
                )
            except asyncio.CancelledError:
                self._sync_queue.complete(item, self._cancelled_result(item))
                raise
            self._sync_queue.complete(item, result)

    def _missing_account_result(
        self,
        *,
        account_id: str,
        user_id: Optional[int],
        trigger_source: str,
    ) -> dict[str, Any]:
        logger.warning(
            "account sync enqueue skipped: account_id={}, user_id={}, trigger_source={}, reason=missing_or_inactive",
            account_id,
            user_id,
            trigger_source,
        )
        return {"status": "missing", "account_id": account_id, "user_id": user_id}

    def _skip_loaded_account(
        self,
        account: Account,
        *,
        account_id: str,
        user_id: int,
        trigger_source: str,
        skip_reauth_required: bool,
    ) -> Optional[dict[str, Any]]:
        if skip_reauth_required and is_reauth_required_account(account):
            logger.info(
                "account sync enqueue skipped: account_id={}, user_id={}, "
                "trigger_source={}, reason=skipped_reauth_required",
                account_id,
                user_id,
                trigger_source,
            )
            return {"status": "skipped_reauth_required", "account_id": account_id, "user_id": user_id}
        return None

    def _dedupe_result(
        self,
        *,
        status: str,
        account_id: str,
        user_id: int,
        trigger_source: str,
    ) -> dict[str, Any]:
        logger.info(
            "account sync enqueue deduped: account_id={}, user_id={}, "
            "trigger_source={}, dedupe={}, queue_size={}",
            account_id,
            user_id,
            trigger_source,
            status,
            self._sync_queue.pending_count(),
        )
        return {"status": status, "account_id": account_id, "user_id": user_id}

    async def _execute_account_sync(
        self,
        service: Any,
        *,
        account_id: str,
        user_id: int,
        trigger_source: str,
    ) -> dict[str, Any]:
        timeout_seconds = self._sync_timeout_seconds(trigger_source)
        try:
            result = await asyncio.wait_for(
                service.sync_account_snapshot(account_id, trigger_source=trigger_source),
                timeout=timeout_seconds,
            )
            self._log_account_sync_finished(
                result,
                account_id=account_id,
                user_id=user_id,
                trigger_source=trigger_source,
            )
            return result
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            await self._handle_account_sync_timeout(
                account_id=account_id,
                user_id=user_id,
                trigger_source=trigger_source,
                timeout_seconds=timeout_seconds,
            )
            return self._failure_result(
                account_id=account_id,
                user_id=user_id,
                trigger_source=trigger_source,
                error=f"账号同步超时: {timeout_seconds:g}s",
            )
        except Exception as exc:
            return self._exception_result(
                account_id=account_id,
                user_id=user_id,
                trigger_source=trigger_source,
                exc=exc,
            )

    def _exception_result(
        self,
        *,
        account_id: str,
        user_id: int,
        trigger_source: str,
        exc: Exception,
    ) -> dict[str, Any]:
        logger.exception(
            "account sync failed: account_id={}, user_id={}, trigger_source={}, "
            "error_type={}, error={!r}",
            account_id,
            user_id,
            trigger_source,
            type(exc).__name__,
            exc,
        )
        return self._failure_result(
            account_id=account_id,
            user_id=user_id,
            trigger_source=trigger_source,
            error=f"账号同步失败: {type(exc).__name__}: {exc}",
        )

    async def wait_for_account(
        self,
        account_id: str,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        return await self._sync_queue.wait_for_result(
            str(account_id),
            timeout_seconds=timeout_seconds,
        )

    def get_account_status(self, account_id: str) -> dict[str, Any]:
        return self._sync_queue.get_status(str(account_id))

    async def wait_until_idle(self) -> None:
        await self._sync_queue.join()

    @staticmethod
    def _failure_result(
        *,
        account_id: str,
        user_id: int,
        trigger_source: str,
        error: str,
    ) -> dict[str, Any]:
        return {
            "account_id": account_id,
            "user_id": user_id,
            "trigger_source": trigger_source,
            "profile_sync_ok": False,
            "resource_sync_ok": False,
            "resource_synced_count": 0,
            "error": error,
        }

    def _cancelled_result(self, item: AccountSyncWorkItem) -> dict[str, Any]:
        return self._failure_result(
            account_id=item.account_id,
            user_id=item.user_id,
            trigger_source=item.trigger_source,
            error="账号同步 worker 已停止",
        )

    def _sync_timeout_seconds(self, trigger_source: str) -> float:
        if trigger_source == SYNC_TRIGGER_AUTO_TIMER:
            return float(self.AUTO_TIMER_ACCOUNT_SYNC_TIMEOUT_SECONDS)
        return float(self.ACCOUNT_SYNC_TIMEOUT_SECONDS)

    def _log_account_sync_finished(
        self,
        result: dict[str, Any],
        *,
        account_id: str,
        user_id: int,
        trigger_source: str,
    ) -> None:
        logger.info(
            "account sync finished: account_id={}, user_id={}, trigger_source={}, "
            "profile_sync_ok={}, resource_sync_ok={}, resource_synced_count={}, error={}",
            account_id,
            user_id,
            trigger_source,
            bool(result.get("profile_sync_ok")),
            bool(result.get("resource_sync_ok")),
            int(result.get("resource_synced_count") or 0),
            result.get("error"),
        )

    async def _handle_account_sync_timeout(
        self,
        *,
        account_id: str,
        user_id: int,
        trigger_source: str,
        timeout_seconds: float,
    ) -> None:
        if trigger_source == SYNC_TRIGGER_AUTO_TIMER:
            logger.warning(
                "auto account sync timed out without marking service unhealthy: "
                "account_id={}, user_id={}, trigger_source={}, timeout_seconds={}",
                account_id,
                user_id,
                trigger_source,
                timeout_seconds,
            )
            return
        logger.error(
            "account sync timed out: account_id={}, user_id={}, trigger_source={}, timeout_seconds={}",
            account_id,
            user_id,
            trigger_source,
            timeout_seconds,
        )

    async def _load_active_account(self, account_id: str, *, user_id: Optional[int] = None) -> Optional[Account]:
        async with get_async_session() as session:
            stmt = select(Account).where(
                Account.account_id == str(account_id),
                Account.is_active.is_(True),
            )
            if user_id is not None:
                stmt = stmt.where(Account.user_id == int(user_id))
            return (await session.execute(stmt.limit(1))).scalar_one_or_none()


account_auto_sync_runtime = AccountAutoSyncRuntime()
