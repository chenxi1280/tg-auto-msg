import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.database.schema.models import AgentFundLedger
from backend.h5_backend.services.admin_panel.service import AdminPanelService


class RechargeAllocationTests(unittest.TestCase):
    def test_recharge_pays_down_credit_before_balance(self):
        service = AdminPanelService()

        repaid, topped_up = service._split_recharge_allocation(
            amount_cents=10_000,
            credit_used_cents=6_000,
        )

        self.assertEqual(repaid, 6_000)
        self.assertEqual(topped_up, 4_000)

    def test_recharge_all_goes_to_balance_when_no_credit_used(self):
        service = AdminPanelService()

        repaid, topped_up = service._split_recharge_allocation(
            amount_cents=10_000,
            credit_used_cents=0,
        )

        self.assertEqual(repaid, 0)
        self.assertEqual(topped_up, 10_000)

    def test_recharge_only_reduces_credit_when_amount_is_insufficient(self):
        service = AdminPanelService()

        repaid, topped_up = service._split_recharge_allocation(
            amount_cents=3_000,
            credit_used_cents=8_000,
        )

        self.assertEqual(repaid, 3_000)
        self.assertEqual(topped_up, 0)


class _ScalarListResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _RechargeSession:
    def __init__(self, operator, subject):
        self.operator = operator
        self.subject = subject
        self.added = []

    async def get(self, _model, key):
        if int(key) == int(self.operator.id):
            return self.operator
        return self.subject

    async def execute(self, _stmt):
        return _ScalarListResult([])

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def refresh(self, _value):
        return None


class RechargeCreditSettlementTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_settle_credit_batches_only_consumes_fully_coverable_batches(self):
        service = AdminPanelService()
        subject = SimpleNamespace(id=3)
        operator = SimpleNamespace(id=2)
        batches = [
            SimpleNamespace(batch_id="b1", total_amount_cents=5_000),
            SimpleNamespace(batch_id="b2", total_amount_cents=3_000),
            SimpleNamespace(batch_id="b3", total_amount_cents=6_000),
        ]

        class _BatchSession:
            async def execute(self, _stmt):
                return _ScalarListResult(batches)

        with patch.object(service, "_apply_settlement_for_batch", AsyncMock()) as settle_batch:
            settled_amount, settled_batch_ids = await service._auto_settle_credit_batches_for_recharge(
                _BatchSession(),
                subject=subject,
                operator=operator,
                amount_cents=9_000,
            )

        self.assertEqual(settled_amount, 8_000)
        self.assertEqual(settled_batch_ids, ["b1", "b2"])
        self.assertEqual(settle_batch.await_count, 2)

    async def test_create_recharge_entry_tops_up_balance_after_auto_settlement(self):
        service = AdminPanelService()
        operator = SimpleNamespace(
            id=2,
            role_code="master_agent",
            province_code="default",
        )
        subject = SimpleNamespace(
            id=3,
            parent_account_id=2,
            balance_cents=1_000,
            credit_used_cents=4_000,
        )
        fake_session = _RechargeSession(operator, subject)

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch(
            "backend.h5_backend.services.admin_panel.service.get_async_session",
            new=fake_get_async_session,
        ), patch.object(
            service,
            "_ensure_visible_account",
            AsyncMock(return_value=subject),
        ), patch.object(
            service,
            "_auto_settle_credit_batches_for_recharge",
            AsyncMock(return_value=(6_000, ["batch_a"])),
        ), patch.object(
            service,
            "_append_audit",
            AsyncMock(),
        ), patch.object(
            service,
            "_serialize_admin_account",
            return_value={"balance_cents": 5_000},
        ):
            data = await service.create_recharge_entry(
                current_admin=operator,
                subject_account_id=3,
                amount_cents=10_000,
                remark="线下已到账",
            )

        self.assertEqual(subject.balance_cents, 5_000)
        self.assertEqual(data["balance_cents"], 5_000)
        ledger_rows = [item for item in fake_session.added if isinstance(item, AgentFundLedger)]
        self.assertEqual(len(ledger_rows), 1)
        self.assertIn("先结清授信批次 60.00", ledger_rows[0].remark)
        self.assertIn("再补余额 40.00", ledger_rows[0].remark)
