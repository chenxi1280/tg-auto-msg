from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import asyncio
import unittest

from backend.database.schema.models import HealthStatus
from backend.h5_backend.services.account.auto_sync import (
    AccountAutoSyncRuntime,
    SYNC_TRIGGER_AUTO_TIMER,
    should_enqueue_auto_timer_sync,
)


class AccountAutoSyncTests(unittest.IsolatedAsyncioTestCase):
    def test_auto_timer_skips_fresh_offline_and_reauth_accounts(self):
        now = datetime(2026, 6, 11, 9, 0, 0)
        fresh_sync = now - timedelta(hours=1)

        fresh_online = SimpleNamespace(
            is_active=True,
            is_banned=False,
            reauth_required=False,
            health_status=HealthStatus.ONLINE.value,
        )
        offline = SimpleNamespace(
            is_active=True,
            is_banned=False,
            reauth_required=False,
            health_status=HealthStatus.OFFLINE.value,
        )
        reauth_required = SimpleNamespace(
            is_active=True,
            is_banned=False,
            reauth_required=True,
            health_status=HealthStatus.ONLINE.value,
        )

        self.assertFalse(
            should_enqueue_auto_timer_sync(
                fresh_online,
                latest_resource_sync_at=fresh_sync,
                now=now,
            )
        )
        self.assertFalse(
            should_enqueue_auto_timer_sync(
                offline,
                latest_resource_sync_at=None,
                now=now,
            )
        )
        self.assertFalse(
            should_enqueue_auto_timer_sync(
                reauth_required,
                latest_resource_sync_at=None,
                now=now,
            )
        )

    def test_auto_timer_enqueues_online_accounts_with_missing_or_stale_resources(self):
        now = datetime(2026, 6, 11, 9, 0, 0)
        stale_sync = now - timedelta(hours=25)
        account = SimpleNamespace(
            is_active=True,
            is_banned=False,
            reauth_required=False,
            health_status=HealthStatus.ONLINE.value,
        )

        self.assertTrue(
            should_enqueue_auto_timer_sync(
                account,
                latest_resource_sync_at=None,
                now=now,
            )
        )
        self.assertTrue(
            should_enqueue_auto_timer_sync(
                account,
                latest_resource_sync_at=stale_sync,
                now=now,
            )
        )

    async def test_run_once_uses_candidate_loader_instead_of_all_active_accounts(self):
        runtime = AccountAutoSyncRuntime()
        runtime.load_auto_timer_candidates = AsyncMock(
            return_value=[
                SimpleNamespace(account_id="acc-stale", user_id=1),
                SimpleNamespace(account_id="acc-missing", user_id=2),
            ]
        )

        with patch.object(runtime, "enqueue_account", AsyncMock(return_value={"status": "enqueued"})) as enqueue:
            await runtime.run_once()

        runtime.load_auto_timer_candidates.assert_awaited_once()
        self.assertEqual(enqueue.await_count, 2)
        enqueue.assert_any_await(
            "acc-stale",
            trigger_source=SYNC_TRIGGER_AUTO_TIMER,
            user_id=1,
            skip_reauth_required=True,
        )
        enqueue.assert_any_await(
            "acc-missing",
            trigger_source=SYNC_TRIGGER_AUTO_TIMER,
            user_id=2,
            skip_reauth_required=True,
        )

    async def test_worker_does_not_mark_account_offline_after_sync_timeout(self):
        runtime = AccountAutoSyncRuntime()
        runtime.AUTO_TIMER_ACCOUNT_SYNC_TIMEOUT_SECONDS = 0.01
        await runtime._queue.put(("acc-timeout", 1, SYNC_TRIGGER_AUTO_TIMER))

        class SlowAccountService:
            async def sync_account_snapshot(self, *_args, **_kwargs):
                await asyncio.sleep(1)

        with patch(
            "backend.h5_backend.services.account.service.get_account_service",
            return_value=SlowAccountService(),
        ), patch("backend.h5_backend.services.account.auto_sync.get_async_session") as session_factory:
            worker = asyncio.create_task(runtime._worker_loop())
            await asyncio.wait_for(runtime._queue.join(), timeout=1)
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker

        session_factory.assert_not_called()

    async def test_auto_timer_worker_uses_short_timeout_without_changing_manual_budget(self):
        runtime = AccountAutoSyncRuntime()
        runtime.ACCOUNT_SYNC_TIMEOUT_SECONDS = 0.5
        runtime.AUTO_TIMER_ACCOUNT_SYNC_TIMEOUT_SECONDS = 0.01
        await runtime._queue.put(("acc-timeout", 1, SYNC_TRIGGER_AUTO_TIMER))

        class SlowAccountService:
            async def sync_account_snapshot(self, *_args, **_kwargs):
                await asyncio.sleep(1)

        with patch(
            "backend.h5_backend.services.account.service.get_account_service",
            return_value=SlowAccountService(),
        ):
            worker = asyncio.create_task(runtime._worker_loop())
            await asyncio.wait_for(runtime._queue.join(), timeout=0.2)
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker
