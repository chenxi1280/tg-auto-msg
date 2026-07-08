import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from backend.h5_backend.services.admin.clash_address_service import ClashAddressService


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value


class _ClashSession:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.added = []
        self.deleted = []
        self.committed = False
        self.flushed = False

    async def get(self, _model, key):
        for row in self.rows:
            if row.id == key:
                return row
        return None

    async def execute(self, stmt):
        text = str(stmt)
        if "is_active" in text and "UPDATE" in text:
            for row in self.rows:
                row.is_active = False
            return _Result(None)
        return _Result(self.rows)

    def add(self, value):
        value.id = len(self.rows) + 1
        value.created_at = datetime(2026, 7, 8, 9, 0, 0)
        value.updated_at = datetime(2026, 7, 8, 9, 0, 0)
        self.rows.append(value)
        self.added.append(value)

    async def flush(self):
        self.flushed = True

    async def delete(self, value):
        self.deleted.append(value)
        self.rows.remove(value)

    async def commit(self):
        self.committed = True


class _FakeClashApplier:
    def __init__(self, *, error=None):
        self.applied_urls = []
        self.error = error

    async def apply(self, url):
        self.applied_urls.append(url)
        if self.error:
            raise self.error


def _row(
    row_id,
    *,
    name="主订阅",
    url="https://proxy.example.com/sub?token=secret-token",
    is_active=False,
    remark="",
):
    return SimpleNamespace(
        id=row_id,
        name=name,
        url=url,
        is_active=is_active,
        remark=remark,
        created_at=datetime(2026, 7, 8, 9, 0, 0),
        updated_at=datetime(2026, 7, 8, 9, 0, 0),
    )


class ClashAddressServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_clash_address_masks_secret_url(self):
        applier = _FakeClashApplier()
        service = ClashAddressService(applier=applier)
        fake_session = _ClashSession()

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch(
            "backend.h5_backend.services.admin.clash_address_service.get_async_session",
            new=fake_get_async_session,
        ), patch(
            "backend.h5_backend.services.admin.clash_address_service.append_audit_log",
            AsyncMock(),
        ):
            result = await service.create_address(
                name="香港主线路",
                url="https://proxy.example.com/sub?token=secret-token",
                is_active=True,
                remark="机场 A",
                actor="admin#1",
                ip_address="127.0.0.1",
            )

        self.assertTrue(fake_session.committed)
        self.assertTrue(fake_session.flushed)
        self.assertEqual(result["name"], "香港主线路")
        self.assertEqual(result["url_masked"], "https://proxy.example.com/sub?token=se***en")
        self.assertNotIn("secret-token", result["url_masked"])
        self.assertTrue(result["is_active"])
        self.assertEqual(applier.applied_urls, ["https://proxy.example.com/sub?token=secret-token"])

    async def test_list_clash_addresses_never_returns_raw_url(self):
        service = ClashAddressService()
        fake_session = _ClashSession([_row(1)])

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch("backend.h5_backend.services.admin.clash_address_service.get_async_session", new=fake_get_async_session):
            result = await service.list_addresses()

        self.assertEqual(result["total"], 1)
        item = result["items"][0]
        self.assertNotIn("url", item)
        self.assertEqual(item["url_masked"], "https://proxy.example.com/sub?token=se***en")

    async def test_update_clash_address_keeps_existing_url_when_url_is_none(self):
        service = ClashAddressService()
        fake_session = _ClashSession([_row(1, is_active=False)])

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch(
            "backend.h5_backend.services.admin.clash_address_service.get_async_session",
            new=fake_get_async_session,
        ), patch(
            "backend.h5_backend.services.admin.clash_address_service.append_audit_log",
            AsyncMock(),
        ):
            result = await service.update_address(
                1,
                name="新名称",
                url=None,
                is_active=False,
                remark="新备注",
                actor="admin#1",
            )

        self.assertEqual(fake_session.rows[0].url, "https://proxy.example.com/sub?token=secret-token")
        self.assertFalse(result["is_active"])
        self.assertEqual(result["name"], "新名称")

    async def test_update_rejects_disabling_active_clash_address(self):
        service = ClashAddressService()
        fake_session = _ClashSession([_row(1, is_active=True)])

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch("backend.h5_backend.services.admin.clash_address_service.get_async_session", new=fake_get_async_session):
            with self.assertRaises(HTTPException) as raised:
                await service.update_address(
                    1,
                    name="主订阅",
                    url=None,
                    is_active=False,
                    remark="",
                    actor="admin#1",
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertFalse(fake_session.committed)

    async def test_update_active_clash_address_applies_new_url_before_commit(self):
        applier = _FakeClashApplier()
        service = ClashAddressService(applier=applier)
        fake_session = _ClashSession([_row(1, is_active=False)])

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch(
            "backend.h5_backend.services.admin.clash_address_service.get_async_session",
            new=fake_get_async_session,
        ), patch(
            "backend.h5_backend.services.admin.clash_address_service.append_audit_log",
            AsyncMock(),
        ):
            result = await service.update_address(
                1,
                name="新名称",
                url="https://proxy.example.com/new?token=new-secret",
                is_active=True,
                remark="",
                actor="admin#1",
            )

        self.assertTrue(fake_session.committed)
        self.assertTrue(result["is_active"])
        self.assertEqual(applier.applied_urls, ["https://proxy.example.com/new?token=new-secret"])

    async def test_activate_clash_address_turns_off_other_addresses(self):
        applier = _FakeClashApplier()
        service = ClashAddressService(applier=applier)
        first = _row(1, is_active=True)
        second = _row(2, name="备用订阅", is_active=False)
        fake_session = _ClashSession([first, second])

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch(
            "backend.h5_backend.services.admin.clash_address_service.get_async_session",
            new=fake_get_async_session,
        ), patch(
            "backend.h5_backend.services.admin.clash_address_service.append_audit_log",
            AsyncMock(),
        ):
            result = await service.activate_address(2, actor="admin#1")

        self.assertFalse(first.is_active)
        self.assertTrue(second.is_active)
        self.assertTrue(result["is_active"])
        self.assertEqual(applier.applied_urls, [second.url])

    async def test_activate_clash_address_rolls_back_when_apply_fails(self):
        service = ClashAddressService(applier=_FakeClashApplier(error=RuntimeError("sync failed")))
        first = _row(1, is_active=True)
        second = _row(2, name="备用订阅", is_active=False)
        fake_session = _ClashSession([first, second])

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch(
            "backend.h5_backend.services.admin.clash_address_service.get_async_session",
            new=fake_get_async_session,
        ), patch(
            "backend.h5_backend.services.admin.clash_address_service.append_audit_log",
            AsyncMock(),
        ):
            with self.assertRaises(RuntimeError):
                await service.activate_address(2, actor="admin#1")

        self.assertTrue(first.is_active)
        self.assertFalse(second.is_active)
        self.assertFalse(fake_session.committed)

    async def test_delete_missing_clash_address_returns_404(self):
        service = ClashAddressService()
        fake_session = _ClashSession()

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch("backend.h5_backend.services.admin.clash_address_service.get_async_session", new=fake_get_async_session):
            with self.assertRaises(HTTPException) as raised:
                await service.delete_address(99, actor="admin#1")

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "Clash 地址不存在")

    async def test_delete_active_clash_address_is_rejected(self):
        service = ClashAddressService()
        fake_session = _ClashSession([_row(1, is_active=True)])

        @asynccontextmanager
        async def fake_get_async_session():
            yield fake_session

        with patch("backend.h5_backend.services.admin.clash_address_service.get_async_session", new=fake_get_async_session):
            with self.assertRaises(HTTPException) as raised:
                await service.delete_address(1, actor="admin#1")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertFalse(fake_session.deleted)
        self.assertFalse(fake_session.committed)


if __name__ == "__main__":
    unittest.main()
