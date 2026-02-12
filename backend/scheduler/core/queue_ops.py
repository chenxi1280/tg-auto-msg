"""Queue operations for scheduler producer/consumer flow."""
from __future__ import annotations

import random
from typing import Optional

from sqlalchemy import select

from backend.database.schema.models import ScheduledMessageTask
from backend.database.runtime.session import get_async_session


async def enqueue_due_tasks(
    *,
    now: int,
    redis_client,
    queue_key: str,
    account_manager,
    jitter_range: int,
    urgent_priority_threshold: int,
) -> None:
    """Load due tasks from DB and enqueue into Redis sorted-set."""
    async with get_async_session() as session:
        query = (
            select(ScheduledMessageTask)
            .where(
                ScheduledMessageTask.enabled == True,
                ScheduledMessageTask.next_run_at.isnot(None),
                ScheduledMessageTask.next_run_at <= now,
            )
            .order_by(
                ScheduledMessageTask.priority.desc(),
                ScheduledMessageTask.next_run_at.asc(),
            )
            .limit(100)
        )

        result = await session.execute(query)
        tasks = result.scalars().all()

        for task in tasks:
            delay_min = max(0, int(getattr(task, "delay_min_seconds", 0) or 0))
            delay_max = max(delay_min, int(getattr(task, "delay_max_seconds", 0) or 0))

            if delay_max > 0:
                upper = min(delay_max, jitter_range)
                lower = min(delay_min, upper)
                jitter = random.randint(lower, upper)
            else:
                jitter_base = max(0, int(getattr(task, "jitter_seconds", 0) or 0))
                jitter = random.randint(0, min(jitter_base, jitter_range))

            if (task.priority or 0) >= urgent_priority_threshold:
                jitter = min(jitter, 3)

            if task.account_id:
                account = await account_manager.get_account(task.account_id)
                if account and account.weight < 100:
                    extra_max = min(120, (100 - account.weight) * 2)
                    jitter += random.randint(0, extra_max)

            execution_time = now + jitter
            existing_score = await redis_client.zscore(queue_key, task.task_id)
            if existing_score is None:
                await redis_client.zadd(queue_key, {task.task_id: execution_time})
            elif execution_time < int(existing_score):
                await redis_client.zadd(queue_key, {task.task_id: execution_time})


async def get_pending_tasks(
    *,
    now: int,
    redis_client,
    queue_key: str,
    batch_size: int = 50,
) -> list[ScheduledMessageTask]:
    """Fetch due tasks from Redis queue and load active task records from DB."""
    task_ids = await redis_client.zrangebyscore(
        queue_key,
        min=0,
        max=now,
        start=0,
        num=batch_size,
    )
    if not task_ids:
        return []

    await redis_client.zrem(queue_key, *task_ids)

    tasks: list[ScheduledMessageTask] = []
    async with get_async_session() as session:
        for task_id in task_ids:
            result = await session.execute(
                select(ScheduledMessageTask).where(
                    ScheduledMessageTask.task_id == task_id
                )
            )
            task = result.scalar_one_or_none()
            if task and task.enabled:
                tasks.append(task)
    return tasks


async def ensure_redis_connection(redis_client, redis_url: str):
    """Ensure Redis connection is alive; reconnect if needed."""
    if redis_client is None:
        import redis.asyncio as redis

        redis_client = redis.from_url(redis_url, decode_responses=True)

    try:
        await redis_client.ping()
        return redis_client
    except Exception:
        pass

    try:
        await redis_client.close()
    except Exception:
        pass

    import redis.asyncio as redis

    redis_client = redis.from_url(redis_url, decode_responses=True)
    await redis_client.ping()
    return redis_client
