from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import asyncio
import unittest

from backend.database.schema.models import HealthStatus
from backend.h5_backend.services.account.auto_sync import (
    AccountAutoSyncRuntime,
    SYNC_TRIGGER_AUTO_TIMER,
    SYNC_TRIGGER_MANUAL,
    _build_auto_timer_candidate_statement,
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
            proxy_id=None,
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

    def test_auto_timer_skips_proxy_accounts_when_enabled(self):
        now = datetime(2026, 7, 8, 13, 50, 0)
        proxied_account = SimpleNamespace(
            is_active=True,
            is_banned=False,
            reauth_required=False,
            health_status=HealthStatus.ONLINE.value,
            proxy_id=1,
        )

        self.assertFalse(
            should_enqueue_auto_timer_sync(
                proxied_account,
                latest_resource_sync_at=None,
                now=now,
                skip_proxy_accounts=True,
            )
        )
        self.assertTrue(
            should_enqueue_auto_timer_sync(
                proxied_account,
                latest_resource_sync_at=None,
                now=now,
                skip_proxy_accounts=False,
            )
        )

    def test_auto_timer_includes_proxy_accounts_by_default(self):
        account = SimpleNamespace(
            is_active=True,
            is_banned=False,
            reauth_required=False,
            health_status=HealthStatus.ONLINE.value,
            proxy_id=1,
        )

        self.assertTrue(
            should_enqueue_auto_timer_sync(
                account,
                latest_resource_sync_at=None,
                now=datetime(2026, 8, 10, 12, 0, 0),
            )
        )

    def test_auto_timer_defaults_to_all_accounts_and_includes_proxy_accounts(self):
        runtime = AccountAutoSyncRuntime()

        self.assertEqual(runtime.AUTO_TIMER_MAX_CANDIDATES_PER_RUN, 0)
        self.assertFalse(runtime.AUTO_TIMER_SKIP_PROXY_ACCOUNTS)

    async def test_run_once_uses_candidate_loader_instead_of_all_active_accounts(self):
        runtime = AccountAutoSyncRuntime()
        runtime.AUTO_TIMER_MAX_CANDIDATES_PER_RUN = 0
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

    async def test_run_once_limits_auto_timer_candidates_per_scan(self):
        runtime = AccountAutoSyncRuntime()
        runtime.AUTO_TIMER_MAX_CANDIDATES_PER_RUN = 1
        runtime.load_auto_timer_candidates = AsyncMock(
            return_value=[
                SimpleNamespace(account_id="acc-1", user_id=1),
                SimpleNamespace(account_id="acc-2", user_id=2),
            ]
        )

        with patch.object(runtime, "enqueue_account", AsyncMock(return_value={"status": "enqueued"})) as enqueue:
            await runtime.run_once()

        self.assertEqual(enqueue.await_count, 1)
        enqueue.assert_awaited_once_with(
            "acc-1",
            trigger_source=SYNC_TRIGGER_AUTO_TIMER,
            user_id=1,
            skip_reauth_required=True,
        )

    def test_auto_timer_candidate_query_orders_by_oldest_resource_snapshot(self):
        cutoff = datetime(2026, 7, 8, 22, 0, 0)

        stmt = _build_auto_timer_candidate_statement(
            cutoff=cutoff,
            skip_proxy_accounts=True,
            max_candidates=1,
        )
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))

        self.assertIn(
            "ORDER BY anon_1.latest_resource_sync_at ASC NULLS FIRST, accounts.account_id ASC",
            compiled,
        )
        self.assertNotIn("ORDER BY accounts.updated_at", compiled)

    async def test_worker_does_not_mark_account_offline_after_sync_timeout(self):
        runtime = AccountAutoSyncRuntime()
        runtime.AUTO_TIMER_ACCOUNT_SYNC_TIMEOUT_SECONDS = 0.01
        await runtime._sync_queue.enqueue(
            account_id="acc-timeout",
            user_id=1,
            trigger_source=SYNC_TRIGGER_AUTO_TIMER,
        )

        class SlowAccountService:
            async def sync_account_snapshot(self, *_args, **_kwargs):
                await asyncio.sleep(1)

        with patch(
            "backend.h5_backend.services.account.service.get_account_service",
            return_value=SlowAccountService(),
        ), patch("backend.h5_backend.services.account.auto_sync.get_async_session") as session_factory:
            worker = asyncio.create_task(runtime._worker_loop())
            await asyncio.wait_for(runtime.wait_until_idle(), timeout=1)
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker

        session_factory.assert_not_called()

    async def test_auto_timer_timeout_is_not_logged_as_service_error(self):
        runtime = AccountAutoSyncRuntime()

        with patch("backend.h5_backend.services.account.auto_sync.logger") as logger:
            await runtime._handle_account_sync_timeout(
                account_id="acc-timeout",
                user_id=1,
                trigger_source=SYNC_TRIGGER_AUTO_TIMER,
                timeout_seconds=45,
            )

        logger.warning.assert_called_once()
        logger.error.assert_not_called()

    async def test_manual_timeout_remains_logged_as_service_error(self):
        runtime = AccountAutoSyncRuntime()

        with patch("backend.h5_backend.services.account.auto_sync.logger") as logger:
            await runtime._handle_account_sync_timeout(
                account_id="acc-timeout",
                user_id=1,
                trigger_source=SYNC_TRIGGER_MANUAL,
                timeout_seconds=360,
            )

        logger.error.assert_called_once()
        logger.warning.assert_not_called()

    async def test_auto_timer_worker_uses_short_timeout_without_changing_manual_budget(self):
        runtime = AccountAutoSyncRuntime()
        runtime.ACCOUNT_SYNC_TIMEOUT_SECONDS = 0.5
        runtime.AUTO_TIMER_ACCOUNT_SYNC_TIMEOUT_SECONDS = 0.01
        await runtime._sync_queue.enqueue(
            account_id="acc-timeout",
            user_id=1,
            trigger_source=SYNC_TRIGGER_AUTO_TIMER,
        )

        class SlowAccountService:
            async def sync_account_snapshot(self, *_args, **_kwargs):
                await asyncio.sleep(1)

        with patch(
            "backend.h5_backend.services.account.service.get_account_service",
            return_value=SlowAccountService(),
        ):
            worker = asyncio.create_task(runtime._worker_loop())
            await asyncio.wait_for(runtime.wait_until_idle(), timeout=0.2)
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker
