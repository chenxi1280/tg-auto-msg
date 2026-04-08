"""Runtime queue for serialized Telegram account synchronization."""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account
from backend.bot.account.reauth import is_reauth_required_account

SYNC_TRIGGER_LOGIN_SUCCESS = "login_success"
SYNC_TRIGGER_AUTO_TIMER = "auto_timer"
SYNC_TRIGGER_MANUAL = "manual"


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
            logger.warning(
                "account sync enqueue skipped: account_id={}, user_id={}, trigger_source={}, reason=missing_or_inactive",
                account_id,
                user_id,
                trigger_source,
            )
            return {"status": "missing", "account_id": account_id, "user_id": user_id}

        normalized_account_id = str(account.account_id)
        normalized_user_id = int(account.user_id)
        if skip_reauth_required and is_reauth_required_account(account):
            logger.info(
                "account sync enqueue skipped: account_id={}, user_id={}, trigger_source={}, reason=skipped_reauth_required",
                normalized_account_id,
                normalized_user_id,
                trigger_source,
            )
            return {"status": "skipped_reauth_required", "account_id": normalized_account_id, "user_id": normalized_user_id}
        if normalized_account_id in self._running_account_ids:
            logger.info(
                "account sync enqueue deduped: account_id={}, user_id={}, trigger_source={}, dedupe=running, queue_size={}",
                normalized_account_id,
                normalized_user_id,
                trigger_source,
                self._queue.qsize(),
            )
            return {"status": "running", "account_id": normalized_account_id, "user_id": normalized_user_id}
        if normalized_account_id in self._queued_account_ids:
            logger.info(
                "account sync enqueue deduped: account_id={}, user_id={}, trigger_source={}, dedupe=queued, queue_size={}",
                normalized_account_id,
                normalized_user_id,
                trigger_source,
                self._queue.qsize(),
            )
            return {"status": "queued", "account_id": normalized_account_id, "user_id": normalized_user_id}

        self._queued_account_ids.add(normalized_account_id)
        await self._queue.put((normalized_account_id, normalized_user_id, trigger_source))
        logger.info(
            "account sync enqueued: account_id={}, user_id={}, trigger_source={}, queue_size={}",
            normalized_account_id,
            normalized_user_id,
            trigger_source,
            self._queue.qsize(),
        )
        return {"status": "enqueued", "account_id": normalized_account_id, "user_id": normalized_user_id}

    async def run_once(self) -> None:
        async with get_async_session() as session:
            result = await session.execute(
                select(Account.account_id, Account.user_id)
                .where(Account.is_active.is_(True))
                .order_by(Account.updated_at.desc(), Account.created_at.desc(), Account.account_id.asc())
            )
            rows = result.all()

        if not rows:
            return

        enqueued = 0
        deduped = 0
        for account_id, user_id in rows:
            queue_result = await self.enqueue_account(
                str(account_id),
                trigger_source=SYNC_TRIGGER_AUTO_TIMER,
                user_id=int(user_id),
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
                result = await asyncio.wait_for(
                    service.sync_account_snapshot(
                        account_id,
                        trigger_source=trigger_source,
                    ),
                    timeout=self.ACCOUNT_SYNC_TIMEOUT_SECONDS,
                )
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
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                logger.error(
                    "account sync timed out: account_id={}, user_id={}, trigger_source={}, timeout_seconds={}",
                    account_id,
                    user_id,
                    trigger_source,
                    self.ACCOUNT_SYNC_TIMEOUT_SECONDS,
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
            finally:
                self._running_account_ids.discard(account_id)
                self._queue.task_done()

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
