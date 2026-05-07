import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.database.schema.models import AgentFundLedger
from backend.h5_backend.services.admin_panel.service import (
    ACCOUNT_TYPE_AGENT,
    ACCOUNT_TYPE_STAFF,
    BUSINESS_IDENTITY_MASTER_AGENT,
    BUSINESS_IDENTITY_SUB_AGENT,
    ROLE_MASTER_AGENT,
    ROLE_SUB_AGENT,
    ROLE_SUPER_ADMIN,
)
from backend.h5_backend.services.admin_panel.batch_service import CardBatchService


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
        service = CardBatchService()
        operator = SimpleNamespace(
            id=1,
            username="admin",
            role_code=ROLE_SUPER_ADMIN,
            account_type=ACCOUNT_TYPE_STAFF,
            business_identity=None,
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
            "backend.h5_backend.services.admin_panel.batch_service.get_async_session",
            new=fake_get_async_session,
        ), patch.object(
            service,
            "_prepare_batch_quote",
            AsyncMock(return_value=quote),
        ), patch.object(
            service,
            "_create_batch_records",
            AsyncMock(return_value=(batch, cards)),
        ), patch(
            "backend.h5_backend.services.admin_panel.batch_service.append_audit",
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
        service = CardBatchService()
        operator = SimpleNamespace(
            id=2,
            username="master",
            role_code=ROLE_MASTER_AGENT,
            account_type=ACCOUNT_TYPE_AGENT,
            business_identity=BUSINESS_IDENTITY_MASTER_AGENT,
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
            "backend.h5_backend.services.admin_panel.batch_service.get_async_session",
            new=fake_get_async_session,
        ), patch.object(
            service,
            "_prepare_batch_quote",
            AsyncMock(return_value=quote),
        ), patch.object(
            service,
            "_create_batch_records",
            AsyncMock(return_value=(batch, cards)),
        ), patch(
            "backend.h5_backend.services.admin_panel.batch_service.append_audit",
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

    async def test_sub_agent_credit_generation_updates_each_level_usage_and_ledgers(self):
        service = CardBatchService()
        root_master = SimpleNamespace(
            id=1,
            username="root",
            role_code=ROLE_MASTER_AGENT,
            account_type=ACCOUNT_TYPE_AGENT,
            business_identity=BUSINESS_IDENTITY_MASTER_AGENT,
            province_code="default",
            parent_account_id=None,
            root_master_account_id=1,
            level_depth=0,
            status="active",
            settlement_mode="credit",
            is_credit_whitelisted=True,
            credit_limit_cents=100_000,
            allocated_credit_limit_cents=20_000,
            credit_used_cents=10_000,
            balance_cents=0,
            force_password_change=False,
            display_name="总代",
            contact_name=None,
            contact_phone=None,
            last_login_at=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        parent_agent = SimpleNamespace(
            id=2,
            username="parent",
            role_code=ROLE_SUB_AGENT,
            account_type=ACCOUNT_TYPE_AGENT,
            business_identity=BUSINESS_IDENTITY_SUB_AGENT,
            province_code="default",
            parent_account_id=1,
            root_master_account_id=1,
            level_depth=1,
            status="active",
            settlement_mode="credit",
            is_credit_whitelisted=True,
            credit_limit_cents=20_000,
            allocated_credit_limit_cents=10_000,
            credit_used_cents=2_000,
            balance_cents=0,
            force_password_change=False,
            display_name="一级代理",
            contact_name=None,
            contact_phone=None,
            last_login_at=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        operator = SimpleNamespace(
            id=3,
            username="child",
            role_code=ROLE_SUB_AGENT,
            account_type=ACCOUNT_TYPE_AGENT,
            business_identity=BUSINESS_IDENTITY_SUB_AGENT,
            province_code="default",
            parent_account_id=2,
            root_master_account_id=1,
            level_depth=2,
            status="active",
            settlement_mode="credit",
            is_credit_whitelisted=True,
            credit_limit_cents=10_000,
            allocated_credit_limit_cents=0,
            credit_used_cents=1_000,
            balance_cents=0,
            force_password_change=False,
            display_name="二级代理",
            contact_name=None,
            contact_phone=None,
            last_login_at=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        fake_session = _FakeSession(operator)
        row_child = SimpleNamespace(delegated_credit_used_cents=1_000)
        row_parent = SimpleNamespace(delegated_credit_used_cents=2_000)
        chain = [
            (operator, parent_agent, row_child),
            (parent_agent, root_master, row_parent),
        ]

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        batch = SimpleNamespace(
            batch_id="batch_credit_multi",
            province_code="default",
            creator_account_id=3,
            owner_account_id=3,
            direct_parent_account_id=2,
            root_master_account_id=1,
            current_liability_account_id=3,
            current_counterparty_account_id=2,
            plan_code="plan_month",
            quantity=2,
            duration_days=30,
            unit_price_cents=1000,
            total_amount_cents=2000,
            settlement_status="pending",
            payment_status="credit",
            export_count=0,
            remark="funding_source=credit",
            created_at=datetime.now(),
            last_exported_at=None,
            used_count=0,
        )
        cards = [
            SimpleNamespace(
                id=1,
                card_code="CARD003",
                plan_code="plan_month",
                duration_days=30,
                is_active=True,
                is_used=False,
                expires_at=None,
                used_by_user_id=None,
                used_at=None,
                batch_id="batch_credit_multi",
                owner_account_id=3,
                direct_parent_account_id=2,
                root_master_account_id=1,
                settlement_unit_price_cents=1000,
                card_source_type="credit",
                copy_status="new",
                created_at=datetime.now(),
            )
        ]
        quote = {
            "root_master": root_master,
            "direct_parent_account_id": 2,
            "plan": SimpleNamespace(plan_code="plan_month"),
            "duration_days": 30,
            "unit_price_cents": 1000,
            "total_amount_cents": 2000,
            "quantity": 2,
            "prefix": "",
            "expires_at": None,
        }

        with patch(
            "backend.h5_backend.services.admin_panel.batch_service.get_async_session",
            new=fake_get_async_session,
        ), patch.object(
            service,
            "_prepare_batch_quote",
            AsyncMock(return_value=quote),
        ), patch.object(
            service,
            "_create_batch_records",
            AsyncMock(return_value=(batch, cards)),
        ), patch(
            "backend.h5_backend.services.admin_panel.batch_service.append_audit",
            AsyncMock(),
        ), patch.object(
            service,
            "_validate_credit_generation",
            AsyncMock(return_value=chain),
        ):
            result = await service.generate_card_batch(
                current_admin=operator,
                plan_code="plan_month",
                quantity=2,
                funding_source="credit",
            )

        self.assertEqual(result["batch"]["payment_status"], "credit")
        self.assertEqual(operator.credit_used_cents, 3_000)
        self.assertEqual(parent_agent.credit_used_cents, 4_000)
        self.assertEqual(root_master.credit_used_cents, 12_000)
        self.assertEqual(row_child.delegated_credit_used_cents, 3_000)
        self.assertEqual(row_parent.delegated_credit_used_cents, 4_000)
        ledger_rows = [item for item in fake_session.added if isinstance(item, AgentFundLedger)]
        self.assertEqual(len(ledger_rows), 3)
        self.assertEqual([row.ledger_scope for row in ledger_rows], ["channel", "channel", "platform"])
