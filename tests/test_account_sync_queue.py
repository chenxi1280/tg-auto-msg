import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from backend.h5_backend.services.account.auto_sync import AccountAutoSyncRuntime
from backend.h5_backend.services.account.sync_queue import (
    SYNC_TRIGGER_AUTO_TIMER,
    SYNC_TRIGGER_MANUAL,
)


def _success_result(account_id: str) -> dict[str, object]:
    return {
        "account_id": account_id,
        "user_id": 1,
        "trigger_source": SYNC_TRIGGER_MANUAL,
        "profile_sync_ok": True,
        "resource_sync_ok": True,
        "resource_synced_count": 3,
        "error": None,
    }


class AccountSyncQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_tracks_queue_running_and_terminal_results(self):
        runtime = AccountAutoSyncRuntime()
        self.assertEqual(runtime.get_account_status("acc-1"), {"status": "idle"})

        await runtime._sync_queue.enqueue(
            account_id="acc-1",
            user_id=1,
            trigger_source=SYNC_TRIGGER_MANUAL,
        )
        self.assertEqual(runtime.get_account_status("acc-1"), {"status": "queued"})

        item = await runtime._sync_queue.get()
        self.assertEqual(runtime.get_account_status("acc-1"), {"status": "running"})

        completed = _success_result("acc-1")
        runtime._sync_queue.complete(item, completed)
        self.assertEqual(
            runtime.get_account_status("acc-1"),
            {"status": "completed", "data": completed},
        )

    async def test_status_exposes_failed_result(self):
        runtime = AccountAutoSyncRuntime()
        await runtime._sync_queue.enqueue(
            account_id="broken",
            user_id=1,
            trigger_source=SYNC_TRIGGER_MANUAL,
        )
        item = await runtime._sync_queue.get()
        failed = {**_success_result("broken"), "resource_sync_ok": False, "error": "boom"}
        runtime._sync_queue.complete(item, failed)

        self.assertEqual(
            runtime.get_account_status("broken"),
            {"status": "failed", "data": failed},
        )

    async def test_manual_reprioritizes_queued_automatic_account_without_duplicate_execution(self):
        runtime = AccountAutoSyncRuntime()
        await runtime._sync_queue.enqueue(
            account_id="auto-first",
            user_id=1,
            trigger_source=SYNC_TRIGGER_AUTO_TIMER,
        )
        await runtime._sync_queue.enqueue(
            account_id="manual-target",
            user_id=2,
            trigger_source=SYNC_TRIGGER_AUTO_TIMER,
        )
        status = await runtime._sync_queue.enqueue(
            account_id="manual-target",
            user_id=2,
            trigger_source=SYNC_TRIGGER_MANUAL,
        )
        service = AsyncMock()
        service.sync_account_snapshot.side_effect = lambda account_id, **_: _success_result(account_id)

        with patch(
            "backend.h5_backend.services.account.service.get_account_service",
            return_value=service,
        ):
            worker = asyncio.create_task(runtime._worker_loop())
            await asyncio.wait_for(runtime.wait_until_idle(), timeout=1)
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker

        self.assertEqual(status, "reprioritized")
        self.assertEqual(
            [call.args[0] for call in service.sync_account_snapshot.await_args_list],
            ["manual-target", "auto-first"],
        )

    async def test_worker_continues_after_one_account_raises(self):
        runtime = AccountAutoSyncRuntime()
        await runtime._sync_queue.enqueue(
            account_id="broken",
            user_id=1,
            trigger_source=SYNC_TRIGGER_AUTO_TIMER,
        )
        await runtime._sync_queue.enqueue(
            account_id="healthy",
            user_id=2,
            trigger_source=SYNC_TRIGGER_AUTO_TIMER,
        )
        service = AsyncMock()
        service.sync_account_snapshot.side_effect = [RuntimeError("boom"), _success_result("healthy")]

        with patch(
            "backend.h5_backend.services.account.service.get_account_service",
            return_value=service,
        ):
            worker = asyncio.create_task(runtime._worker_loop())
            await asyncio.wait_for(runtime.wait_until_idle(), timeout=1)
            broken = await runtime.wait_for_account("broken", timeout_seconds=0.1)
            healthy = await runtime.wait_for_account("healthy", timeout_seconds=0.1)
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker

        self.assertIn("RuntimeError", str(broken["error"]))
        self.assertTrue(healthy["resource_sync_ok"])
        self.assertEqual(service.sync_account_snapshot.await_count, 2)

    async def test_wait_timeout_does_not_cancel_shared_completion(self):
        runtime = AccountAutoSyncRuntime()
        await runtime._sync_queue.enqueue(
            account_id="slow",
            user_id=1,
            trigger_source=SYNC_TRIGGER_MANUAL,
        )

        with self.assertRaises(TimeoutError):
            await runtime.wait_for_account("slow", timeout_seconds=0.001)

        item = await runtime._sync_queue.get()
        runtime._sync_queue.complete(item, _success_result("slow"))
        result = await runtime.wait_for_account("slow", timeout_seconds=0.1)
        self.assertTrue(result["resource_sync_ok"])
