"""CLI for versioned SQL migrations."""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from typing import Any

from backend.database.runtime.migration_manager import (
    apply_pending_migrations,
    list_migration_history,
    rollback_migrations,
)
from backend.database.runtime.session import engine


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


async def _run_apply() -> None:
    result = await apply_pending_migrations(engine)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))


async def _run_status(limit: int) -> None:
    rows = await list_migration_history(engine, limit=limit)
    print(json.dumps(rows, ensure_ascii=False, indent=2, default=_json_default))


async def _run_rollback(version: str | None, steps: int, dry_run: bool) -> None:
    rows = await rollback_migrations(engine, version=version, steps=steps, dry_run=dry_run)
    print(json.dumps(rows, ensure_ascii=False, indent=2, default=_json_default))


def main() -> None:
    parser = argparse.ArgumentParser(description="Database migration manager")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    subparsers.add_parser("apply", help="apply pending migrations")

    status_parser = subparsers.add_parser("status", help="show migration history")
    status_parser.add_argument("--limit", type=int, default=200)

    rollback_parser = subparsers.add_parser("rollback", help="rollback applied migrations")
    rollback_parser.add_argument("--version", type=str, default=None, help="rollback specific version")
    rollback_parser.add_argument("--steps", type=int, default=1, help="rollback latest N applied versions")
    rollback_parser.add_argument("--dry-run", action="store_true", help="show rollback plan only")

    args = parser.parse_args()
    if args.cmd == "apply":
        asyncio.run(_run_apply())
        return
    if args.cmd == "status":
        asyncio.run(_run_status(args.limit))
        return
    if args.cmd == "rollback":
        asyncio.run(_run_rollback(args.version, args.steps, args.dry_run))
        return


if __name__ == "__main__":
    main()
