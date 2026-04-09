import unittest
from datetime import datetime
from types import SimpleNamespace

from backend.database.schema.models import AgentFundLedger
from backend.h5_backend.services.admin_panel.service import AdminPanelService


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


class SettlementLogicTests(unittest.IsolatedAsyncioTestCase):
    async def test_settlement_moves_liability_to_parent_and_reduces_credit_usage(self):
        service = AdminPanelService()
        subject = SimpleNamespace(
            id=3,
            parent_account_id=2,
            credit_used_cents=8_000,
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
        self.assertEqual(credit_row.delegated_credit_used_cents, 3_000)
        self.assertEqual(batch.current_liability_account_id, 2)
        self.assertIsNone(batch.current_counterparty_account_id)
        self.assertEqual(batch.payment_status, "credit")
        self.assertEqual(batch.settlement_status, "pending")
        ledger_rows = [item for item in session.added if isinstance(item, AgentFundLedger)]
        self.assertEqual(len(ledger_rows), 1)
        self.assertEqual(ledger_rows[0].biz_type, "credit_settlement")
        self.assertEqual(int(ledger_rows[0].amount_cents), 5_000)
