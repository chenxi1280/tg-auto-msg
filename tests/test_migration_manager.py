import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.database.runtime.migration_manager import MigrationFile, apply_pending_migrations


class _FakeConnection:
    def __init__(self):
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return None


class _FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def begin(self):
        yield self.connection


class MigrationManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_pending_migrations_sets_province_context_before_sql(self):
        connection = _FakeConnection()
        engine = _FakeEngine(connection)
        migration = MigrationFile(
            version="999",
            filename="999_test.sql",
            path=Path("sql/migrations/999_test.sql"),
            checksum="checksum",
            statements=["SELECT 1"],
            rollback_filename=None,
            rollback_path=None,
        )

        with patch(
            "backend.database.runtime.migration_manager._discover_migration_files",
            return_value=[migration],
        ), patch(
            "backend.database.runtime.migration_manager._ensure_schema_migrations_table",
            AsyncMock(),
        ), patch(
            "backend.database.runtime.migration_manager._get_migration_record",
            AsyncMock(return_value=None),
        ), patch(
            "backend.database.runtime.migration_manager._upsert_migration_record",
            AsyncMock(),
        ), patch(
            "backend.database.runtime.migration_manager.settings.province_code",
            "guangdong",
        ):
            result = await apply_pending_migrations(engine)

        self.assertEqual(result, {"total": 1, "applied": 1, "skipped": 0})
        executed_sql = [sql for sql, _ in connection.calls]
        self.assertTrue(any("set_config('app.province_code'" in sql for sql in executed_sql))
        set_config_index = next(i for i, (sql, _) in enumerate(connection.calls) if "set_config('app.province_code'" in sql)
        migration_index = next(i for i, (sql, _) in enumerate(connection.calls) if "SELECT 1" in sql)
        self.assertLess(set_config_index, migration_index)
        _, params = connection.calls[set_config_index]
        self.assertEqual(params, {"province_code": "guangdong"})
