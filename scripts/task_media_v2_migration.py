"""Read-only inventory by default; V2 writes require the explicit migrate command."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.task_media.migration import inventory_v1_media_tasks, migrate_account_batch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Telegram task media V2 migration")
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("inventory", help="read-only V1 inventory")
    migrate = subcommands.add_parser("migrate", help="migrate one account serially")
    migrate.add_argument("--account-id", required=True)
    migrate.add_argument("--limit", type=int, default=50)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.command in {None, "inventory"}:
        result = await inventory_v1_media_tasks()
    else:
        result = await migrate_account_batch(account_id=args.account_id, limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
