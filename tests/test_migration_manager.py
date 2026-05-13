import io
import unittest
from contextlib import asynccontextmanager
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.database.runtime import migration_cli
from backend.database.runtime.migration_manager import MigrationFile, apply_pending_migrations, rollback_migrations


class _FakeConnection:
    def __init__(self):
        self.calls = []
        self.query_rows = []
        self.run_sync_calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        sql = str(statement).lower()
        if "from schema_migrations" in sql:
            return _FakeMappingsResult(self.query_rows)
        return None

    async def run_sync(self, fn):
        self.run_sync_calls.append(fn)


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def begin(self):
        yield self.connection


class MigrationManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_migration_cli_apply_bootstraps_model_tables_before_migrations(self):
        connection = _FakeConnection()
        engine = _FakeEngine(connection)
        calls = []

        async def fake_run_sync(fn):
            connection.run_sync_calls.append(fn)
            calls.append("create_all")

        async def fake_apply_pending_migrations(received_engine):
            self.assertIs(received_engine, engine)
            calls.append("apply_migrations")
            return {"total": 1, "applied": 1, "skipped": 0}

        connection.run_sync = fake_run_sync
        with patch.object(migration_cli, "engine", engine), patch.object(
            migration_cli,
            "apply_pending_migrations",
            fake_apply_pending_migrations,
        ):
            with redirect_stdout(io.StringIO()):
                await migration_cli._run_apply()

        self.assertEqual(calls, ["create_all", "apply_migrations"])
        self.assertEqual(connection.run_sync_calls, [migration_cli.Base.metadata.create_all])

    async def test_apply_pending_migrations_accepts_legacy_checksum_for_023(self):
        connection = _FakeConnection()
        engine = _FakeEngine(connection)
        migration = MigrationFile(
            version="023",
            filename="023_backfill_legacy_cards_to_super_admin.sql",
            path=Path("sql/migrations/023_backfill_legacy_cards_to_super_admin.sql"),
            checksum="170160c58d97d0492aa3660b447ae1a3f2c6fd6f679da931bcc37509cc0114eb",
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
            AsyncMock(return_value={"status": "applied", "checksum": "c93877d366dea1ab1d54fe637afb04eb4af6e2cf370d10b201c48e1afa3776ba"}),
        ):
            result = await apply_pending_migrations(engine)

        self.assertEqual(result, {"total": 1, "applied": 0, "skipped": 1})
        self.assertFalse(any("SELECT 1" in sql for sql, _ in connection.calls))

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

    async def test_rollback_migrations_sets_province_context_before_sql(self):
        connection = _FakeConnection()
        connection.query_rows = [
            {
                "version": "999",
                "filename": "999_test.sql",
                "checksum": "checksum",
                "rollback_file": "999_test.down.sql",
                "applied_at": None,
                "execution_ms": 1,
                "statements_count": 1,
            }
        ]
        engine = _FakeEngine(connection)

        with patch(
            "backend.database.runtime.migration_manager._ensure_schema_migrations_table",
            AsyncMock(),
        ), patch(
            "backend.database.runtime.migration_manager._upsert_migration_record",
            AsyncMock(),
        ), patch(
            "backend.database.runtime.migration_manager.settings.province_code",
            "guangdong",
        ), patch(
            "backend.database.runtime.migration_manager._parse_rollback_file",
            return_value=["SELECT 2"],
        ), patch(
            "pathlib.Path.exists",
            return_value=True,
        ):
            result = await rollback_migrations(engine, steps=1)

        self.assertEqual(len(result), 1)
        executed_sql = [sql for sql, _ in connection.calls]
        self.assertTrue(any("set_config('app.province_code'" in sql for sql in executed_sql))
        set_config_index = next(i for i, (sql, _) in enumerate(connection.calls) if "set_config('app.province_code'" in sql)
        rollback_index = next(i for i, (sql, _) in enumerate(connection.calls) if "SELECT 2" in sql)
        self.assertLess(set_config_index, rollback_index)
        _, params = connection.calls[set_config_index]
        self.assertEqual(params, {"province_code": "guangdong"})
