import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.database.schema.models import HealthStatus
from backend.h5_backend.services.account.auto_sync import (
    SYNC_TRIGGER_AUTO_TIMER,
    SYNC_TRIGGER_MANUAL,
)
from backend.h5_backend.services.account.service import AccountService


class AccountServiceSyncTests(unittest.IsolatedAsyncioTestCase):
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
