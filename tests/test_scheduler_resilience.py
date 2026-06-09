import asyncio
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.bot.circuit.breaker import CircuitBreaker
from backend.bot.account.health_selection import select_account
from backend.bot.account.manager import AccountSelectionStrategy
from backend.database.schema.models import HealthStatus, TaskTriggerMode
from backend.scheduler.core.task_runner import execute_task_once
from backend.scheduler.core.health import collect_scheduler_health_snapshot
from backend.scheduler.core.queue_ops import get_pending_tasks
from backend.scheduler.core.worker import TaskScheduler


class _FakeQueueScalarResult:
    def __init__(self, task):
        self._task = task

    def scalars(self):
        return self

    def all(self):
        return [self._task] if self._task is not None else []

    def scalar_one_or_none(self):
        return self._task


class _FakeQueueSession:
    def __init__(self, task):
        self._task = task
        self.commits = 0

    async def execute(self, _statement):
        return _FakeQueueScalarResult(self._task)

    async def commit(self):
        self.commits += 1


class QueueOpsTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_pending_tasks_claims_due_tasks_via_lua_eval(self):
        fake_task = SimpleNamespace(
            task_id="task-1",
            enabled=True,
            trigger_mode=TaskTriggerMode.SCHEDULED.value,
        )
        fake_redis = SimpleNamespace(eval=AsyncMock(return_value=["task-1"]))

        @asynccontextmanager
        async def fake_session_ctx():
            yield _FakeQueueSession(fake_task)

        with patch(
            "backend.scheduler.core.queue_ops.get_async_session",
            fake_session_ctx,
        ):
            tasks = await get_pending_tasks(
                now=123,
                redis_client=fake_redis,
                queue_key="queue:tasks:pending",
                batch_size=10,
            )

        self.assertEqual([task.task_id for task in tasks], ["task-1"])
        fake_redis.eval.assert_awaited_once()


class WorkerLockingTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_task_from_queue_skips_when_processing_lock_exists(self):
        scheduler = TaskScheduler()
        scheduler.redis_client = SimpleNamespace(
            set=AsyncMock(return_value=False),
            eval=AsyncMock(),
        )

        with patch(
            "backend.scheduler.core.worker._execute_task_once",
            AsyncMock(),
        ) as execute_mock:
            await scheduler._execute_task_from_queue(
                SimpleNamespace(task_id="task-1"),
                now=123,
                current_hour=8,
            )

        execute_mock.assert_not_awaited()
        scheduler.redis_client.eval.assert_not_awaited()

    async def test_execute_task_from_queue_releases_owned_processing_lock(self):
        scheduler = TaskScheduler()
        scheduler.redis_client = SimpleNamespace(
            set=AsyncMock(return_value=True),
            eval=AsyncMock(return_value=1),
        )
        db_task = SimpleNamespace(task_id="task-1", enabled=True)

        @asynccontextmanager
        async def fake_session_ctx():
            yield _FakeQueueSession(db_task)

        summary = SimpleNamespace(
            status="success",
            success_count=1,
            failed_count=0,
            error_summary=None,
        )

        with patch(
            "backend.scheduler.core.worker.get_async_session",
            fake_session_ctx,
        ), patch(
            "backend.scheduler.core.worker._execute_task_once",
            AsyncMock(return_value=summary),
        ):
            await scheduler._execute_task_from_queue(
                SimpleNamespace(task_id="task-1"),
                now=123,
                current_hour=8,
            )

        scheduler.redis_client.set.assert_awaited_once()
        _, kwargs = scheduler.redis_client.set.await_args
        self.assertTrue(kwargs["nx"])
        self.assertEqual(kwargs["ex"], scheduler.PROCESSING_TTL)
        scheduler.redis_client.eval.assert_awaited_once()

    async def test_execute_task_from_queue_times_out_and_releases_lock(self):
        scheduler = TaskScheduler()
        scheduler.redis_client = SimpleNamespace(
            set=AsyncMock(return_value=True),
            eval=AsyncMock(return_value=1),
        )
        db_task = SimpleNamespace(task_id="task-timeout", enabled=True)

        @asynccontextmanager
        async def fake_session_ctx():
            yield _FakeQueueSession(db_task)

        async def never_finishes(*_args, **_kwargs):
            await asyncio.sleep(60)

        with patch(
            "backend.scheduler.core.worker.get_async_session",
            fake_session_ctx,
        ), patch(
            "backend.scheduler.core.worker._execute_task_once",
            never_finishes,
        ), patch(
            "backend.scheduler.core.worker.settings",
            SimpleNamespace(scheduler_task_timeout_seconds=1),
        ):
            await scheduler._execute_task_from_queue(
                SimpleNamespace(task_id="task-timeout"),
                now=123,
                current_hour=8,
            )

        self.assertEqual(scheduler.last_task_timeout_id, "task-timeout")
        scheduler.redis_client.eval.assert_awaited_once()

    async def test_execute_pending_tasks_runs_with_bounded_concurrency(self):
        scheduler = TaskScheduler()
        started = asyncio.Event()
        first_can_finish = asyncio.Event()
        running_count = 0
        max_running_count = 0

        async def execute_task(_task, _now, _current_hour):
            nonlocal running_count, max_running_count
            running_count += 1
            max_running_count = max(max_running_count, running_count)
            if running_count == 2:
                started.set()
            await first_can_finish.wait()
            running_count -= 1

        with patch.object(
            scheduler,
            "_execute_task_from_queue",
            execute_task,
        ), patch(
            "backend.scheduler.core.worker.settings",
            SimpleNamespace(scheduler_task_concurrency=2),
        ):
            task = asyncio.create_task(
                scheduler._execute_pending_tasks(
                    [SimpleNamespace(task_id=str(idx)) for idx in range(3)],
                    now=123,
                    current_hour=8,
                )
            )
            await asyncio.wait_for(started.wait(), timeout=1)
            self.assertEqual(max_running_count, 2)
            first_can_finish.set()
            await task


class SchedulerHealthSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_snapshot_marks_due_tasks_without_queue_unhealthy(self):
        class _Rows:
            def first(self):
                return SimpleNamespace(
                    _mapping={
                        "now_epoch": 1000,
                        "due_scheduled": 2,
                        "enabled_scheduled": 2,
                        "earliest_next_run": None,
                    }
                )

        class _Session:
            async def execute(self, _statement):
                return _Rows()

        @asynccontextmanager
        async def fake_session_ctx():
            yield _Session()

        fake_redis = SimpleNamespace(
            zrange=AsyncMock(return_value=[]),
            scan=AsyncMock(return_value=(0, [])),
        )

        snapshot = await collect_scheduler_health_snapshot(
            redis_client=fake_redis,
            session_factory=fake_session_ctx,
            now_epoch=1000,
        )

        self.assertEqual(snapshot["status"], "unhealthy")
        self.assertIn("due_tasks_not_queued", snapshot["issues"])
        self.assertEqual(snapshot["due_scheduled"], 2)


class CircuitBreakerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_with_circuit_breaker_recovers_expired_ban_before_send(self):
        breaker = CircuitBreaker()
        state = SimpleNamespace(
            account_id="acc-1",
            is_banned=True,
            is_flooding=True,
            flood_until=datetime.now() - timedelta(seconds=5),
        )

        async def get_account(_account_id):
            return state

        async def update_account(_account_id, **kwargs):
            for key, value in kwargs.items():
                setattr(state, key, value)
            return state

        breaker._account_manager = SimpleNamespace(
            get_account=AsyncMock(side_effect=get_account),
            update_account=AsyncMock(side_effect=update_account),
            health_check=AsyncMock(return_value=HealthStatus.ONLINE),
        )
        send_mock = AsyncMock(return_value="ok")

        with patch(
            "backend.bot.circuit.recovery.notify_account_recovered",
            AsyncMock(),
        ):
            result = await breaker.execute_with_circuit_breaker(
                "acc-1",
                send_mock,
            )

        self.assertEqual(result, "ok")
        self.assertFalse(state.is_banned)
        self.assertFalse(state.is_flooding)
        self.assertIsNone(state.flood_until)
        send_mock.assert_awaited_once()


class AccountSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_select_account_prefers_accounts_with_matching_resource(self):
        manager = SimpleNamespace(
            get_accounts=AsyncMock(),
            _round_robin_counter={},
        )
        account_a = SimpleNamespace(
            account_id="acc-a",
            health_status=HealthStatus.ONLINE,
            is_flooding=False,
            is_banned=False,
            weight=100,
            messages_sent=5,
        )
        account_b = SimpleNamespace(
            account_id="acc-b",
            health_status=HealthStatus.ONLINE,
            is_flooding=False,
            is_banned=False,
            weight=100,
            messages_sent=1,
        )
        manager.get_accounts.return_value = [account_a, account_b]

        class _ResourceRows:
            def scalars(self):
                return self

            def all(self):
                return ["acc-b"]

        class _ResourceSession:
            async def execute(self, _statement):
                return _ResourceRows()

        @asynccontextmanager
        async def fake_session_ctx():
            yield _ResourceSession()

        with patch(
            "backend.bot.account.health_selection.get_async_session",
            fake_session_ctx,
        ):
            selected = await select_account(
                manager,
                user_id=1,
                peer_id=2001,
                strategy=AccountSelectionStrategy.LEAST_USED,
            )

        self.assertEqual(selected.account_id, "acc-b")


class TaskRunnerReauthTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_task_once_stops_reauth_required_account_before_sending(self):
        task = SimpleNamespace(
            task_id="task-reauth",
            title="失效任务",
            user_id=9,
            account_id="acc-reauth",
            enabled=True,
            next_run_at=1,
            start_at=None,
            end_at=None,
            repeat_interval_min=10,
            text=None,
            media_type="none",
            buttons=None,
        )
        account = SimpleNamespace(
            account_id="acc-reauth",
            username="sender",
            phone="",
            first_name="",
            reauth_required=True,
            reauth_reason="session_unauthorized",
        )
        session = _FakeQueueSession(task)
        account_manager = SimpleNamespace(get_account=AsyncMock(return_value=account))
        auth_summary = SimpleNamespace(can_create_tasks=True)

        @asynccontextmanager
        async def fake_session_ctx():
            yield session

        with (
            patch("backend.scheduler.core.task_runner.get_async_session", fake_session_ctx),
            patch("backend.scheduler.core.task_runner.get_account_manager", return_value=account_manager),
            patch("backend.scheduler.core.task_runner.get_account_authorization_summary", AsyncMock(return_value=auth_summary)),
            patch("backend.scheduler.core.task_runner.mark_account_reauth_required", AsyncMock()) as mark_mock,
        ):
            summary = await execute_task_once("task-reauth")

        self.assertEqual(summary.status, "skipped")
        self.assertIn("需要重新绑定", summary.error_summary)
        self.assertTrue(task.enabled)
        self.assertGreater(task.next_run_at, 1)
        self.assertEqual(session.commits, 1)
        mark_mock.assert_awaited_once_with("acc-reauth", "session_unauthorized")
