import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.database.schema.models import AppSetting
from backend.h5_backend.services.admin.service import AdminLicenseService


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class _NoticeSession:
    def __init__(self):
        self.rows = {}
        self.added = []
        self.committed = False

    async def get(self, model, key):
        return self.rows.get((model, key))

    def add(self, value):
        self.added.append(value)
        if isinstance(value, AppSetting):
            self.rows[(AppSetting, value.key)] = value

    async def commit(self):
        self.committed = True


class AdminSystemServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_today_system_stats_returns_all_three_metrics(self):
        service = AdminLicenseService()
        values = iter([12, 5, 7])

        class _StatsSession:
            async def execute(self, _stmt):
                return _ScalarResult(next(values))

        @asynccontextmanager
        async def fake_get_async_session():
            yield _StatsSession()

        with patch("backend.h5_backend.services.admin.service.get_async_session", new=fake_get_async_session):
            result = await service.get_today_system_stats()

        self.assertEqual(result["today_sent_messages"], 12)
        self.assertEqual(result["today_bound_cards"], 5)
        self.assertEqual(result["today_new_users"], 7)
        self.assertEqual(result["timezone"], "Asia/Shanghai")
        self.assertRegex(result["date"], r"^\d{4}-\d{2}-\d{2}$")

    async def test_update_bot_notice_settings_includes_refresh_summary(self):
        service = AdminLicenseService()
        fake_session = _NoticeSession()

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        refresh_summary = {
            "total_users": 3,
            "updated": 2,
            "failed": 1,
            "pin_attempted_users": 2,
            "pin_failed_users": 1,
        }

        with patch("backend.h5_backend.services.admin.service.get_async_session", new=fake_get_async_session), patch.object(
            service,
            "_append_audit",
            AsyncMock(),
        ), patch(
            "backend.bot.notice_manager.get_bot_notice_manager",
            return_value=SimpleNamespace(refresh_all_linked_users=AsyncMock(return_value=refresh_summary)),
        ), patch.object(
            service,
            "get_bot_notice_settings",
            AsyncMock(
                return_value={
                    "enabled": True,
                    "entry_button_text": "公告栏",
                    "message_text": "hello",
                    "target_url": "https://example.com",
                    "updated_at": datetime.now().isoformat(),
                }
            ),
        ):
            result = await service.update_bot_notice_settings(
                enabled=True,
                entry_button_text="公告栏",
                message_text="hello",
                target_url="https://example.com",
                actor="admin#1",
                ip_address="127.0.0.1",
            )

        self.assertTrue(fake_session.committed)
        self.assertEqual(result["refresh_summary"], refresh_summary)


if __name__ == "__main__":
    unittest.main()
