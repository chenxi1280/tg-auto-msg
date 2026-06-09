"""Scheduler health snapshot helpers."""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

import redis.asyncio as redis
from sqlalchemy import text

from backend.config.core.settings import settings
from backend.database.runtime.session import get_async_session


async def _scan_processing_keys(redis_client: Any, pattern: str) -> list[str]:
    keys: list[str] = []
    cursor: Any = 0
    while True:
        cursor, batch = await redis_client.scan(cursor=cursor, match=pattern, count=200)
        keys.extend(str(key) for key in (batch or []))
        if int(cursor or 0) == 0:
            break
    return keys


async def collect_scheduler_health_snapshot(
    *,
    redis_client: Optional[Any] = None,
    session_factory: Callable = get_async_session,
    now_epoch: Optional[int] = None,
    stale_pending_seconds: int = 600,
) -> dict[str, Any]:
    """Return an immediate scheduler health snapshot.

    The incident class this detects is: DB has due scheduled tasks, but Redis
    has no pending/processing work, which means the producer/worker is stalled.
    """
    now = int(now_epoch if now_epoch is not None else time.time())
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT
                        extract(epoch from now())::bigint AS now_epoch,
                        count(*) FILTER (
                            WHERE enabled
                              AND trigger_mode = 'scheduled'
                              AND next_run_at <= extract(epoch from now())::bigint
                        ) AS due_scheduled,
                        count(*) FILTER (
                            WHERE enabled
                              AND trigger_mode = 'scheduled'
                        ) AS enabled_scheduled,
                        min(to_timestamp(next_run_at)) FILTER (
                            WHERE enabled
                              AND trigger_mode = 'scheduled'
                        ) AS earliest_next_run
                    FROM scheduled_message_tasks
                    """
                )
            )
        ).first()

    mapping = dict(row._mapping) if row is not None else {}
    db_now = int(mapping.get("now_epoch") or now)
    due_scheduled = int(mapping.get("due_scheduled") or 0)
    enabled_scheduled = int(mapping.get("enabled_scheduled") or 0)
    earliest_next_run = mapping.get("earliest_next_run")

    created_redis = False
    if redis_client is None:
        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        created_redis = True

    try:
        pending = await redis_client.zrange(
            "queue:tasks:pending",
            0,
            -1,
            withscores=True,
        )
        processing_keys = await _scan_processing_keys(
            redis_client,
            "queue:tasks:processing:*",
        )
    finally:
        if created_redis:
            await redis_client.aclose()

    pending_scores = [float(score) for _task_id, score in (pending or [])]
    pending_due_scores = [score for score in pending_scores if score <= db_now]
    oldest_pending_lag_seconds = (
        max(0, int(db_now - min(pending_due_scores))) if pending_due_scores else 0
    )
    processing_count = len(processing_keys)
    pending_count = len(pending_scores)

    issues: list[str] = []
    if due_scheduled > 0 and pending_count == 0 and processing_count == 0:
        issues.append("due_tasks_not_queued")
    if (
        oldest_pending_lag_seconds >= max(1, int(stale_pending_seconds or 600))
        and processing_count == 0
    ):
        issues.append("pending_tasks_stale")

    if hasattr(earliest_next_run, "isoformat"):
        earliest_next_run = earliest_next_run.isoformat()

    return {
        "status": "unhealthy" if issues else "healthy",
        "issues": issues,
        "now_epoch": db_now,
        "due_scheduled": due_scheduled,
        "enabled_scheduled": enabled_scheduled,
        "earliest_next_run": earliest_next_run,
        "pending_count": pending_count,
        "pending_due_count": len(pending_due_scores),
        "processing_count": processing_count,
        "oldest_pending_lag_seconds": oldest_pending_lag_seconds,
    }
