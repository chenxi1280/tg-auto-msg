import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.bot.task_issue_notifier import TaskIssueNotifier
from backend.database.schema.models import TaskTargetSendIssue
from backend.scheduler.core.task_execution import collect_task_targets, count_configured_task_targets
from backend.scheduler.core.task_issue_classifier import classify_task_send_error
from backend.scheduler.core.task_issue_state import (
    TARGET_DELIVERY_SUSPENDED,
    has_target_collection_changed,
    merge_target_runtime_metadata,
    update_task_target_failure_metadata,
    update_task_target_success_metadata,
)


class TaskIssueClassifierTests(unittest.TestCase):
    def test_user_banned_error_is_auto_suspended(self):
        exc = type("UserBannedInChannelError", (Exception,), {})()
        result = classify_task_send_error(exc)

        self.assertEqual(result.issue_category, "permission_denied")
        self.assertTrue(result.should_auto_suspend_target)
        self.assertEqual(result.suspension_reason, "user_banned_in_channel")

    def test_channel_private_error_is_auto_suspended(self):
        exc = type("ChannelPrivateError", (Exception,), {})()
        result = classify_task_send_error(exc)

        self.assertEqual(result.issue_category, "target_inaccessible")
        self.assertTrue(result.should_auto_suspend_target)
        self.assertEqual(result.suspension_reason, "channel_private")

    def test_other_errors_are_not_auto_suspended(self):
        result = classify_task_send_error(RuntimeError("boom"))

        self.assertEqual(result.issue_category, "send_error")
        self.assertFalse(result.should_auto_suspend_target)
        self.assertIn("RuntimeError", result.user_message)


class TaskTargetRuntimeMetadataTests(unittest.TestCase):
    def test_collect_task_targets_skips_suspended_targets(self):
        task = SimpleNamespace(
            target_peers=[
                {"peer_id": 1001, "peer_type": "channel", "delivery_status": "active"},
                {"peer_id": 1002, "peer_type": "channel", "delivery_status": TARGET_DELIVERY_SUSPENDED},
            ],
            target_peer_id=None,
            chat_id=None,
            target_peer_type=None,
            target_access_hash=None,
        )

        targets = collect_task_targets(task)

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["peer_id"], 1001)
        self.assertEqual(count_configured_task_targets(task), 2)

    def test_collect_task_targets_does_not_fallback_when_all_explicit_targets_suspended(self):
        task = SimpleNamespace(
            target_peers=[
                {"peer_id": 1002, "peer_type": "channel", "delivery_status": TARGET_DELIVERY_SUSPENDED},
            ],
            target_peer_id=9999,
            chat_id=9999,
            target_peer_type="channel",
            target_access_hash=123,
        )

        targets = collect_task_targets(task)

        self.assertEqual(targets, [])

    def test_merge_target_runtime_metadata_reenables_existing_target(self):
        merged = merge_target_runtime_metadata(
            incoming_targets=[{"peer_id": 1001, "peer_type": "channel", "access_hash": 9}],
            existing_targets=[
                {
                    "peer_id": 1001,
                    "peer_type": "channel",
                    "access_hash": 9,
                    "title": "测试频道",
                    "last_sent_message_id": 88,
                    "delivery_status": TARGET_DELIVERY_SUSPENDED,
                    "suspended_reason": "channel_private",
                    "suspended_at": "2026-04-11T08:00:00",
                    "last_error_type": "ChannelPrivateError",
                    "last_error_message": "当前账号无权访问该频道或群组（ChannelPrivateError）",
                }
            ],
        )

        self.assertEqual(merged[0]["delivery_status"], "active")
        self.assertIsNone(merged[0]["suspended_reason"])
        self.assertEqual(merged[0]["title"], "测试频道")
        self.assertEqual(merged[0]["last_sent_message_id"], 88)
        self.assertEqual(merged[0]["last_error_type"], "ChannelPrivateError")

    def test_merge_target_runtime_metadata_preserves_suspension_when_not_resetting(self):
        merged = merge_target_runtime_metadata(
            incoming_targets=[{"peer_id": 1001, "peer_type": "channel", "access_hash": 9}],
            existing_targets=[
                {
                    "peer_id": 1001,
                    "peer_type": "channel",
                    "access_hash": 9,
                    "delivery_status": TARGET_DELIVERY_SUSPENDED,
                    "suspended_reason": "channel_private",
                    "suspended_at": "2026-04-11T08:00:00",
                }
            ],
            reset_delivery_status=False,
        )

        self.assertEqual(merged[0]["delivery_status"], TARGET_DELIVERY_SUSPENDED)
        self.assertEqual(merged[0]["suspended_reason"], "channel_private")

    def test_has_target_collection_changed_ignores_runtime_metadata_only_changes(self):
        changed = has_target_collection_changed(
            incoming_targets=[{"peer_id": 1001, "peer_type": "channel", "access_hash": 9}],
            existing_targets=[
                {
                    "peer_id": 1001,
                    "peer_type": "channel",
                    "access_hash": 9,
                    "delivery_status": TARGET_DELIVERY_SUSPENDED,
                    "last_error_type": "ChannelPrivateError",
                }
            ],
        )

        self.assertFalse(changed)

    def test_has_target_collection_changed_detects_replaced_target(self):
        changed = has_target_collection_changed(
            incoming_targets=[{"peer_id": 1002, "peer_type": "channel", "access_hash": 9}],
            existing_targets=[{"peer_id": 1001, "peer_type": "channel", "access_hash": 9}],
        )

        self.assertTrue(changed)

    def test_failure_and_success_metadata_updates(self):
        task = SimpleNamespace(
            target_peers=[{"peer_id": 2001, "peer_type": "channel", "title": "目标频道"}]
        )

        update_task_target_failure_metadata(
            task,
            peer_id=2001,
            peer_type="channel",
            peer_title="目标频道",
            error_type="ChannelPrivateError",
            error_message="当前账号无权访问该频道或群组（ChannelPrivateError）",
            suspension_reason="channel_private",
        )
        self.assertEqual(task.target_peers[0]["delivery_status"], TARGET_DELIVERY_SUSPENDED)
        self.assertEqual(task.target_peers[0]["last_error_type"], "ChannelPrivateError")

        update_task_target_success_metadata(task, peer_id=2001, peer_type="channel")
        self.assertEqual(task.target_peers[0]["delivery_status"], "active")
        self.assertIsNone(task.target_peers[0]["last_error_type"])
        self.assertIsNone(task.target_peers[0]["suspended_reason"])


class TaskIssueNotifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_scan_once_aggregates_active_issue_notifications(self):
        notifier = TaskIssueNotifier()
        now = datetime(2026, 4, 11, 12, 0, 0)
        issues = [
            TaskTargetSendIssue(
                id=1,
                user_id=9,
                task_id="task-1",
                account_id="acc-1",
                peer_id=1001,
                peer_type="channel",
                peer_title="频道 A",
                current_error_type="ChannelPrivateError",
                current_error_message="当前账号无权访问该频道或群组（ChannelPrivateError）",
                issue_category="target_inaccessible",
                status="active",
                auto_suspended=True,
            ),
            TaskTargetSendIssue(
                id=2,
                user_id=9,
                task_id="task-1",
                account_id="acc-1",
                peer_id=1002,
                peer_type="channel",
                peer_title="频道 B",
                current_error_type="RuntimeError",
                current_error_message="发送失败（RuntimeError）：boom",
                issue_category="send_error",
                status="active",
                auto_suspended=False,
            ),
        ]

        with (
            patch.object(notifier, "_list_pending_active_issues", AsyncMock(return_value=issues)),
            patch.object(notifier, "_list_pending_recovery_issues", AsyncMock(return_value=[])),
            patch.object(notifier, "_load_user_links", AsyncMock(return_value={9: 987654321})),
            patch.object(notifier, "_load_task_titles", AsyncMock(return_value={"task-1": "测试任务"})),
            patch.object(notifier, "_mark_active_notified", AsyncMock()) as mark_mock,
            patch("backend.bot.task_issue_notifier.bot_client.send_message", AsyncMock()) as send_mock,
            patch("backend.bot.task_issue_notifier.datetime") as datetime_mock,
        ):
            datetime_mock.now.return_value = now
            sent = await notifier.scan_once()

        self.assertEqual(sent, 1)
        send_mock.assert_awaited_once()
        sent_text = send_mock.await_args.args[1]
        self.assertIn("任务发送异常提醒", sent_text)
        self.assertIn("频道 A", sent_text)
        self.assertIn("系统已暂停该目标", sent_text)
        self.assertIn("频道 B", sent_text)
        mark_mock.assert_awaited_once()

    async def test_scan_once_sends_recovery_notification_once(self):
        notifier = TaskIssueNotifier()
        now = datetime(2026, 4, 11, 12, 0, 0)
        issues = [
            TaskTargetSendIssue(
                id=3,
                user_id=9,
                task_id="task-2",
                account_id="acc-1",
                peer_id=2001,
                peer_type="channel",
                peer_title="频道 C",
                current_error_type="ChannelPrivateError",
                current_error_message="当前账号无权访问该频道或群组（ChannelPrivateError）",
                issue_category="target_inaccessible",
                status="resolved",
                auto_suspended=True,
            )
        ]

        with (
            patch.object(notifier, "_list_pending_active_issues", AsyncMock(return_value=[])),
            patch.object(notifier, "_list_pending_recovery_issues", AsyncMock(return_value=issues)),
            patch.object(notifier, "_load_user_links", AsyncMock(return_value={9: 987654321})),
            patch.object(notifier, "_load_task_titles", AsyncMock(return_value={"task-2": "恢复任务"})),
            patch.object(notifier, "_mark_recovery_notified", AsyncMock()) as mark_mock,
            patch("backend.bot.task_issue_notifier.bot_client.send_message", AsyncMock()) as send_mock,
            patch("backend.bot.task_issue_notifier.datetime") as datetime_mock,
        ):
            datetime_mock.now.return_value = now
            sent = await notifier.scan_once()

        self.assertEqual(sent, 1)
        send_mock.assert_awaited_once()
        sent_text = send_mock.await_args.args[1]
        self.assertIn("任务目标已恢复", sent_text)
        self.assertIn("频道 C", sent_text)
        mark_mock.assert_awaited_once()

    async def test_old_unnotified_active_issue_is_not_backfilled(self):
        notifier = TaskIssueNotifier()
        now = datetime(2026, 4, 11, 12, 0, 0)

        with patch("backend.bot.task_issue_notifier.get_async_session", _fake_session_ctx([
            TaskTargetSendIssue(
                id=10,
                user_id=9,
                task_id="task-old",
                account_id="acc-1",
                peer_id=3001,
                peer_type="channel",
                peer_title="旧频道",
                current_error_type="RuntimeError",
                current_error_message="发送失败（RuntimeError）：boom",
                issue_category="send_error",
                status="active",
                last_notified_at=None,
                last_seen_at=datetime(2026, 4, 11, 10, 0, 0),
            )
        ])), patch.object(
            notifier, "_load_user_links", AsyncMock(return_value={9: 987654321})
        ), patch.object(
            notifier, "_load_task_titles", AsyncMock(return_value={"task-old": "旧任务"})
        ), patch(
            "backend.bot.task_issue_notifier.bot_client.send_message", AsyncMock()
        ) as send_mock, patch(
            "backend.bot.task_issue_notifier.datetime"
        ) as datetime_mock:
            datetime_mock.now.return_value = now
            active_issues = await notifier._list_pending_active_issues(now)
            self.assertEqual(active_issues, [])

            sent = await notifier.scan_once()

        self.assertEqual(sent, 0)
        send_mock.assert_not_awaited()

    async def test_old_recovery_issue_is_not_backfilled(self):
        notifier = TaskIssueNotifier()
        now = datetime(2026, 4, 11, 12, 0, 0)

        with patch("backend.bot.task_issue_notifier.get_async_session", _fake_session_ctx([
            TaskTargetSendIssue(
                id=11,
                user_id=9,
                task_id="task-old-recovery",
                account_id="acc-1",
                peer_id=4001,
                peer_type="channel",
                peer_title="旧恢复频道",
                current_error_type="ChannelPrivateError",
                current_error_message="当前账号无权访问该频道或群组（ChannelPrivateError）",
                issue_category="target_inaccessible",
                status="resolved",
                resolved_at=datetime(2026, 4, 11, 10, 0, 0),
                recovered_notified_at=None,
            )
        ])), patch.object(
            notifier, "_load_user_links", AsyncMock(return_value={9: 987654321})
        ), patch.object(
            notifier, "_load_task_titles", AsyncMock(return_value={"task-old-recovery": "旧恢复任务"})
        ), patch(
            "backend.bot.task_issue_notifier.bot_client.send_message", AsyncMock()
        ) as send_mock, patch(
            "backend.bot.task_issue_notifier.datetime"
        ) as datetime_mock:
            datetime_mock.now.return_value = now
            recovery_issues = await notifier._list_pending_recovery_issues()
            self.assertEqual(recovery_issues, [])

            sent = await notifier.scan_once()

        self.assertEqual(sent, 0)
        send_mock.assert_not_awaited()


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _statement):
        return _FakeScalarResult(self._rows)


def _fake_session_ctx(rows):
    class _Ctx:
        async def __aenter__(self_inner):
            return _FakeSession(rows)

        async def __aexit__(self_inner, exc_type, exc, tb):
            return False

    return _Ctx


if __name__ == "__main__":
    unittest.main()
