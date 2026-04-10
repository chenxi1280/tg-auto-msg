import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.h5_backend.services.admin_panel.service import AdminPanelService, ROLE_MASTER_AGENT, ROLE_SUB_AGENT, ROLE_SUPER_ADMIN


class _ScalarListResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _OperationLogSession:
    def __init__(self, *, accounts, ledgers, batches):
        self.accounts = accounts
        self.ledgers = ledgers
        self.batches = batches

    async def execute(self, stmt):
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()
        if "from admin_accounts" in sql and "province_code" in sql:
            return _ScalarListResult([account.id for account in self.accounts if account.province_code == "default"])
        if "from admin_accounts" in sql and "parent_account_id in (2)" in sql:
            return _ScalarListResult([3])
        if "from admin_accounts" in sql and "parent_account_id in (3)" in sql:
            return _ScalarListResult([4])
        if "from admin_accounts" in sql and "parent_account_id in (4)" in sql:
            return _ScalarListResult([])
        if "from agent_fund_ledgers" in sql:
            if "account_id in (1, 2, 3, 4, 5)" in sql:
                visible = {1, 2, 3, 4, 5}
            elif "account_id in (2, 3, 4)" in sql:
                visible = {2, 3, 4}
            elif "account_id in (3, 4)" in sql:
                visible = {3, 4}
            else:
                raise AssertionError(f"unexpected ledger scope sql: {sql}")
            return _ScalarListResult([row for row in self.ledgers if int(row.account_id) in visible])
        if "from card_batches" in sql:
            if "owner_account_id in (1, 2, 3, 4, 5)" in sql:
                visible = {1, 2, 3, 4, 5}
            elif "owner_account_id in (2, 3, 4)" in sql:
                visible = {2, 3, 4}
            elif "owner_account_id in (3, 4)" in sql:
                visible = {3, 4}
            else:
                raise AssertionError(f"unexpected batch scope sql: {sql}")
            return _ScalarListResult([row for row in self.batches if int(row.owner_account_id) in visible])
        raise AssertionError(f"unexpected query: {sql}")


class OperationLogScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_operation_logs_respect_visible_account_chain(self):
        service = AdminPanelService()
        accounts = [
            SimpleNamespace(id=1, province_code="default"),
            SimpleNamespace(id=2, province_code="default"),
            SimpleNamespace(id=3, province_code="default"),
            SimpleNamespace(id=4, province_code="default"),
            SimpleNamespace(id=5, province_code="default"),
        ]
        ledgers = [
            SimpleNamespace(
                id=11,
                account_id=3,
                counterparty_account_id=2,
                operator_account_id=2,
                biz_type="recharge",
                direction="in",
                amount_cents=1000,
                balance_after_cents=1000,
                credit_used_after_cents=0,
                related_batch_id=None,
                related_request_id=None,
                ledger_scope="channel",
                remark="child",
                created_at=datetime(2026, 1, 1, 10, 0, 0),
            ),
            SimpleNamespace(
                id=12,
                account_id=5,
                counterparty_account_id=1,
                operator_account_id=1,
                biz_type="recharge",
                direction="in",
                amount_cents=2000,
                balance_after_cents=2000,
                credit_used_after_cents=0,
                related_batch_id=None,
                related_request_id=None,
                ledger_scope="platform",
                remark="sibling",
                created_at=datetime(2026, 1, 1, 11, 0, 0),
            ),
        ]
        batches = [
            SimpleNamespace(
                batch_id="batch_visible",
                creator_account_id=3,
                owner_account_id=4,
                direct_parent_account_id=3,
                root_master_account_id=2,
                plan_code="plan_month",
                quantity=2,
                total_amount_cents=2000,
                remark="funding_source=credit",
                created_at=datetime(2026, 1, 1, 12, 0, 0),
            ),
            SimpleNamespace(
                batch_id="batch_hidden",
                creator_account_id=5,
                owner_account_id=5,
                direct_parent_account_id=None,
                root_master_account_id=5,
                plan_code="plan_month",
                quantity=1,
                total_amount_cents=1000,
                remark="funding_source=balance",
                created_at=datetime(2026, 1, 1, 13, 0, 0),
            ),
        ]

        @asynccontextmanager
        async def fake_get_async_session():
            yield _OperationLogSession(accounts=accounts, ledgers=ledgers, batches=batches)

        with patch(
            "backend.h5_backend.services.admin_panel.service.get_async_session",
            new=fake_get_async_session,
        ), patch.object(
            service,
            "_build_account_name_map_from_ids",
            AsyncMock(return_value={2: "总代", 3: "子代理", 4: "下级", 5: "平级总代"}),
        ), patch.object(
            service,
            "_build_plan_name_map_from_codes",
            AsyncMock(return_value={"plan_month": "月卡"}),
        ):
            super_admin = SimpleNamespace(id=1, role_code=ROLE_SUPER_ADMIN, province_code="default")
            master = SimpleNamespace(id=2, role_code=ROLE_MASTER_AGENT, province_code="default")
            child = SimpleNamespace(id=3, role_code=ROLE_SUB_AGENT, province_code="default")

            super_rows = await service.list_operation_logs(current_admin=super_admin, scope_only=True)
            master_rows = await service.list_operation_logs(current_admin=master, scope_only=True)
            child_rows = await service.list_operation_logs(current_admin=child, scope_only=True)

        self.assertEqual(super_rows["total"], 4)
        self.assertEqual(master_rows["total"], 2)
        self.assertEqual(child_rows["total"], 2)
        self.assertEqual({item["subject_account_id"] for item in master_rows["items"]}, {3, 4})
        self.assertEqual({item["subject_account_id"] for item in child_rows["items"]}, {3, 4})
        self.assertNotIn(5, {item["subject_account_id"] for item in master_rows["items"]})
        self.assertNotIn(2, {item["subject_account_id"] for item in child_rows["items"]})


if __name__ == "__main__":
    unittest.main()
