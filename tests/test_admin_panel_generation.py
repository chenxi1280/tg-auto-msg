import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.database.schema.models import AgentFundLedger
from backend.h5_backend.services.admin_panel.service import (
    AdminPanelService,
    ROLE_MASTER_AGENT,
    ROLE_SUPER_ADMIN,
)


class _FakeSession:
    def __init__(self, operator):
        self.operator = operator
        self.added = []

    async def get(self, model, key):
        return self.operator

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None


class AdminPanelGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_super_admin_generation_uses_platform_flow(self):
        service = AdminPanelService()
        operator = SimpleNamespace(
            id=1,
            username="admin",
            role_code=ROLE_SUPER_ADMIN,
            province_code="default",
            parent_account_id=None,
            root_master_account_id=None,
            level_depth=0,
            status="active",
            settlement_mode="prepaid",
            is_credit_whitelisted=True,
            credit_limit_cents=0,
            allocated_credit_limit_cents=0,
            credit_used_cents=0,
            balance_cents=0,
            force_password_change=False,
            display_name="超级管理员",
            contact_name=None,
            contact_phone=None,
            last_login_at=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        fake_session = _FakeSession(operator)

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        batch = SimpleNamespace(
            batch_id="batch_1",
            province_code="default",
            creator_account_id=1,
            owner_account_id=1,
            direct_parent_account_id=None,
            root_master_account_id=None,
            current_liability_account_id=None,
            current_counterparty_account_id=None,
            plan_code="plan_month",
            quantity=2,
            duration_days=30,
            unit_price_cents=1000,
            total_amount_cents=2000,
            settlement_status="settled",
            payment_status="paid",
            export_count=0,
            remark="funding_source=platform",
            created_at=datetime.now(),
            last_exported_at=None,
            used_count=0,
        )
        cards = [
            SimpleNamespace(
                id=1,
                card_code="CARD001",
                plan_code="plan_month",
                duration_days=30,
                is_active=True,
                is_used=False,
                expires_at=None,
                used_by_user_id=None,
                used_at=None,
                batch_id="batch_1",
                owner_account_id=1,
                direct_parent_account_id=None,
                root_master_account_id=None,
                settlement_unit_price_cents=1000,
                card_source_type="platform",
                copy_status="new",
                created_at=datetime.now(),
            )
        ]
        quote = {
            "root_master": operator,
            "direct_parent_account_id": None,
            "plan": SimpleNamespace(plan_code="plan_month"),
            "duration_days": 30,
            "unit_price_cents": 1000,
            "total_amount_cents": 2000,
            "quantity": 2,
            "prefix": "",
            "expires_at": None,
        }

        with patch(
            "backend.h5_backend.services.admin_panel.service.get_async_session",
            new=fake_get_async_session,
        ), patch.object(
            service,
            "_prepare_batch_quote",
            AsyncMock(return_value=quote),
        ), patch.object(
            service,
            "_create_batch_records",
            AsyncMock(return_value=(batch, cards)),
        ), patch.object(
            service,
            "_append_audit",
            AsyncMock(),
        ), patch.object(
            service,
            "_ensure_credit_mode_allowed",
        ) as ensure_credit, patch.object(
            service,
            "_apply_balance_generation",
        ) as apply_balance:
            result = await service.generate_card_batch(
                current_admin=operator,
                plan_code="plan_month",
                quantity=2,
                funding_source="credit",
            )

        ensure_credit.assert_not_called()
        apply_balance.assert_not_called()
        self.assertEqual(result["batch"]["payment_status"], "paid")
        self.assertEqual(result["batch"]["settlement_status"], "settled")
        self.assertEqual(result["cards"][0]["card_source_type"], "platform")
        self.assertEqual(fake_session.added, [])

    async def test_master_agent_balance_generation_deducts_balance_and_writes_ledger(self):
        service = AdminPanelService()
        operator = SimpleNamespace(
            id=2,
            username="master",
            role_code=ROLE_MASTER_AGENT,
            province_code="default",
            parent_account_id=None,
            root_master_account_id=2,
            level_depth=0,
            status="active",
            settlement_mode="prepaid",
            is_credit_whitelisted=True,
            credit_limit_cents=100_000,
            allocated_credit_limit_cents=0,
            credit_used_cents=0,
            balance_cents=8_000,
            force_password_change=False,
            display_name="省总代",
            contact_name=None,
            contact_phone=None,
            last_login_at=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        fake_session = _FakeSession(operator)

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        batch = SimpleNamespace(
            batch_id="batch_balance",
            province_code="default",
            creator_account_id=2,
            owner_account_id=2,
            direct_parent_account_id=None,
            root_master_account_id=2,
            current_liability_account_id=None,
            current_counterparty_account_id=None,
            plan_code="plan_month",
            quantity=2,
            duration_days=30,
            unit_price_cents=1000,
            total_amount_cents=2000,
            settlement_status="settled",
            payment_status="paid",
            export_count=0,
            remark="funding_source=balance",
            created_at=datetime.now(),
            last_exported_at=None,
            used_count=0,
        )
        cards = [
            SimpleNamespace(
                id=1,
                card_code="CARD002",
                plan_code="plan_month",
                duration_days=30,
                is_active=True,
                is_used=False,
                expires_at=None,
                used_by_user_id=None,
                used_at=None,
                batch_id="batch_balance",
                owner_account_id=2,
                direct_parent_account_id=None,
                root_master_account_id=2,
                settlement_unit_price_cents=1000,
                card_source_type="balance",
                copy_status="new",
                created_at=datetime.now(),
            )
        ]
        quote = {
            "root_master": operator,
            "direct_parent_account_id": None,
            "plan": SimpleNamespace(plan_code="plan_month"),
            "duration_days": 30,
            "unit_price_cents": 1000,
            "total_amount_cents": 2000,
            "quantity": 2,
            "prefix": "",
            "expires_at": None,
        }

        with patch(
            "backend.h5_backend.services.admin_panel.service.get_async_session",
            new=fake_get_async_session,
        ), patch.object(
            service,
            "_prepare_batch_quote",
            AsyncMock(return_value=quote),
        ), patch.object(
            service,
            "_create_batch_records",
            AsyncMock(return_value=(batch, cards)),
        ), patch.object(
            service,
            "_append_audit",
            AsyncMock(),
        ):
            result = await service.generate_card_batch(
                current_admin=operator,
                plan_code="plan_month",
                quantity=2,
                funding_source="balance",
            )

        self.assertEqual(operator.balance_cents, 6_000)
        self.assertEqual(result["batch"]["payment_status"], "paid")
        ledger_rows = [item for item in fake_session.added if isinstance(item, AgentFundLedger)]
        self.assertEqual(len(ledger_rows), 1)
        self.assertEqual(ledger_rows[0].biz_type, "consume_balance")
        self.assertEqual(int(ledger_rows[0].amount_cents), 2000)
