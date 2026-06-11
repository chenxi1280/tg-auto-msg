from datetime import datetime, timedelta
from types import SimpleNamespace

import unittest

from backend.bot.account.proxy_observation import (
    SING_BOX_PROXY_REGIONS,
    get_proxy_region_options,
    is_proxy_observation_active,
    mark_proxy_observation_success,
    proxy_observation_has_send_budget,
    proxy_observation_remaining_seconds,
    reset_proxy_observation,
    select_reauth_proxy_for_account,
    start_proxy_observation,
)
from fastapi import HTTPException

from backend.database.schema.models import Account, Proxy
from backend.scheduler.core.task_runner import _lock_and_recheck_observation_budget


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class TestAccountProxyObservation(unittest.IsolatedAsyncioTestCase):
    def test_fixed_sing_box_regions_are_stable(self):
        options = get_proxy_region_options()

        assert [item["region_code"] for item in options] == ["hk", "tw", "jp", "sg", "us1", "us2", "uk"]
        assert [item["port"] for item in options] == [10801, 10802, 10803, 10804, 10805, 10806, 10807]
        assert all(item["host"] == "sing-box" for item in options)
        assert len(SING_BOX_PROXY_REGIONS) == 7

    def test_proxy_observation_starts_24_hour_window_with_one_success_budget(self):
        now = datetime(2026, 5, 9, 10, 0, 0)
        account = SimpleNamespace(
            proxy_observation_started_at=None,
            proxy_observation_until=None,
            proxy_observation_success_count=9,
        )

        start_proxy_observation(account, now=now)

        assert account.proxy_observation_started_at == now
        assert account.proxy_observation_until == now + timedelta(hours=24)
        assert account.proxy_observation_success_count == 0
        assert is_proxy_observation_active(account, now)
        assert proxy_observation_has_send_budget(account, now)
        assert proxy_observation_remaining_seconds(account, now) == 24 * 3600

        account.proxy_observation_success_count = 1
        assert not proxy_observation_has_send_budget(account, now)

    def test_proxy_observation_expires_without_manual_unlock(self):
        now = datetime(2026, 5, 9, 10, 0, 0)
        account = SimpleNamespace(
            proxy_observation_until=now - timedelta(seconds=1),
            proxy_observation_success_count=1,
        )

        assert not is_proxy_observation_active(account, now)
        assert proxy_observation_has_send_budget(account, now)

    async def test_proxy_observation_success_count_is_capped(self):
        class FakeSession:
            async def execute(self, statement):
                assert "UPDATE accounts" in str(statement)
                return SimpleNamespace(rowcount=0)

        marked = await mark_proxy_observation_success(FakeSession(), "acc-1", now=datetime(2026, 5, 9, 10, 0, 0))

        assert marked is False

    async def test_proxy_observation_success_mark_uses_atomic_update(self):
        class FakeSession:
            async def execute(self, statement):
                text = str(statement)
                assert "UPDATE accounts" in text
                assert "proxy_observation_success_count" in text
                return SimpleNamespace(rowcount=1)

        marked = await mark_proxy_observation_success(FakeSession(), "acc-1", now=datetime(2026, 5, 9, 10, 0, 0))

        assert marked is True

    def test_reset_proxy_observation_clears_window_but_keeps_counter_not_null(self):
        account = SimpleNamespace(
            proxy_observation_started_at=datetime(2026, 5, 9, 10, 0, 0),
            proxy_observation_until=datetime(2026, 5, 10, 10, 0, 0),
            proxy_observation_success_count=1,
        )

        reset_proxy_observation(account)

        assert account.proxy_observation_started_at is None
        assert account.proxy_observation_until is None
        assert account.proxy_observation_success_count == 0

    async def test_task_runner_claims_observation_budget_before_sending(self):
        account = SimpleNamespace(
            proxy_observation_until=datetime.now() + timedelta(hours=1),
            proxy_observation_success_count=0,
        )
        task = SimpleNamespace(
            task_id="task-1",
            title="task",
            text="hello",
            media_type="none",
            buttons=None,
            account_id="acc-1",
            next_run_at=None,
        )

        class FakeSession:
            def __init__(self):
                self.executed = []

            async def get(self, model, key):
                assert model is Account
                assert key == "acc-1"
                return account

            async def execute(self, statement, *_args, **_kwargs):
                self.executed.append(str(statement))
                return SimpleNamespace(rowcount=1)

        skipped, targets = await _lock_and_recheck_observation_budget(
            task=task,
            target_specs=[{"target": 1}, {"target": 2}],
            session=FakeSession(),
            now=1000,
            advance_schedule=True,
            trigger_source="scheduler",
            account_display="@acc",
        )

        assert skipped is None
        assert targets == [{"target": 1}]

    async def test_task_runner_skips_when_observation_budget_claim_loses_race(self):
        account = SimpleNamespace(
            proxy_observation_until=datetime.now() + timedelta(hours=1),
            proxy_observation_success_count=0,
        )
        task = SimpleNamespace(
            task_id="task-1",
            title="task",
            text="hello",
            media_type="none",
            buttons=None,
            account_id="acc-1",
            next_run_at=None,
        )

        class FakeSession:
            def __init__(self):
                self.committed = False

            async def get(self, model, key):
                assert model is Account
                assert key == "acc-1"
                return account

            async def execute(self, *_args, **_kwargs):
                return SimpleNamespace(rowcount=0)

            async def commit(self):
                self.committed = True

        session = FakeSession()
        skipped, targets = await _lock_and_recheck_observation_budget(
            task=task,
            target_specs=[{"target": 1}, {"target": 2}],
            session=session,
            now=1000,
            advance_schedule=True,
            trigger_source="scheduler",
            account_display="@acc",
        )

        assert skipped is not None
        assert skipped.status == "skipped"
        assert targets == []
        assert task.next_run_at == int(account.proxy_observation_until.timestamp())
        assert session.committed is True

    async def test_select_reauth_proxy_rejects_unavailable_existing_region(self):
        account = Account(
            account_id="acc-1",
            user_id=9,
            username="sender",
            string_session_encrypted="encrypted",
            proxy_id=None,
            reauth_required=False,
            health_status="online",
        )
        proxy = Proxy(
            proxy_id=1,
            proxy_type="socks5",
            host="sing-box",
            port=10801,
            display_name="香港",
            region_code="hk",
            is_system_gateway=True,
            is_shared=True,
            is_active=False,
            is_healthy=False,
        )

        class FakeSession:
            flushed = False

            async def get(self, model, key):
                if model is Account and key == "acc-1":
                    return account
                return None

            async def execute(self, statement):
                assert "FROM proxies" in str(statement)
                return _ScalarResult(proxy)

            async def flush(self):
                self.flushed = True

        session = FakeSession()

        with self.assertRaises(HTTPException) as raised:
            await select_reauth_proxy_for_account(
                session,
                user_id=9,
                account_id="acc-1",
                region_code="hk",
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertFalse(proxy.is_active)
        self.assertFalse(proxy.is_healthy)
        self.assertIsNone(account.proxy_id)
        self.assertFalse(account.reauth_required)
        self.assertFalse(session.flushed)
