from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.dialects import postgresql

from backend.bot.account.health_selection import increment_messages_sent
from backend.scheduler.core.task_lifecycle import handle_task_success


class _RecordingSession:
    def __init__(self) -> None:
        self.executed = []
        self.added = []
        self.commit_count = 0

    async def execute(self, statement):
        self.executed.append(statement)
        return SimpleNamespace(rowcount=1)

    def add(self, value) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commit_count += 1


class AccountStatsTransactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_increment_messages_sent_uses_caller_session_without_commit(self):
        session = _RecordingSession()

        await increment_messages_sent(session, "account-1")

        self.assertEqual(len(session.executed), 1)
        statement = str(
            session.executed[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("UPDATE accounts", statement)
        self.assertIn("messages_sent=(accounts.messages_sent + 1)", statement)
        self.assertIn("last_used_at=", statement)
        self.assertEqual(session.commit_count, 0)

    async def test_task_success_updates_account_in_own_transaction(self):
        session = _RecordingSession()
        task = SimpleNamespace(
            task_id="task-1",
            account_id="account-1",
            failure_count=2,
            last_sent_message_id=None,
            next_run_at=100,
            repeat_interval_min=10,
        )
        increment = AsyncMock()

        with (
            patch(
                "backend.scheduler.core.task_lifecycle.increment_messages_sent",
                increment,
                create=True,
            ),
            patch(
                "backend.scheduler.core.task_lifecycle.mark_proxy_observation_success",
                AsyncMock(),
            ),
        ):
            await handle_task_success(
                session=session,
                task=task,
                message_id=42,
                target_message_ids=None,
                error_message=None,
                now=1_000,
            )

        increment.assert_awaited_once_with(session, "account-1")
        self.assertEqual(session.commit_count, 1)


if __name__ == "__main__":
    unittest.main()
