import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from backend.database.schema.models import AppSetting
from backend.h5_backend.services.admin.settings_service import SettingsService
from backend.h5_backend.services.admin.user_service import UsersService


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class _ScalarOptionalResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _ScalarsResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


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
        values = iter([20, 12, 8, 5, 7, 3, 4])

        class _StatsSession:
            async def execute(self, _stmt):
                return _ScalarResult(next(values))

        @asynccontextmanager
        async def fake_get_async_session():
            yield _StatsSession()

        with patch("backend.h5_backend.services.admin.settings_service.get_async_session", new=fake_get_async_session):
            result = await service.get_today_system_stats()

        self.assertEqual(result["today_sent_messages"], 12)
        self.assertEqual(result["today_sent_messages_total"], 20)
        self.assertEqual(result["today_sent_success"], 12)
        self.assertEqual(result["today_sent_failed"], 8)
        self.assertEqual(result["today_bound_cards"], 5)
        self.assertEqual(result["today_new_users"], 7)
        self.assertEqual(result["today_activations"], 3)
        self.assertEqual(result["today_card_renewals"], 4)
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
        self.assertEqual(
            result["purchase_buttons"],
            [{"text": "购买卡密", "url": "https://shop.example.com/cards?sku=monthly"}],
        )

    async def test_update_purchase_settings_accepts_two_buttons_and_keeps_legacy_primary(self):
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
                purchase_buttons=[
                    {"text": "联系 A", "url": "https://t.me/contact_a"},
                    {"text": "联系 B", "url": "https://shop.example.com/cards"},
                ],
                actor="admin#1",
                ip_address="127.0.0.1",
            )

        self.assertTrue(fake_session.committed)
        self.assertEqual(result["purchase_url"], "https://t.me/contact_a")
        self.assertEqual(result["purchase_button_text"], "联系 A")
        self.assertEqual(
            result["purchase_buttons"],
            [
                {"text": "联系 A", "url": "https://t.me/contact_a"},
                {"text": "联系 B", "url": "https://shop.example.com/cards"},
            ],
        )

    async def test_update_purchase_settings_rejects_local_shop_url(self):
        service = SettingsService()

        with self.assertRaises(HTTPException) as raised:
            await service.update_purchase_settings(
                purchase_url="http://127.0.0.1/cards",
                purchase_button_text="购买卡密",
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "购买链接格式无效，仅支持 Telegram 链接或公网 HTTP/HTTPS 商铺链接")

    async def test_list_user_accounts_includes_send_summary(self):
        service = UsersService()
        user = SimpleNamespace(id=9)
        account = SimpleNamespace(
            account_id="acc_1",
            tg_user_id=10001,
            username="alice",
            first_name="Alice",
            phone="+100000000",
            developer_app_id=3,
            is_active=True,
            is_banned=False,
            health_status="online",
            is_flooding=False,
            messages_sent=8,
            created_at=datetime(2026, 5, 8, 9, 0, 0),
        )
        last_send_at = datetime(2026, 5, 8, 10, 30, 0)

        class _UserAccountSession:
            def __init__(self):
                self.calls = 0

            async def execute(self, _stmt):
                self.calls += 1
                if self.calls == 1:
                    return _ScalarOptionalResult(user)
                if self.calls == 2:
                    return _ScalarsResult([account])
                if self.calls == 3:
                    return _RowsResult([
                        SimpleNamespace(account_id="acc_1", task_count=3, enabled_task_count=2)
                    ])
                if self.calls == 4:
                    return _RowsResult([
                        SimpleNamespace(
                            account_id="acc_1",
                            send_log_count=5,
                            send_success_count=4,
                            send_failed_count=1,
                            last_send_at=last_send_at,
                        )
                    ])
                return _RowsResult([
                    SimpleNamespace(account_id="acc_1", result="failed", error_message="FloodWait")
                ])

        @asynccontextmanager
        async def fake_get_async_session():
            yield _UserAccountSession()

        authorization_summary = SimpleNamespace(to_dict=lambda: {"authorization_end_at": "2026-06-08T00:00:00"})

        with patch("backend.h5_backend.services.admin.user_service.get_async_session", new=fake_get_async_session), patch(
            "backend.h5_backend.services.admin.user_service.get_account_authorization_summary",
            AsyncMock(return_value=authorization_summary),
        ):
            result = await service.list_user_accounts(9)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tg_account_name"], "@alice")
        self.assertEqual(result[0]["task_count"], 3)
        self.assertEqual(result[0]["enabled_task_count"], 2)
        self.assertEqual(result[0]["send_log_count"], 5)
        self.assertEqual(result[0]["send_success_count"], 4)
        self.assertEqual(result[0]["send_failed_count"], 1)
        self.assertEqual(result[0]["last_send_at"], "2026-05-08T10:30:00")
        self.assertEqual(result[0]["last_send_result"], "failed")
        self.assertEqual(result[0]["last_send_error_message"], "FloodWait")
        self.assertEqual(result[0]["authorization_end_at"], "2026-06-08T00:00:00")

    async def test_list_account_send_logs_returns_paginated_items(self):
        service = UsersService()
        account = SimpleNamespace(account_id="acc_1", user_id=9)
        log = SimpleNamespace(
            id=7,
            send_at=datetime(2026, 5, 8, 10, 0, 0),
            result="success",
            trigger_source="scheduler",
            error_code=None,
            error_message=None,
            message_id=12345,
        )

        class _SendLogSession:
            def __init__(self):
                self.execute_calls = 0

            async def get(self, _model, key):
                self.get_key = key
                return account

            async def execute(self, _stmt):
                self.execute_calls += 1
                if self.execute_calls == 1:
                    return _ScalarResult(1)
                return _RowsResult([(log, "task_1", "早报任务")])

        fake_session = _SendLogSession()

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch("backend.h5_backend.services.admin.user_service.get_async_session", new=fake_get_async_session):
            result = await service.list_account_send_logs(9, "acc_1", result="success", limit=20, offset=0)

        self.assertEqual(fake_session.get_key, "acc_1")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["limit"], 20)
        self.assertEqual(result["offset"], 0)
        self.assertEqual(
            result["items"][0],
            {
                "id": 7,
                "task_id": "task_1",
                "task_title": "早报任务",
                "send_at": "2026-05-08T10:00:00",
                "result": "success",
                "trigger_source": "scheduler",
                "error_code": None,
                "error_message": None,
                "message_id": 12345,
            },
        )

    async def test_list_account_send_logs_rejects_invalid_result(self):
        service = UsersService()

        with self.assertRaises(HTTPException) as raised:
            await service.list_account_send_logs(9, "acc_1", result="pending")

        self.assertEqual(raised.exception.status_code, 400)

    async def test_list_account_send_logs_validates_account_owner(self):
        service = UsersService()

        class _SendLogSession:
            async def get(self, _model, _key):
                return SimpleNamespace(account_id="acc_1", user_id=10)

        @asynccontextmanager
        async def fake_get_async_session():
            yield _SendLogSession()

        with patch("backend.h5_backend.services.admin.user_service.get_async_session", new=fake_get_async_session):
            with self.assertRaises(HTTPException) as raised:
                await service.list_account_send_logs(9, "acc_1")

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "账号不存在")


if __name__ == "__main__":
    unittest.main()
