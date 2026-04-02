"""Task lifecycle helpers for scheduler worker."""
from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy import select

from backend.database.schema.models import ScheduledMessageTask, TaskLog


def calculate_next_run(now: int, target_hour: int, interval_min: int) -> int:
    """Calculate next run timestamp (current implementation: fixed interval)."""
    del target_hour
    return now + interval_min * 60


def check_time_limit(task: ScheduledMessageTask, current_hour: int, now: int) -> tuple[bool, int | None]:
    """Check daily time-window limit. Returns (allowed, suggested_next_run)."""
    if task.day_start_hour is None or task.day_end_hour is None:
        return True, None

    if task.day_start_hour <= task.day_end_hour:
        in_time_range = task.day_start_hour <= current_hour < task.day_end_hour
    else:
        in_time_range = current_hour >= task.day_start_hour or current_hour < task.day_end_hour

    if in_time_range:
        return True, None

    logger.debug(f"任务 {task.task_id} 不在时段内，跳过")
    next_hour = task.day_start_hour if current_hour >= task.day_end_hour else current_hour
    next_run = calculate_next_run(now, next_hour, task.repeat_interval_min)
    return False, next_run


async def handle_task_success(
    *,
    session,
    task: ScheduledMessageTask,
    message_id: int,
    target_message_ids: dict[tuple[str, int], int] | None,
    now: int,
    account_manager,
) -> None:
    """Persist task success side-effects and schedule next run."""
    log = TaskLog(task_id=task.task_id, result="success", message_id=message_id)
    session.add(log)

    if target_message_ids:
        from backend.scheduler.core.task_execution import update_task_target_last_message_ids

        update_task_target_last_message_ids(
            task,
            target_message_ids=target_message_ids,
        )
    else:
        task.last_sent_message_id = message_id
    task.failure_count = 0
    task.next_run_at = now + task.repeat_interval_min * 60

    if task.account_id:
        await account_manager.increment_messages_sent(task.account_id)

    await session.commit()


async def handle_task_failure(
    *,
    session,
    task: ScheduledMessageTask,
    error_message: str,
    max_failure_count: int,
) -> None:
    """Persist task failure side-effects and apply auto-disable policy."""
    log = TaskLog(task_id=task.task_id, result="failed", error_message=error_message)
    session.add(log)

    task.failure_count += 1

    now = int(datetime.now().timestamp())
    retry_after = max(30, task.repeat_interval_min * 60)
    task.next_run_at = now + retry_after

    if task.failure_count >= max_failure_count:
        task.enabled = False
        logger.warning(
            f"任务 {task.task_id} 连续失败 {task.failure_count} 次，自动禁用"
        )

    await session.commit()


async def suspend_account_tasks(
    *,
    session,
    account_id: str,
    suspend_until: int,
    reason: str,
) -> None:
    """Suspend all enabled tasks for one account until specified timestamp."""
    result = await session.execute(
        select(ScheduledMessageTask).where(
            ScheduledMessageTask.account_id == account_id,
            ScheduledMessageTask.enabled == True,
        )
    )
    tasks = result.scalars().all()
    for task in tasks:
        task.next_run_at = max(task.next_run_at or 0, suspend_until)

    await session.commit()
    logger.warning(
        f"账号 {account_id} 任务已暂停到 {suspend_until}，原因: {reason}，影响任务数: {len(tasks)}"
    )
