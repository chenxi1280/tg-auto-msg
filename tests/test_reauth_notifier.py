import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.bot.account.reauth_notifier import (
    ReauthNoticeItem,
    ReauthReminderRuntime,
    mark_account_reauth_required,
    notify_account_authorization_required,
)
from backend.database.schema.models import Account, AppSetting, ScheduledMessageTask


class _ScalarResult:
    def __init__(self, value=None, rows=None):
        self._value = value
        self._rows = list(rows or [])

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _RowResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class _MarkSession:
    def __init__(self, account, tasks, authorization_end_at):
        self.account = account
        self.tasks = tasks
        self.authorization_end_at = authorization_end_at
        self.settings = {}
        self.execute_count = 0
        self.commits = 0

    async def get(self, model, key):
        if model is Account:
            return self.account if str(key) == str(self.account.account_id) else None
        if model is AppSetting:
            return self.settings.get(str(key))
        return None

    async def execute(self, _statement):
        self.execute_count += 1
        if self.execute_count == 1:
            return _ScalarResult(rows=self.tasks)
        return _ScalarResult(value=SimpleNamespace(end_at=self.authorization_end_at))

    def add(self, row):
        self.settings[str(row.key)] = row

    async def commit(self):
        self.commits += 1


class _ReminderSession:
    def __init__(self, *, rows, settings=None, enabled_tasks=None, notice_accounts=None):
        self.rows = rows
        self.settings = settings or {}
        self.enabled_tasks = enabled_tasks or {}
        self.notice_accounts = notice_accounts or []
        self.execute_count = 0

    async def get(self, model, key):
        if model is AppSetting:
            return self.settings.get(str(key))
        return None

    async def execute(self, _statement):
        self.execute_count += 1
        if self.execute_count == 1:
            return _RowResult(self.rows)
        if self.execute_count == 2:
            return _RowResult([(key, value.value) for key, value in self.settings.items()])
        if self.execute_count == 3 and self.notice_accounts:
            return _RowResult(self.notice_accounts)
        return _RowResult([
            (account_id, len(tasks))
            for account_id, tasks in self.enabled_tasks.items()
        ])


class _NoticeJoinSession(_ReminderSession):
    async def execute(self, statement):
        self.execute_count += 1
        if self.execute_count == 1:
            return _RowResult(self.rows)
        if self.execute_count == 2:
            return _RowResult([(key, value.value) for key, value in self.settings.items()])
        if self.execute_count == 3:
            compiled_sql = str(statement.compile(compile_kwargs={"literal_binds": True})).upper()
            if "LEFT OUTER JOIN" in compiled_sql:
                return _RowResult(self.notice_accounts)
            return _RowResult([])
        return _RowResult([
            (account_id, len(tasks))
            for account_id, tasks in self.enabled_tasks.items()
        ])


def _session_ctx(session):
    @asynccontextmanager
    async def _ctx():
        yield session

    return _ctx


class ReauthNotifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_mark_account_reauth_required_keeps_tasks_enabled_sends_and_records_notice(self):
        account = Account(
            account_id="acc-1",
            user_id=9,
            tg_user_id=10001,
            username="sender",
            string_session_encrypted="encrypted",
            reauth_required=False,
        )
        tasks = [
            ScheduledMessageTask(task_id="task-1", user_id=9, account_id="acc-1", title="任务1", enabled=True),
            ScheduledMessageTask(task_id="task-2", user_id=9, account_id="acc-1", title="任务2", enabled=True),
        ]
        session = _MarkSession(account, tasks, datetime(2026, 5, 15, 12, 0, 0))

        with (
            patch("backend.bot.account.reauth_notifier.get_async_session", _session_ctx(session)),
            patch("backend.bot.account.reauth_notifier._load_user_links", AsyncMock(return_value={9: 987654321})),
            patch("backend.bot.account.reauth_notifier.ensure_manager_bot_ready", AsyncMock(return_value=True)),
            patch("backend.bot.account.reauth_notifier.bot_client.send_message", AsyncMock()) as send_mock,
        ):
            result = await mark_account_reauth_required("acc-1", "session_unauthorized")

        self.assertIsNotNone(result)
        self.assertFalse(result.was_reauth_required)
        self.assertEqual(result.disabled_task_count, 2)
        self.assertTrue(result.notice_sent)
        self.assertTrue(account.reauth_required)
        self.assertEqual(account.reauth_reason, "session_unauthorized")
        self.assertTrue(tasks[0].enabled)
        self.assertTrue(tasks[1].enabled)
        send_mock.assert_awaited_once()
        buttons = send_mock.await_args.kwargs["buttons"]
        self.assertEqual(buttons[0][0].data, b"acc_proxy_select:acc-1:hk")
        self.assertEqual(buttons[-1][0].data, b"acc_relogin:acc-1")
        self.assertIn("reauth_notice:acc-1", session.settings)

    async def test_mark_account_reauth_required_does_not_repeat_immediate_notice(self):
        account = Account(
            account_id="acc-1",
            user_id=9,
            tg_user_id=10001,
            username="sender",
            string_session_encrypted="encrypted",
            reauth_required=True,
            reauth_reason="session_unauthorized",
        )
        session = _MarkSession(account, [], datetime(2026, 5, 15, 12, 0, 0))

        with (
            patch("backend.bot.account.reauth_notifier.get_async_session", _session_ctx(session)),
            patch("backend.bot.account.reauth_notifier._load_user_links", AsyncMock(return_value={9: 987654321})),
            patch("backend.bot.account.reauth_notifier.bot_client.send_message", AsyncMock()) as send_mock,
        ):
            result = await mark_account_reauth_required("acc-1", "session_unauthorized")

        self.assertIsNotNone(result)
        self.assertTrue(result.was_reauth_required)
        self.assertFalse(result.notice_sent)
        self.assertIsNone(result.user_id)
        send_mock.assert_not_awaited()

    async def test_collect_due_reminders_skips_today_notice_and_expired_auth_is_not_queried(self):
        account = Account(
            account_id="acc-1",
            user_id=9,
            tg_user_id=10001,
            username="sender",
            string_session_encrypted="encrypted",
            reauth_required=True,
            reauth_reason="session_unauthorized",
        )
        today = datetime.now().date().isoformat()
        session = _ReminderSession(
            rows=[(account, datetime.now() + timedelta(days=3))],
            settings={"reauth_notice:acc-1": AppSetting(key="reauth_notice:acc-1", value=today)},
        )
        notifier = ReauthReminderRuntime()

        with (
            patch("backend.bot.account.reauth_notifier.get_async_session", _session_ctx(session)),
            patch("backend.bot.account.reauth_notifier._load_user_links", AsyncMock(return_value={9: 987654321})),
        ):
            items = await notifier._collect_due_reminders()

        self.assertEqual(items, [])

    async def test_collect_due_reminders_stops_after_three_notices(self):
        account = Account(
            account_id="acc-1",
            user_id=9,
            tg_user_id=10001,
            username="sender",
            string_session_encrypted="encrypted",
            reauth_required=True,
            reauth_reason="session_unauthorized",
        )
        session = _ReminderSession(
            rows=[(account, datetime(2026, 5, 15, 12, 0, 0))],
            settings={
                "reauth_notice:acc-1": AppSetting(
                    key="reauth_notice:acc-1",
                    value='{"count":3,"first_sent_date":"2026-05-01","last_sent_date":"2026-05-03"}',
                )
            },
        )
        notifier = ReauthReminderRuntime()

        with (
            patch("backend.bot.account.reauth_notifier.get_async_session", _session_ctx(session)),
            patch("backend.bot.account.reauth_notifier._load_user_links", AsyncMock(return_value={9: 987654321})),
            patch("backend.bot.account.reauth_notifier.datetime") as datetime_mock,
        ):
            datetime_mock.now.return_value = datetime(2026, 5, 4, 9, 0, 0)
            items = await notifier._collect_due_reminders()

        self.assertEqual(items, [])

    async def test_collect_due_reminders_includes_authorization_expired_notice_state(self):
        account = Account(
            account_id="acc-expired",
            user_id=9,
            tg_user_id=10001,
            username="sender",
            string_session_encrypted="encrypted",
            reauth_required=False,
            reauth_reason=None,
        )
        session = _ReminderSession(
            rows=[],
            settings={
                "reauth_notice:acc-expired": AppSetting(
                    key="reauth_notice:acc-expired",
                    value='{"count":1,"first_sent_date":"2026-05-01","last_sent_date":"2026-05-01"}',
                )
            },
            enabled_tasks={
                "acc-expired": [
                    ScheduledMessageTask(task_id="task-1", user_id=9, account_id="acc-expired", title="任务1", enabled=True),
                ]
            },
            notice_accounts=[(account, datetime(2026, 5, 1, 12, 0, 0))],
        )
        notifier = ReauthReminderRuntime()

        with (
            patch("backend.bot.account.reauth_notifier.get_async_session", _session_ctx(session)),
            patch("backend.bot.account.reauth_notifier._load_user_links", AsyncMock(return_value={9: 987654321})),
            patch("backend.bot.account.reauth_notifier.datetime") as datetime_mock,
        ):
            datetime_mock.now.return_value = datetime(2026, 5, 2, 9, 0, 0)
            items = await notifier._collect_due_reminders()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].account_id, "acc-expired")
        self.assertEqual(items[0].authorization_end_at, datetime(2026, 5, 1, 12, 0, 0))

    async def test_collect_due_reminders_includes_notice_state_without_authorization_row(self):
        account = Account(
            account_id="acc-no-auth",
            user_id=9,
            tg_user_id=10001,
            username="sender",
            string_session_encrypted="encrypted",
            reauth_required=True,
            reauth_reason="session_unauthorized",
        )
        session = _NoticeJoinSession(
            rows=[],
            settings={
                "reauth_notice:acc-no-auth": AppSetting(
                    key="reauth_notice:acc-no-auth",
                    value='{"count":1,"first_sent_date":"2026-05-01","last_sent_date":"2026-05-01"}',
                )
            },
            enabled_tasks={"acc-no-auth": []},
            notice_accounts=[(account, None)],
        )
        notifier = ReauthReminderRuntime()

        with (
            patch("backend.bot.account.reauth_notifier.get_async_session", _session_ctx(session)),
            patch("backend.bot.account.reauth_notifier._load_user_links", AsyncMock(return_value={9: 987654321})),
            patch("backend.bot.account.reauth_notifier.datetime") as datetime_mock,
        ):
            datetime_mock.now.return_value = datetime(2026, 5, 2, 9, 0, 0)
            items = await notifier._collect_due_reminders()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].account_id, "acc-no-auth")
        self.assertIsNone(items[0].authorization_end_at)

    async def test_collect_due_reminders_ignores_old_notice_after_account_recovers(self):
        account = Account(
            account_id="acc-recovered",
            user_id=9,
            tg_user_id=10001,
            username="sender",
            string_session_encrypted="encrypted",
            reauth_required=False,
            reauth_reason=None,
        )
        session = _ReminderSession(
            rows=[],
            settings={
                "reauth_notice:acc-recovered": AppSetting(
                    key="reauth_notice:acc-recovered",
                    value='{"count":1,"first_sent_date":"2026-05-01","last_sent_date":"2026-05-01"}',
                )
            },
            notice_accounts=[(account, datetime(2026, 6, 1, 12, 0, 0))],
        )
        notifier = ReauthReminderRuntime()

        with (
            patch("backend.bot.account.reauth_notifier.get_async_session", _session_ctx(session)),
            patch("backend.bot.account.reauth_notifier._load_user_links", AsyncMock(return_value={9: 987654321})),
            patch("backend.bot.account.reauth_notifier.datetime") as datetime_mock,
        ):
            datetime_mock.now.return_value = datetime(2026, 5, 2, 9, 0, 0)
            items = await notifier._collect_due_reminders()

        self.assertEqual(items, [])

    async def test_notify_account_authorization_required_sends_immediate_notice_to_bound_user(self):
        account = Account(
            account_id="acc-1",
            user_id=9,
            tg_user_id=10001,
            username="sender",
            string_session_encrypted="encrypted",
            reauth_required=False,
        )
        tasks = [
            ScheduledMessageTask(task_id="task-1", user_id=9, account_id="acc-1", title="任务1", enabled=True),
        ]
        session = _MarkSession(account, tasks, datetime(2026, 5, 1, 12, 0, 0))

        with (
            patch("backend.bot.account.reauth_notifier.get_async_session", _session_ctx(session)),
            patch("backend.bot.account.reauth_notifier._load_user_links", AsyncMock(return_value={9: 987654321})),
            patch("backend.bot.account.reauth_notifier.ensure_manager_bot_ready", AsyncMock(return_value=True)),
            patch("backend.bot.account.reauth_notifier.bot_client.send_message", AsyncMock()) as send_mock,
        ):
            sent = await notify_account_authorization_required("acc-1", "authorization_expired")

        self.assertTrue(sent)
        send_mock.assert_awaited_once()
        self.assertIn("账号授权已失效", send_mock.await_args.args[1])
        self.assertIn("reauth_notice:acc-1", session.settings)

    async def test_collect_due_reminders_counts_only_enabled_tasks_in_batch(self):
        account = Account(
            account_id="acc-1",
            user_id=9,
            tg_user_id=10001,
            username="sender",
            string_session_encrypted="encrypted",
            reauth_required=True,
            reauth_reason="session_unauthorized",
        )
        session = _ReminderSession(
            rows=[(account, datetime.now() + timedelta(days=3))],
            enabled_tasks={
                "acc-1": [
                    ScheduledMessageTask(task_id="task-1", user_id=9, account_id="acc-1", title="任务1", enabled=True),
                ]
            },
        )
        notifier = ReauthReminderRuntime()

        with (
            patch("backend.bot.account.reauth_notifier.get_async_session", _session_ctx(session)),
            patch("backend.bot.account.reauth_notifier._load_user_links", AsyncMock(return_value={9: 987654321})),
        ):
            items = await notifier._collect_due_reminders()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].disabled_task_count, 1)
        self.assertEqual(session.execute_count, 3)

    async def test_scan_once_sends_daily_reminder(self):
        notifier = ReauthReminderRuntime()
        item = ReauthNoticeItem(
            account_id="acc-1",
            user_id=9,
            tg_user_id=987654321,
            account_label="@sender",
            disabled_task_count=1,
            authorization_end_at=datetime(2026, 5, 15, 12, 0, 0),
            reason="session_unauthorized",
        )

        with (
            patch.object(notifier, "_collect_due_reminders", AsyncMock(return_value=[item])),
            patch("backend.bot.account.reauth_notifier.ensure_manager_bot_ready", AsyncMock(return_value=True)),
            patch("backend.bot.account.reauth_notifier._send_reauth_notice", AsyncMock(return_value=True)) as send_mock,
        ):
            sent = await notifier.scan_once()

        self.assertEqual(sent, 1)
        send_mock.assert_awaited_once_with(item)


if __name__ == "__main__":
    unittest.main()
