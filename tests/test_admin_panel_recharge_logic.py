import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.database.schema.models import AgentFundLedger
from backend.h5_backend.services.admin_panel.service import (
    ACCOUNT_TYPE_AGENT,
    ACCOUNT_TYPE_STAFF,
    ROLE_SUPER_ADMIN,
)
from backend.h5_backend.services.admin_panel.ledger_service import FundLedgerService


class _ScalarListResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _ScalarValueResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _RechargeSession:
    def __init__(self, *, operator, subject, pending_batches, credit_row=None, parent_account=None):
        self.operator = operator
        self.subject = subject
        self.pending_batches = pending_batches
        self.credit_row = credit_row
        self.parent_account = parent_account
        self.added = []

    async def get(self, _model, key):
        if int(key) == int(self.operator.id):
            return self.operator
        if int(key) == int(self.subject.id):
            return self.subject
        if self.parent_account is not None and int(key) == int(self.parent_account.id):
            return self.parent_account
        return None

    async def execute(self, stmt):
        sql = str(stmt).lower()
        if "from card_batches" in sql and " limit " in sql:
            for batch in self.pending_batches:
                if (
                    int(batch.current_liability_account_id or 0) == int(self.subject.id)
                    and batch.payment_status == "credit"
                    and batch.settlement_status == "pending"
                ):
                    return _ScalarValueResult(batch.batch_id)
            return _ScalarValueResult(None)
        if "from card_batches" in sql:
            rows = [
                batch
                for batch in self.pending_batches
                if int(batch.current_liability_account_id or 0) == int(self.subject.id)
                and batch.payment_status == "credit"
                and batch.settlement_status == "pending"
            ]
            return _ScalarListResult(rows)
        if "from agent_credit_limits" in sql:
            return _ScalarValueResult(self.credit_row)
        raise AssertionError(f"unexpected query: {sql}")

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def refresh(self, _value):
        return None


class RechargeCreditSettlementTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_recharge_entry_keeps_insufficient_amount_as_credit_prepay(self):
        service = FundLedgerService()
        operator = SimpleNamespace(
            id=1,
            role_code=ROLE_SUPER_ADMIN,
            account_type=ACCOUNT_TYPE_STAFF,
            province_code="default",
        )
        subject = SimpleNamespace(
            id=3,
            account_type=ACCOUNT_TYPE_AGENT,
            parent_account_id=None,
            balance_cents=1_000,
            credit_used_cents=5_000,
            credit_prepay_cents=0,
        )
        pending_batches = [
            SimpleNamespace(
                batch_id="batch_a",
                total_amount_cents=5_000,
                payment_status="credit",
                settlement_status="pending",
                current_liability_account_id=3,
                current_counterparty_account_id=None,
                created_at=datetime(2026, 1, 1, 0, 0, 0),
            )
        ]
        fake_session = _RechargeSession(operator=operator, subject=subject, pending_batches=pending_batches)

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch(
            "backend.h5_backend.services.admin_panel.ledger_service.get_async_session",
            new=fake_get_async_session,
        ), patch(
            "backend.h5_backend.services.admin_panel.ledger_service.ensure_visible_account",
            AsyncMock(return_value=subject),
        ), patch(
            "backend.h5_backend.services.admin_panel.ledger_service.append_audit",
            AsyncMock(),
        ), patch(
            "backend.h5_backend.services.admin_panel.ledger_service.serialize_admin_account",
            side_effect=lambda account: {
                "balance_cents": int(account.balance_cents or 0),
                "credit_used_cents": int(account.credit_used_cents or 0),
                "credit_prepay_cents": int(account.credit_prepay_cents or 0),
            },
        ):
            data = await service.create_recharge_entry(
                current_admin=operator,
                subject_account_id=3,
                amount_cents=3_000,
                remark="线下已到账",
            )

        self.assertEqual(subject.balance_cents, 1_000)
        self.assertEqual(subject.credit_used_cents, 5_000)
        self.assertEqual(subject.credit_prepay_cents, 3_000)
        self.assertEqual(data["credit_prepay_cents"], 3_000)
        self.assertEqual(pending_batches[0].settlement_status, "pending")
        ledger_rows = [item for item in fake_session.added if isinstance(item, AgentFundLedger)]
        self.assertEqual(len(ledger_rows), 1)
        self.assertIn("授信预抵结转 30.00", ledger_rows[0].remark)
        self.assertNotIn("再补余额", ledger_rows[0].remark)

    async def test_create_recharge_entry_auto_settles_earliest_batch_then_carries_remaining_prepay(self):
        service = FundLedgerService()
        operator = SimpleNamespace(
            id=2,
            role_code="master_agent",
            account_type=ACCOUNT_TYPE_AGENT,
            province_code="default",
            parent_account_id=None,
        )
        subject = SimpleNamespace(
            id=3,
            account_type=ACCOUNT_TYPE_AGENT,
            parent_account_id=2,
            balance_cents=1_000,
            credit_used_cents=12_000,
            credit_prepay_cents=0,
        )
        parent_account = SimpleNamespace(id=2, account_type=ACCOUNT_TYPE_AGENT, parent_account_id=None)
        credit_row = SimpleNamespace(delegated_credit_used_cents=12_000)
        pending_batches = [
            SimpleNamespace(
                batch_id="batch_a",
                total_amount_cents=5_000,
                payment_status="credit",
                settlement_status="pending",
                current_liability_account_id=3,
                current_counterparty_account_id=2,
                created_at=datetime(2026, 1, 1, 0, 0, 0),
            ),
            SimpleNamespace(
                batch_id="batch_b",
                total_amount_cents=7_000,
                payment_status="credit",
                settlement_status="pending",
                current_liability_account_id=3,
                current_counterparty_account_id=2,
                created_at=datetime(2026, 1, 2, 0, 0, 0),
            ),
        ]
        fake_session = _RechargeSession(
            operator=operator,
            subject=subject,
            pending_batches=pending_batches,
            credit_row=credit_row,
            parent_account=parent_account,
        )

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch(
            "backend.h5_backend.services.admin_panel.ledger_service.get_async_session",
            new=fake_get_async_session,
        ), patch(
            "backend.h5_backend.services.admin_panel.ledger_service.ensure_visible_account",
            AsyncMock(return_value=subject),
        ), patch(
            "backend.h5_backend.services.admin_panel.ledger_service.append_audit",
            AsyncMock(),
        ), patch(
            "backend.h5_backend.services.admin_panel.ledger_service.serialize_admin_account",
            side_effect=lambda account: {
                "balance_cents": int(account.balance_cents or 0),
                "credit_used_cents": int(account.credit_used_cents or 0),
                "credit_prepay_cents": int(account.credit_prepay_cents or 0),
            },
        ):
            data = await service.create_recharge_entry(
                current_admin=operator,
                subject_account_id=3,
                amount_cents=8_000,
                remark="线下已到账",
            )

        self.assertEqual(subject.balance_cents, 1_000)
        self.assertEqual(subject.credit_used_cents, 7_000)
        self.assertEqual(subject.credit_prepay_cents, 3_000)
        self.assertEqual(credit_row.delegated_credit_used_cents, 7_000)
        self.assertEqual(pending_batches[0].current_liability_account_id, 2)
        self.assertEqual(pending_batches[0].settlement_status, "pending")
        self.assertEqual(pending_batches[1].current_liability_account_id, 3)
        self.assertEqual(data["credit_prepay_cents"], 3_000)
        ledger_rows = [item for item in fake_session.added if isinstance(item, AgentFundLedger)]
        self.assertEqual(len(ledger_rows), 2)
        self.assertEqual(ledger_rows[0].biz_type, "credit_settlement")
        self.assertEqual(ledger_rows[1].biz_type, "recharge")
        self.assertIn("先结清授信批次 50.00（1 批）", ledger_rows[1].remark)
        self.assertIn("授信预抵结转 30.00", ledger_rows[1].remark)


if __name__ == "__main__":
    unittest.main()
