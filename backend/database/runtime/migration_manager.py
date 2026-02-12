"""Versioned SQL migration manager with execution records and rollback support."""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


SQL_DIR = Path(__file__).resolve().parents[3] / "sql"
MIGRATIONS_DIR = SQL_DIR / "migrations"
ROLLBACK_DIR = MIGRATIONS_DIR / "rollback"
MIGRATION_STATEMENT_MARKER = "-- @statement"
VERSION_RE = re.compile(r"^(\d+)_.*\.sql$")


@dataclass(frozen=True)
class MigrationFile:
    """Migration file metadata."""

    version: str
    filename: str
    path: Path
    checksum: str
    statements: List[str]
    rollback_filename: Optional[str]
    rollback_path: Optional[Path]


def _split_sql_statements(sql_text: str) -> List[str]:
    """Split SQL string into executable statements while preserving quoted blocks."""
    sql_text = (sql_text or "").strip()
    if not sql_text:
        return []

    statements: List[str] = []
    buf: List[str] = []
    i = 0
    n = len(sql_text)
    in_single = False
    in_double = False
    dollar_tag: Optional[str] = None

    while i < n:
        ch = sql_text[i]

        if dollar_tag:
            if sql_text.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            buf.append(ch)
            i += 1
            continue

        if not in_single and not in_double and ch == "$":
            j = i + 1
            while j < n and (sql_text[j].isalnum() or sql_text[j] == "_"):
                j += 1
            if j < n and sql_text[j] == "$":
                tag = sql_text[i : j + 1]
                dollar_tag = tag
                buf.append(tag)
                i = j + 1
                continue

        if ch == "'" and not in_double:
            if in_single and i + 1 < n and sql_text[i + 1] == "'":
                buf.append("''")
                i += 2
                continue
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue

        if ch == ";" and not in_single and not in_double:
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def _cleanup_chunk(raw_chunk: str) -> str:
    lines: List[str] = []
    for line in raw_chunk.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _parse_sql_file(path: Path) -> List[str]:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []

    statements: List[str] = []
    if MIGRATION_STATEMENT_MARKER in content:
        chunks = content.split(MIGRATION_STATEMENT_MARKER)
        for chunk in chunks:
            stmt = _cleanup_chunk(chunk)
            if stmt:
                statements.extend(_split_sql_statements(stmt))
    else:
        stmt = _cleanup_chunk(content)
        if stmt:
            statements.extend(_split_sql_statements(stmt))
    return statements


def _resolve_rollback_file(version: str, migration_path: Path) -> tuple[Optional[str], Optional[Path]]:
    # 1) 同目录：001_xxx.down.sql
    same_dir = migration_path.with_suffix(".down.sql")
    if same_dir.exists():
        return (same_dir.name, same_dir)

    # 2) rollback 目录：rollback/001_xxx.down.sql
    if ROLLBACK_DIR.exists():
        candidates = sorted(ROLLBACK_DIR.glob(f"{version}_*.down.sql"))
        if candidates:
            rb = candidates[0]
            rel = rb.relative_to(MIGRATIONS_DIR).as_posix()
            return (rel, rb)

    return (None, None)


def _discover_migration_files() -> List[MigrationFile]:
    if not MIGRATIONS_DIR.exists():
        logger.warning(f"迁移目录不存在，跳过 SQL 迁移: {MIGRATIONS_DIR}")
        return []

    files = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name.endswith(".down.sql"):
            continue
        match = VERSION_RE.match(path.name)
        if not match:
            continue
        version = match.group(1)
        content = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        statements = _parse_sql_file(path)
        rollback_filename, rollback_path = _resolve_rollback_file(version, path)
        files.append(
            MigrationFile(
                version=version,
                filename=path.name,
                path=path,
                checksum=checksum,
                statements=statements,
                rollback_filename=rollback_filename,
                rollback_path=rollback_path,
            )
        )
    return files


async def _ensure_schema_migrations_table(conn: AsyncConnection) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(64) PRIMARY KEY,
                filename VARCHAR(255) NOT NULL,
                checksum VARCHAR(64) NOT NULL,
                status VARCHAR(20) NOT NULL,
                applied_at TIMESTAMP,
                execution_ms INTEGER,
                statements_count INTEGER DEFAULT 0 NOT NULL,
                error_message TEXT,
                rollback_file VARCHAR(255),
                rollback_applied_at TIMESTAMP,
                rollback_status VARCHAR(20),
                rollback_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS idx_schema_migrations_status
            ON schema_migrations(status, applied_at DESC)
            """
        )
    )


async def _get_migration_record(conn: AsyncConnection, version: str) -> Optional[Dict[str, Any]]:
    result = await conn.execute(
        text(
            """
            SELECT version, filename, checksum, status, applied_at, rollback_file, rollback_status
            FROM schema_migrations
            WHERE version = :version
            """
        ),
        {"version": str(version)},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def _upsert_migration_record(
    conn: AsyncConnection,
    *,
    version: str,
    filename: str,
    checksum: str,
    status: str,
    applied_at: Optional[datetime],
    execution_ms: Optional[int],
    statements_count: int,
    error_message: Optional[str],
    rollback_file: Optional[str],
    rollback_applied_at: Optional[datetime],
    rollback_status: Optional[str],
    rollback_error: Optional[str],
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO schema_migrations (
                version,
                filename,
                checksum,
                status,
                applied_at,
                execution_ms,
                statements_count,
                error_message,
                rollback_file,
                rollback_applied_at,
                rollback_status,
                rollback_error
            ) VALUES (
                :version,
                :filename,
                :checksum,
                :status,
                :applied_at,
                :execution_ms,
                :statements_count,
                :error_message,
                :rollback_file,
                :rollback_applied_at,
                :rollback_status,
                :rollback_error
            )
            ON CONFLICT (version) DO UPDATE SET
                filename = EXCLUDED.filename,
                checksum = EXCLUDED.checksum,
                status = EXCLUDED.status,
                applied_at = EXCLUDED.applied_at,
                execution_ms = EXCLUDED.execution_ms,
                statements_count = EXCLUDED.statements_count,
                error_message = EXCLUDED.error_message,
                rollback_file = EXCLUDED.rollback_file,
                rollback_applied_at = EXCLUDED.rollback_applied_at,
                rollback_status = EXCLUDED.rollback_status,
                rollback_error = EXCLUDED.rollback_error,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {
            "version": str(version),
            "filename": filename,
            "checksum": checksum,
            "status": status,
            "applied_at": applied_at,
            "execution_ms": execution_ms,
            "statements_count": int(statements_count),
            "error_message": error_message,
            "rollback_file": rollback_file,
            "rollback_applied_at": rollback_applied_at,
            "rollback_status": rollback_status,
            "rollback_error": rollback_error,
        },
    )


async def apply_pending_migrations(engine: AsyncEngine) -> Dict[str, int]:
    """Apply pending migrations with version check and execution records."""
    migrations = _discover_migration_files()
    if not migrations:
        return {"total": 0, "applied": 0, "skipped": 0}

    async with engine.begin() as conn:
        await _ensure_schema_migrations_table(conn)

    applied = 0
    skipped = 0

    for migration in migrations:
        async with engine.begin() as conn:
            await _ensure_schema_migrations_table(conn)
            existing = await _get_migration_record(conn, migration.version)
            if existing and existing.get("status") == "applied":
                if str(existing.get("checksum") or "") != migration.checksum:
                    raise RuntimeError(
                        "迁移文件校验失败，数据库已应用版本与当前文件不一致: "
                        f"version={migration.version}, file={migration.filename}"
                    )
                skipped += 1
                continue

        start = time.perf_counter()
        executed_count = 0
        error: Optional[Exception] = None
        try:
            async with engine.begin() as conn:
                await _ensure_schema_migrations_table(conn)
                for stmt in migration.statements:
                    await conn.execute(text(stmt))
                    executed_count += 1

                elapsed_ms = int((time.perf_counter() - start) * 1000)
                await _upsert_migration_record(
                    conn,
                    version=migration.version,
                    filename=migration.filename,
                    checksum=migration.checksum,
                    status="applied",
                    applied_at=datetime.now(),
                    execution_ms=elapsed_ms,
                    statements_count=executed_count,
                    error_message=None,
                    rollback_file=migration.rollback_filename,
                    rollback_applied_at=None,
                    rollback_status=None,
                    rollback_error=None,
                )
                applied += 1
        except Exception as exc:
            error = exc

        if error is not None:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            async with engine.begin() as conn:
                await _ensure_schema_migrations_table(conn)
                await _upsert_migration_record(
                    conn,
                    version=migration.version,
                    filename=migration.filename,
                    checksum=migration.checksum,
                    status="failed",
                    applied_at=None,
                    execution_ms=elapsed_ms,
                    statements_count=executed_count,
                    error_message=str(error),
                    rollback_file=migration.rollback_filename,
                    rollback_applied_at=None,
                    rollback_status=None,
                    rollback_error=None,
                )
            raise RuntimeError(
                f"迁移执行失败: version={migration.version}, file={migration.filename}, error={error}"
            ) from error

    return {"total": len(migrations), "applied": applied, "skipped": skipped}


def _parse_rollback_file(path: Path) -> List[str]:
    if not path.exists():
        return []
    return _parse_sql_file(path)


async def list_migration_history(engine: AsyncEngine, limit: int = 200) -> List[Dict[str, Any]]:
    """Return migration history rows ordered by newest version."""
    limit = max(1, min(1000, int(limit)))
    async with engine.begin() as conn:
        await _ensure_schema_migrations_table(conn)
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT
                        version,
                        filename,
                        checksum,
                        status,
                        applied_at,
                        execution_ms,
                        statements_count,
                        error_message,
                        rollback_file,
                        rollback_applied_at,
                        rollback_status,
                        rollback_error,
                        created_at,
                        updated_at
                    FROM schema_migrations
                    ORDER BY CAST(version AS INTEGER) DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
        ).mappings().all()
        return [dict(r) for r in rows]


async def rollback_migrations(
    engine: AsyncEngine,
    *,
    version: Optional[str] = None,
    steps: int = 1,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """
    Rollback migrations using paired *.down.sql files.

    Strategy:
    - By `version`: rollback this version only.
    - By `steps`: rollback latest N applied versions.
    """
    steps = max(1, int(steps))
    async with engine.begin() as conn:
        await _ensure_schema_migrations_table(conn)
        if version:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT version, filename, checksum, rollback_file, applied_at, execution_ms, statements_count
                        FROM schema_migrations
                        WHERE version = :version
                          AND status = 'applied'
                        """
                    ),
                    {"version": str(version)},
                )
            ).mappings().all()
        else:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT version, filename, checksum, rollback_file, applied_at, execution_ms, statements_count
                        FROM schema_migrations
                        WHERE status = 'applied'
                        ORDER BY CAST(version AS INTEGER) DESC
                        LIMIT :steps
                        """
                    ),
                    {"steps": steps},
                )
            ).mappings().all()

    candidates = [dict(r) for r in rows]
    if not candidates:
        raise RuntimeError("没有可回滚的已应用迁移")

    rolled: List[Dict[str, Any]] = []
    for row in candidates:
        rollback_file = row.get("rollback_file")
        rollback_path = None
        if rollback_file:
            rollback_path = MIGRATIONS_DIR / str(rollback_file)
        if rollback_path is None or not rollback_path.exists():
            msg = (
                "缺少回滚文件，无法自动回滚: "
                f"version={row['version']}, expected={rollback_file or 'N/A'}"
            )
            async with engine.begin() as conn:
                await _ensure_schema_migrations_table(conn)
                await _upsert_migration_record(
                    conn,
                    version=str(row["version"]),
                    filename=str(row["filename"]),
                    checksum=str(row.get("checksum") or ""),
                    status="applied",
                    applied_at=row.get("applied_at"),
                    execution_ms=row.get("execution_ms"),
                    statements_count=int(row.get("statements_count") or 0),
                    error_message=None,
                    rollback_file=rollback_file,
                    rollback_applied_at=None,
                    rollback_status="missing",
                    rollback_error=msg,
                )
            raise RuntimeError(msg)

        statements = _parse_rollback_file(rollback_path)
        if dry_run:
            rolled.append(
                {
                    "version": str(row["version"]),
                    "filename": str(row["filename"]),
                    "rollback_file": str(rollback_file),
                    "statements_count": len(statements),
                    "dry_run": True,
                }
            )
            continue

        start = time.perf_counter()
        error: Optional[Exception] = None
        executed = 0
        try:
            async with engine.begin() as conn:
                await _ensure_schema_migrations_table(conn)
                for stmt in statements:
                    await conn.execute(text(stmt))
                    executed += 1
                await _upsert_migration_record(
                    conn,
                    version=str(row["version"]),
                    filename=str(row["filename"]),
                    checksum=str(row.get("checksum") or ""),
                    status="rolled_back",
                    applied_at=None,
                    execution_ms=int((time.perf_counter() - start) * 1000),
                    statements_count=executed,
                    error_message=None,
                    rollback_file=str(rollback_file),
                    rollback_applied_at=datetime.now(),
                    rollback_status="success",
                    rollback_error=None,
                )
        except Exception as exc:
            error = exc

        if error is not None:
            async with engine.begin() as conn:
                await _ensure_schema_migrations_table(conn)
                await _upsert_migration_record(
                    conn,
                    version=str(row["version"]),
                    filename=str(row["filename"]),
                    checksum=str(row.get("checksum") or ""),
                    status="applied",
                    applied_at=row.get("applied_at"),
                    execution_ms=row.get("execution_ms"),
                    statements_count=int(row.get("statements_count") or 0),
                    error_message=None,
                    rollback_file=str(rollback_file),
                    rollback_applied_at=None,
                    rollback_status="failed",
                    rollback_error=str(error),
                )
            raise RuntimeError(
                f"回滚失败: version={row['version']}, rollback={rollback_file}, error={error}"
            ) from error

        rolled.append(
            {
                "version": str(row["version"]),
                "filename": str(row["filename"]),
                "rollback_file": str(rollback_file),
                "statements_count": executed,
                "dry_run": False,
            }
        )

    return rolled
