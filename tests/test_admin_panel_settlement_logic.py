import unittest
from datetime import datetime
from types import SimpleNamespace

from backend.database.schema.models import AgentFundLedger
from backend.h5_backend.services.admin_panel.batch_service import CardBatchService


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _SettlementSession:
    def __init__(self, *, credit_row, parent_account):
        self.credit_row = credit_row
        self.parent_account = parent_account
        self.added = []

    async def execute(self, _stmt):
        return _ScalarResult(self.credit_row)

    async def get(self, _model, _key):
        return self.parent_account

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def refresh(self, _value):
        return None


class SettlementLogicTests(unittest.IsolatedAsyncioTestCase):
    async def test_settlement_moves_liability_to_parent_and_reduces_credit_usage(self):
        service = CardBatchService()
        subject = SimpleNamespace(
            id=3,
            parent_account_id=2,
            credit_used_cents=8_000,
            credit_prepay_cents=8_000,
            balance_cents=0,
        )
        parent_account = SimpleNamespace(id=2, parent_account_id=None)
        credit_row = SimpleNamespace(delegated_credit_used_cents=8_000)
        batch = SimpleNamespace(
            batch_id="batch_credit_1",
            total_amount_cents=5_000,
            payment_status="credit",
            settlement_status="pending",
            current_liability_account_id=3,
            current_counterparty_account_id=2,
        )
        session = _SettlementSession(credit_row=credit_row, parent_account=parent_account)

        await service._apply_settlement_for_batch(
            session,
            subject=subject,
            batch=batch,
            operator=subject,
            request_id="req_1",
        )

        self.assertEqual(subject.credit_used_cents, 3_000)
        self.assertEqual(subject.credit_prepay_cents, 3_000)
        self.assertEqual(credit_row.delegated_credit_used_cents, 3_000)
        self.assertEqual(batch.current_liability_account_id, 2)
        self.assertIsNone(batch.current_counterparty_account_id)
        self.assertEqual(batch.payment_status, "credit")
        self.assertEqual(batch.settlement_status, "pending")
        ledger_rows = [item for item in session.added if isinstance(item, AgentFundLedger)]
        self.assertEqual(len(ledger_rows), 1)
        self.assertEqual(ledger_rows[0].biz_type, "credit_settlement")
        self.assertEqual(int(ledger_rows[0].amount_cents), 5_000)

    async def test_settle_credit_batch_uses_credit_prepay_for_single_batch(self):
        service = CardBatchService()
        operator = SimpleNamespace(
            id=3,
            parent_account_id=2,
            credit_used_cents=12_000,
            credit_prepay_cents=7_000,
            balance_cents=0,
        )
        batch = SimpleNamespace(
            batch_id="batch_credit_2",
            total_amount_cents=5_000,
            payment_status="credit",
            settlement_status="pending",
            current_liability_account_id=3,
            current_counterparty_account_id=2,
            owner_account_id=3,
        )
        sibling_batch = SimpleNamespace(
            batch_id="batch_credit_3",
            total_amount_cents=7_000,
            payment_status="credit",
            settlement_status="pending",
            current_liability_account_id=3,
            current_counterparty_account_id=2,
            owner_account_id=3,
        )
        credit_row = SimpleNamespace(delegated_credit_used_cents=12_000)
        parent_account = SimpleNamespace(id=2, parent_account_id=None)

        class _ServiceSession(_SettlementSession):
            async def get(self, _model, key):
                if str(key) == batch.batch_id:
                    return batch
                if int(key) == 3:
                    return operator
                if int(key) == 2:
                    return parent_account
                return None

        session = _ServiceSession(credit_row=credit_row, parent_account=parent_account)

        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock, patch

        @asynccontextmanager
        async def fake_get_async_session():
            yield session

        with patch(
            "backend.h5_backend.services.admin_panel.batch_service.get_async_session",
            new=fake_get_async_session,
        ), patch(
            "backend.h5_backend.services.admin_panel.batch_service.visible_account_ids",
            AsyncMock(return_value=[2, 3, 4]),
        ), patch(
            "backend.h5_backend.services.admin_panel.batch_service.append_audit",
            AsyncMock(),
        ), patch(
            "backend.h5_backend.services.admin_panel.batch_service.serialize_batch",
            side_effect=lambda current_batch: {
                "batch_id": current_batch.batch_id,
                "payment_status": current_batch.payment_status,
                "settlement_status": current_batch.settlement_status,
            },
        ):
            result = await service.settle_credit_batch(
                current_admin=operator,
                batch_id=batch.batch_id,
            )

        self.assertEqual(operator.credit_used_cents, 7_000)
        self.assertEqual(operator.credit_prepay_cents, 2_000)
        self.assertEqual(credit_row.delegated_credit_used_cents, 7_000)
        self.assertEqual(batch.current_liability_account_id, 2)
        self.assertEqual(sibling_batch.current_liability_account_id, 3)
        self.assertEqual(result["batch_id"], batch.batch_id)
        self.assertEqual(result["settlement_status"], "pending")
