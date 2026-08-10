import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks, HTTPException

from backend.database.schema.models import HealthStatus
from backend.h5_backend.services.account.auto_sync import (
    SYNC_TRIGGER_AUTO_TIMER,
    SYNC_TRIGGER_MANUAL,
)
from backend.h5_backend.services.account.service import AccountService
from backend.h5_backend.services.account.service import account_auto_sync_runtime


class AccountServiceSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_wait_returns_only_completed_resource_result(self):
        service = AccountService()
        completed = {
            "profile_sync_ok": True,
            "resource_sync_ok": True,
            "resource_synced_count": 115,
            "error": None,
        }

        with patch(
            "backend.h5_backend.services.account.service.check_account_permission",
            AsyncMock(),
        ), patch.object(
            account_auto_sync_runtime,
            "enqueue_account",
            AsyncMock(return_value={"status": "enqueued"}),
        ), patch.object(
            account_auto_sync_runtime,
            "wait_for_account",
            AsyncMock(return_value=completed),
        ):
            result = await service.sync_resources("acc-1", 7, BackgroundTasks(), wait=True)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["data"], completed)
        self.assertIn("115", result["message"])

    async def test_manual_wait_surfaces_resource_sync_failure(self):
        service = AccountService()
        failed = {
            "profile_sync_ok": True,
            "resource_sync_ok": False,
            "resource_synced_count": 0,
            "error": "Telegram read failed",
        }

        with patch(
            "backend.h5_backend.services.account.service.check_account_permission",
            AsyncMock(),
        ), patch.object(
            account_auto_sync_runtime,
            "enqueue_account",
            AsyncMock(return_value={"status": "running"}),
        ), patch.object(
            account_auto_sync_runtime,
            "wait_for_account",
            AsyncMock(return_value=failed),
        ):
            with self.assertRaises(HTTPException) as raised:
                await service.sync_resources("acc-1", 7, BackgroundTasks(), wait=True)

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(raised.exception.detail, "Telegram read failed")

    async def test_manual_non_waiting_request_reports_reprioritized_state(self):
        service = AccountService()

        with patch(
            "backend.h5_backend.services.account.service.check_account_permission",
            AsyncMock(),
        ), patch.object(
            account_auto_sync_runtime,
            "enqueue_account",
            AsyncMock(return_value={"status": "reprioritized"}),
        ):
            result = await service.sync_resources("acc-1", 7, BackgroundTasks(), wait=False)

        self.assertEqual(result["status"], "reprioritized")
        self.assertFalse(result["already_running"])

    async def test_sync_all_counts_reprioritized_accounts_as_queued_work(self):
        service = AccountService()
        account_manager = SimpleNamespace(
            get_accounts=AsyncMock(
                return_value=[
                    SimpleNamespace(account_id="acc-1"),
                    SimpleNamespace(account_id="acc-2"),
                ]
            )
        )

        with patch(
            "backend.h5_backend.services.account.service.get_account_manager",
            return_value=account_manager,
        ), patch.object(
            account_auto_sync_runtime,
            "enqueue_account",
            AsyncMock(side_effect=[{"status": "reprioritized"}, {"status": "queued"}]),
        ):
            result = await service.sync_all_resources(7)

        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["data"]["reprioritized_accounts"], 1)
        self.assertEqual(result["data"]["already_running_accounts"], 1)
        self.assertFalse(result["already_running"])

    async def test_auto_timer_client_unavailable_does_not_mark_account_offline(self):
        service = AccountService()
        account_manager = SimpleNamespace(
            get_account=AsyncMock(return_value=SimpleNamespace(account_id="acc-1", user_id=7, is_active=True)),
            get_client=AsyncMock(return_value=None),
            update_account=AsyncMock(),
        )

        with patch(
            "backend.h5_backend.services.account.service.get_account_manager",
            return_value=account_manager,
        ), patch(
            "backend.h5_backend.services.account.service.get_resource_manager",
            return_value=SimpleNamespace(),
        ), patch(
            "backend.h5_backend.services.account.service.diagnose_client_unavailable",
            AsyncMock(return_value="client unavailable"),
        ):
            result = await service.sync_account_snapshot("acc-1", trigger_source=SYNC_TRIGGER_AUTO_TIMER)

        self.assertFalse(result["profile_sync_ok"])
        self.assertEqual(result["error"], "client unavailable")
        account_manager.update_account.assert_not_awaited()

    async def test_manual_client_unavailable_marks_account_offline(self):
        service = AccountService()
        account_manager = SimpleNamespace(
            get_account=AsyncMock(return_value=SimpleNamespace(account_id="acc-1", user_id=7, is_active=True)),
            get_client=AsyncMock(return_value=None),
            update_account=AsyncMock(),
        )

        with patch(
            "backend.h5_backend.services.account.service.get_account_manager",
            return_value=account_manager,
        ), patch(
            "backend.h5_backend.services.account.service.get_resource_manager",
            return_value=SimpleNamespace(),
        ), patch(
            "backend.h5_backend.services.account.service.diagnose_client_unavailable",
            AsyncMock(return_value="client unavailable"),
        ):
            result = await service.sync_account_snapshot("acc-1", trigger_source=SYNC_TRIGGER_MANUAL)

        self.assertFalse(result["profile_sync_ok"])
        account_manager.update_account.assert_awaited_once_with(
            "acc-1",
            health_status=HealthStatus.OFFLINE.value,
        )
