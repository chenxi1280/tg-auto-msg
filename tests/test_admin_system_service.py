import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from backend.database.schema.models import AppSetting
from backend.h5_backend.services.admin.settings_service import SettingsService


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


def _build_notice_manager_module(refresh_summary):
    module = ModuleType("backend.bot.notice_manager")
    manager = SimpleNamespace(refresh_all_linked_users=AsyncMock(return_value=refresh_summary))
    module.get_bot_notice_manager = lambda: manager
    return module


class AdminSystemServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_today_system_stats_returns_all_three_metrics(self):
        service = SettingsService()
        values = iter([12, 5, 7])

        class _StatsSession:
            async def execute(self, _stmt):
                return _ScalarResult(next(values))

        @asynccontextmanager
        async def fake_get_async_session():
            yield _StatsSession()

        with patch("backend.h5_backend.services.admin.settings_service.get_async_session", new=fake_get_async_session):
            result = await service.get_today_system_stats()

        self.assertEqual(result["today_sent_messages"], 12)
        self.assertEqual(result["today_bound_cards"], 5)
        self.assertEqual(result["today_new_users"], 7)
        self.assertEqual(result["timezone"], "Asia/Shanghai")
        self.assertRegex(result["date"], r"^\d{4}-\d{2}-\d{2}$")

    async def test_update_bot_notice_settings_includes_refresh_summary(self):
        service = SettingsService()
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

        with patch("backend.h5_backend.services.admin.settings_service.get_async_session", new=fake_get_async_session), patch(
            "backend.h5_backend.services.admin.settings_service.append_audit_log",
            AsyncMock(),
        ), patch.dict(
            "sys.modules",
            {"backend.bot.notice_manager": _build_notice_manager_module(refresh_summary)},
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

    async def test_update_bot_notice_settings_allows_empty_target_url(self):
        service = SettingsService()
        fake_session = _NoticeSession()

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch("backend.h5_backend.services.admin.settings_service.get_async_session", new=fake_get_async_session), patch(
            "backend.h5_backend.services.admin.settings_service.append_audit_log",
            AsyncMock(),
        ), patch.dict(
            "sys.modules",
            {"backend.bot.notice_manager": _build_notice_manager_module({"updated": 0})},
        ), patch.object(
            service,
            "get_bot_notice_settings",
            AsyncMock(
                return_value={
                    "enabled": True,
                    "entry_button_text": "公告栏",
                    "message_text": "hello",
                    "target_url": "",
                    "updated_at": datetime.now().isoformat(),
                }
            ),
        ):
            result = await service.update_bot_notice_settings(
                enabled=True,
                entry_button_text="公告栏",
                message_text="hello",
                target_url="",
                actor="admin#1",
                ip_address="127.0.0.1",
            )

        self.assertTrue(fake_session.committed)
        self.assertEqual(result["target_url"], "")

    async def test_update_purchase_settings_allows_external_shop_url(self):
        service = SettingsService()
        fake_session = _NoticeSession()

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch("backend.h5_backend.services.admin.settings_service.get_async_session", new=fake_get_async_session), patch(
            "backend.h5_backend.services.admin.settings_service.append_audit_log",
            AsyncMock(),
        ):
            result = await service.update_purchase_settings(
                purchase_url="https://shop.example.com/cards?sku=monthly",
                purchase_button_text="购买卡密",
                actor="admin#1",
                ip_address="127.0.0.1",
            )

        self.assertTrue(fake_session.committed)
        self.assertEqual(result["purchase_url"], "https://shop.example.com/cards?sku=monthly")
        self.assertEqual(result["purchase_button_text"], "购买卡密")

    async def test_update_purchase_settings_rejects_local_shop_url(self):
        service = SettingsService()

        with self.assertRaises(HTTPException) as raised:
            await service.update_purchase_settings(
                purchase_url="http://127.0.0.1/cards",
                purchase_button_text="购买卡密",
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "购买链接格式无效，仅支持 Telegram 链接或公网 HTTP/HTTPS 商铺链接")


if __name__ == "__main__":
    unittest.main()
