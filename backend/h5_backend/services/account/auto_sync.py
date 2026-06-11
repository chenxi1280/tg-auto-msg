"""Runtime queue for serialized Telegram account synchronization."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

from loguru import logger
from sqlalchemy import func, or_, select

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account, HealthStatus, Resource
from backend.bot.account.reauth import is_reauth_required_account

SYNC_TRIGGER_LOGIN_SUCCESS = "login_success"
SYNC_TRIGGER_AUTO_TIMER = "auto_timer"
SYNC_TRIGGER_MANUAL = "manual"
AUTO_TIMER_RESOURCE_STALE_SECONDS = 24 * 60 * 60


def should_enqueue_auto_timer_sync(
    account: Any,
    *,
    latest_resource_sync_at: Optional[datetime],
    now: datetime,
) -> bool:
    if not bool(getattr(account, "is_active", False)):
        return False
    if bool(getattr(account, "is_banned", False)):
        return False
    if bool(getattr(account, "reauth_required", False)):
        return False
    if str(getattr(account, "health_status", "")) != HealthStatus.ONLINE.value:
        return False
    if latest_resource_sync_at is None:
        return True
    stale_after = timedelta(seconds=AUTO_TIMER_RESOURCE_STALE_SECONDS)
    return latest_resource_sync_at <= now - stale_after


class AccountAutoSyncRuntime:
    INTERVAL_SECONDS = 60 * 60
    ACCOUNT_SYNC_TIMEOUT_SECONDS = 6 * 60

    def __init__(self) -> None:
        self._running = False
        self._queue: asyncio.Queue[tuple[str, int, str]] = asyncio.Queue()
        self._queued_account_ids: set[str] = set()
        self._running_account_ids: set[str] = set()
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

        await self._enqueue_loaded_account(
            account_id=normalized_account_id,
            user_id=normalized_user_id,
            trigger_source=trigger_source,
        )
        logger.info(
            "account sync enqueued: account_id={}, user_id={}, trigger_source={}, queue_size={}",
            normalized_account_id,
            normalized_user_id,
            trigger_source,
            self._queue.qsize(),
        )
        return {"status": "enqueued", "account_id": normalized_account_id, "user_id": normalized_user_id}

    async def run_once(self) -> None:
        rows = await self.load_auto_timer_candidates()

        if not rows:
            logger.info("account sync scan queued: total_accounts=0, enqueued=0, deduped=0, queue_size={}", self._queue.qsize())
            return

        enqueued = 0
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
            else:
                deduped += 1

        logger.info(
            "account sync scan queued: total_accounts={}, enqueued={}, deduped={}, queue_size={}",
            len(rows),
            enqueued,
            deduped,
            self._queue.qsize(),
        )

    async def load_auto_timer_candidates(self) -> list[Any]:
        cutoff = datetime.now() - timedelta(seconds=AUTO_TIMER_RESOURCE_STALE_SECONDS)
        latest_sync = (
            select(
                Resource.account_id,
                func.max(Resource.last_sync_at).label("latest_resource_sync_at"),
            )
            .where(Resource.is_active.is_(True))
            .group_by(Resource.account_id)
            .subquery()
        )
        async with get_async_session() as session:
            result = await session.execute(
                select(Account.account_id, Account.user_id)
                .outerjoin(latest_sync, latest_sync.c.account_id == Account.account_id)
                .where(Account.is_active.is_(True))
                .where(Account.is_banned.is_(False))
                .where(Account.reauth_required.is_(False))
                .where(Account.health_status == HealthStatus.ONLINE.value)
                .where(
                    or_(
                        latest_sync.c.latest_resource_sync_at.is_(None),
                        latest_sync.c.latest_resource_sync_at <= cutoff,
                    )
                )
                .order_by(
                    latest_sync.c.latest_resource_sync_at.asc().nullsfirst(),
                    Account.updated_at.asc(),
                    Account.account_id.asc(),
                )
            )
            return result.all()

    async def _worker_loop(self) -> None:
        from backend.h5_backend.services.account.service import get_account_service

        service = get_account_service()
        while True:
            account_id, user_id, trigger_source = await self._queue.get()
            self._queued_account_ids.discard(account_id)
            self._running_account_ids.add(account_id)
            logger.info(
                "account sync started: account_id={}, user_id={}, trigger_source={}, queue_size={}",
                account_id,
                user_id,
                trigger_source,
                self._queue.qsize(),
            )
            try:
                await self._execute_account_sync(
                    service,
                    account_id=account_id,
                    user_id=user_id,
                    trigger_source=trigger_source,
                )
            finally:
                self._running_account_ids.discard(account_id)
                self._queue.task_done()

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
                "account sync enqueue skipped: account_id={}, user_id={}, trigger_source={}, reason=skipped_reauth_required",
                account_id,
                user_id,
                trigger_source,
            )
            return {"status": "skipped_reauth_required", "account_id": account_id, "user_id": user_id}
        if account_id in self._running_account_ids:
            return self._dedupe_result(status="running", account_id=account_id, user_id=user_id, trigger_source=trigger_source)
        if account_id in self._queued_account_ids:
            return self._dedupe_result(status="queued", account_id=account_id, user_id=user_id, trigger_source=trigger_source)
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
            "account sync enqueue deduped: account_id={}, user_id={}, trigger_source={}, dedupe={}, queue_size={}",
            account_id,
            user_id,
            trigger_source,
            status,
            self._queue.qsize(),
        )
        return {"status": status, "account_id": account_id, "user_id": user_id}

    async def _enqueue_loaded_account(self, *, account_id: str, user_id: int, trigger_source: str) -> None:
        self._queued_account_ids.add(account_id)
        await self._queue.put((account_id, user_id, trigger_source))

    async def _execute_account_sync(
        self,
        service: Any,
        *,
        account_id: str,
        user_id: int,
        trigger_source: str,
    ) -> None:
        try:
            result = await asyncio.wait_for(
                service.sync_account_snapshot(account_id, trigger_source=trigger_source),
                timeout=self.ACCOUNT_SYNC_TIMEOUT_SECONDS,
            )
            self._log_account_sync_finished(
                result,
                account_id=account_id,
                user_id=user_id,
                trigger_source=trigger_source,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            await self._handle_account_sync_timeout(
                account_id=account_id,
                user_id=user_id,
                trigger_source=trigger_source,
            )
        except Exception as exc:
            logger.exception(
                "account sync failed: account_id={}, user_id={}, trigger_source={}, error_type={}, error={!r}",
                account_id,
                user_id,
                trigger_source,
                type(exc).__name__,
                exc,
            )

    def _log_account_sync_finished(
        self,
        result: dict[str, Any],
        *,
        account_id: str,
        user_id: int,
        trigger_source: str,
    ) -> None:
        logger.info(
            "account sync finished: account_id={}, user_id={}, trigger_source={}, profile_sync_ok={}, resource_sync_ok={}, resource_synced_count={}, error={}",
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
    ) -> None:
        await self.mark_account_offline_after_timeout(
            account_id,
            trigger_source=trigger_source,
            timeout_seconds=self.ACCOUNT_SYNC_TIMEOUT_SECONDS,
        )
        logger.error(
            "account sync timed out: account_id={}, user_id={}, trigger_source={}, timeout_seconds={}",
            account_id,
            user_id,
            trigger_source,
            self.ACCOUNT_SYNC_TIMEOUT_SECONDS,
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

    async def mark_account_offline_after_timeout(
        self,
        account_id: str,
        *,
        trigger_source: str,
        timeout_seconds: float,
    ) -> None:
        async with get_async_session() as session:
            account = await session.get(Account, str(account_id))
            if account is None:
                return
            account.health_status = HealthStatus.OFFLINE.value
            await session.commit()
        logger.warning(
            "account sync timeout marked account offline: account_id={}, trigger_source={}, timeout_seconds={}",
            account_id,
            trigger_source,
            timeout_seconds,
        )


account_auto_sync_runtime = AccountAutoSyncRuntime()
