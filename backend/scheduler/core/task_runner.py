"""Shared one-shot task execution service for scheduler, bot, and API."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import select
from telethon.errors import FloodWaitError, PeerFloodError

from backend.bot.account.manager import get_account_manager
from backend.bot.account.reauth import is_reauth_required_account
from backend.bot.circuit.breaker import FloodWaitAction, get_circuit_breaker
from backend.bot.resources.manager import get_resource_manager
from backend.config.core.settings import settings
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    ScheduledMessageTask,
    TaskTriggerSource,
)
from backend.h5_backend.services.licensing.service import (
    disable_tasks_for_account_if_unlicensed,
    get_account_authorization_summary,
)
from backend.scheduler.core.task_execution import (
    collect_task_targets,
    count_configured_task_targets,
    get_target_last_message_id,
    resolve_send_target,
    send_with_protections,
)
from backend.scheduler.core.task_issue_classifier import classify_task_send_error
from backend.scheduler.core.task_issue_state import (
    record_task_target_send_issue,
    resolve_task_target_send_issue,
    update_task_target_failure_metadata,
    update_task_target_success_metadata,
)
from backend.scheduler.core.task_lifecycle import (
    check_time_limit,
    handle_task_failure,
    handle_task_success,
    suspend_account_tasks,
)


@dataclass
class TaskExecutionSummary:
    """User-facing summary for one execution attempt."""

    task_id: str
    title: str
    account_id: Optional[str]
    trigger_source: str
    status: str
    total_targets: int
    success_count: int
    failed_count: int
    error_summary: Optional[str]
    executed_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def _build_summary(
    *,
    task: ScheduledMessageTask,
    trigger_source: str,
    status: str,
    total_targets: int,
    success_count: int,
    failed_count: int,
    error_summary: Optional[str] = None,
) -> TaskExecutionSummary:
    return TaskExecutionSummary(
        task_id=str(task.task_id),
        title=str(task.title or ""),
        account_id=str(task.account_id) if task.account_id else None,
        trigger_source=str(trigger_source),
        status=status,
        total_targets=max(0, int(total_targets)),
        success_count=max(0, int(success_count)),
        failed_count=max(0, int(failed_count)),
        error_summary=str(error_summary).strip() if error_summary else None,
        executed_at=datetime.now().isoformat(),
    )


async def execute_task_once(
    task_id: str,
    *,
    trigger_source: str = TaskTriggerSource.SCHEDULER.value,
    advance_schedule: bool = True,
    respect_schedule_constraints: bool = True,
) -> TaskExecutionSummary:
    """
    Execute one task exactly once.

    `advance_schedule=True` is for scheduler-triggered runs.
    `advance_schedule=False` is for ad-hoc bot/API manual runs.
    """

    now = int(datetime.now().timestamp())
    current_hour = datetime.now().hour
    account_manager = get_account_manager()
    resource_manager = get_resource_manager()
    circuit_breaker = get_circuit_breaker()

    async with get_async_session() as session:
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        if not task.enabled:
            raise HTTPException(status_code=400, detail="任务已禁用，无法执行")

        if task.account_id:
            auth_summary = await get_account_authorization_summary(task.account_id, session=session)
            if not auth_summary.can_create_tasks:
                disabled_count = await disable_tasks_for_account_if_unlicensed(
                    account_id=task.account_id,
                    session=session,
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"当前执行账号已无有效授权，已停用该账号下任务 {disabled_count} 条",
                )

        if task.account_id:
            account = await account_manager.get_account(task.account_id)
            if account and is_reauth_required_account(account):
                raise HTTPException(status_code=400, detail="当前执行账号需要重新绑定后才能发送")

        if advance_schedule and task.next_run_at is None:
            start_at_ts = int(task.start_at or 0)
            task.next_run_at = max(now, start_at_ts) if start_at_ts > 0 else now
            await session.commit()

        if advance_schedule and task.next_run_at and task.next_run_at > now:
            return _build_summary(
                task=task,
                trigger_source=trigger_source,
                status="skipped",
                total_targets=0,
                success_count=0,
                failed_count=0,
                error_summary="任务尚未到执行时间",
            )

        target_specs = collect_task_targets(task)
        if not target_specs:
            configured_target_count = count_configured_task_targets(task)
            if configured_target_count > 0:
                if advance_schedule:
                    task.next_run_at = now + task.repeat_interval_min * 60
                    await session.commit()
                    return _build_summary(
                        task=task,
                        trigger_source=trigger_source,
                        status="skipped",
                        total_targets=configured_target_count,
                        success_count=0,
                        failed_count=configured_target_count,
                        error_summary="当前没有可发送目标（目标可能已被系统暂停）",
                    )
                await handle_task_failure(
                    session=session,
                    task=task,
                    error_message="当前没有可发送目标（目标可能已被系统暂停）",
                    max_failure_count=settings.max_failure_count,
                    trigger_source=trigger_source,
                    advance_schedule=False,
                    apply_disable_policy=False,
                )
                return _build_summary(
                    task=task,
                    trigger_source=trigger_source,
                    status="failed",
                    total_targets=configured_target_count,
                    success_count=0,
                    failed_count=configured_target_count,
                    error_summary="当前没有可发送目标（目标可能已被系统暂停）",
                )

            await handle_task_failure(
                session=session,
                task=task,
                error_message="缺少目标 Peer ID",
                max_failure_count=settings.max_failure_count,
                trigger_source=trigger_source,
                advance_schedule=advance_schedule,
                apply_disable_policy=advance_schedule,
            )
            return _build_summary(
                task=task,
                trigger_source=trigger_source,
                status="failed",
                total_targets=0,
                success_count=0,
                failed_count=0,
                error_summary="缺少目标 Peer ID",
            )

        if task.account_id:
            await account_manager.ensure_account_proxy(task.account_id)
            client = await account_manager.get_client(task.account_id)
            account_id_str = task.account_id
            if not client:
                await handle_task_failure(
                    session=session,
                    task=task,
                    error_message="无法获取账号客户端",
                    max_failure_count=settings.max_failure_count,
                    trigger_source=trigger_source,
                    advance_schedule=advance_schedule,
                    apply_disable_policy=advance_schedule,
                )
                return _build_summary(
                    task=task,
                    trigger_source=trigger_source,
                    status="failed",
                    total_targets=len(target_specs),
                    success_count=0,
                    failed_count=len(target_specs),
                    error_summary="无法获取账号客户端",
                )
        else:
            from backend.bot.client_runtime.manager import userbot_client

            client = userbot_client
            account_id_str = "default"

        if respect_schedule_constraints:
            if task.start_at and now < task.start_at:
                if advance_schedule:
                    task.next_run_at = max(task.next_run_at or 0, task.start_at)
                    await session.commit()
                return _build_summary(
                    task=task,
                    trigger_source=trigger_source,
                    status="skipped",
                    total_targets=len(target_specs),
                    success_count=0,
                    failed_count=0,
                    error_summary="任务未到开始时间",
                )

            if task.end_at and now > task.end_at:
                if advance_schedule:
                    task.enabled = False
                    await session.commit()
                return _build_summary(
                    task=task,
                    trigger_source=trigger_source,
                    status="skipped",
                    total_targets=len(target_specs),
                    success_count=0,
                    failed_count=0,
                    error_summary="任务已超过结束时间",
                )

            allowed, next_run_at = check_time_limit(task, current_hour, now)
            if not allowed:
                if advance_schedule and next_run_at is not None:
                    task.next_run_at = next_run_at
                    await session.commit()
                return _build_summary(
                    task=task,
                    trigger_source=trigger_source,
                    status="skipped",
                    total_targets=len(target_specs),
                    success_count=0,
                    failed_count=0,
                    error_summary="当前不在任务允许的执行时段内",
                )

        try:
            last_message_id: Optional[int] = None
            send_errors: list[str] = []
            partial_failure_summaries: list[str] = []
            target_message_ids: dict[tuple[str, int], int] = {}

            for spec in target_specs:
                target_peer_id = int(spec["peer_id"])
                target_peer_type = spec.get("peer_type")
                target_access_hash = spec.get("access_hash")
                target_title = spec.get("title")
                normalized_target_peer_type = str(
                    target_peer_type or task.target_peer_type or "user"
                ).strip().lower()
                target_label = target_title or f"{normalized_target_peer_type}:{target_peer_id}"
                previous_message_id = get_target_last_message_id(
                    task,
                    target_peer_id=target_peer_id,
                    target_peer_type=target_peer_type,
                )

                try:
                    send_target = await resolve_send_target(
                        client=client,
                        task=task,
                        target_peer_id=target_peer_id,
                        target_peer_type=target_peer_type,
                        target_access_hash=target_access_hash,
                        resource_manager=resource_manager,
                    )
                    message_id = await send_with_protections(
                        client=client,
                        task=task,
                        send_target=send_target,
                        lock_peer_id=target_peer_id,
                        account_id=account_id_str,
                        previous_message_id=previous_message_id,
                        media_ref_prefix="tgmsg://",
                    )
                except (FloodWaitError, PeerFloodError):
                    raise
                except Exception as send_err:
                    classification = classify_task_send_error(send_err)
                    send_errors.append(
                        f"peer={target_peer_id}: {type(send_err).__name__}: {send_err}"
                    )
                    partial_failure_summaries.append(
                        f"{target_label}: {classification.user_message}"
                    )
                    await record_task_target_send_issue(
                        session=session,
                        task=task,
                        peer_id=target_peer_id,
                        peer_type=normalized_target_peer_type,
                        peer_title=str(target_title).strip() if target_title else None,
                        classification=classification,
                    )
                    update_task_target_failure_metadata(
                        task,
                        peer_id=target_peer_id,
                        peer_type=normalized_target_peer_type,
                        peer_title=str(target_title).strip() if target_title else None,
                        error_type=classification.error_type,
                        error_message=classification.user_message,
                        suspension_reason=classification.suspension_reason,
                    )
                    logger.warning(
                        "任务 {} 发送目标失败: peer={}, error={}: {}",
                        task_id,
                        target_peer_id,
                        type(send_err).__name__,
                        send_err,
                    )
                    continue

                if message_id:
                    await resolve_task_target_send_issue(
                        session=session,
                        task=task,
                        peer_id=target_peer_id,
                        peer_type=normalized_target_peer_type,
                    )
                    update_task_target_success_metadata(
                        task,
                        peer_id=target_peer_id,
                        peer_type=normalized_target_peer_type,
                    )
                    last_message_id = message_id
                    target_message_ids[(normalized_target_peer_type, target_peer_id)] = message_id
                else:
                    send_errors.append(f"peer={target_peer_id}: send_message returned empty")
                    empty_result_error = RuntimeError("send_message returned empty")
                    classification = classify_task_send_error(empty_result_error)
                    partial_failure_summaries.append(
                        f"{target_label}: {classification.user_message}"
                    )
                    await record_task_target_send_issue(
                        session=session,
                        task=task,
                        peer_id=target_peer_id,
                        peer_type=normalized_target_peer_type,
                        peer_title=str(target_title).strip() if target_title else None,
                        classification=classification,
                    )
                    update_task_target_failure_metadata(
                        task,
                        peer_id=target_peer_id,
                        peer_type=normalized_target_peer_type,
                        peer_title=str(target_title).strip() if target_title else None,
                        error_type=classification.error_type,
                        error_message=classification.user_message,
                        suspension_reason=classification.suspension_reason,
                    )

            success_count = len(target_message_ids)
            failed_count = len(target_specs) - success_count

            if last_message_id:
                partial_failure_summary = None
                if send_errors:
                    partial_failure_summary = (
                        f"部分目标发送失败，共 {len(send_errors)} 个；"
                        f"示例：{partial_failure_summaries[0]}"
                    )
                await handle_task_success(
                    session=session,
                    task=task,
                    message_id=last_message_id,
                    target_message_ids=target_message_ids,
                    error_message=partial_failure_summary,
                    now=now,
                    account_manager=account_manager,
                    trigger_source=trigger_source,
                    advance_schedule=advance_schedule,
                )
                if send_errors:
                    logger.warning(
                        "任务 {} 部分目标发送失败: {} 个; 错误示例: {}",
                        task_id,
                        len(send_errors),
                        send_errors[0],
                    )
                return _build_summary(
                    task=task,
                    trigger_source=trigger_source,
                    status="partial_success" if failed_count else "success",
                    total_targets=len(target_specs),
                    success_count=success_count,
                    failed_count=failed_count,
                    error_summary=partial_failure_summary,
                )

            reason = send_errors[0] if send_errors else "发送失败"
            if partial_failure_summaries:
                reason = (
                    f"目标发送全部失败，共 {len(send_errors)} 个；"
                    f"示例：{partial_failure_summaries[0]}"
                )
            await handle_task_failure(
                session=session,
                task=task,
                error_message=reason,
                max_failure_count=settings.max_failure_count,
                trigger_source=trigger_source,
                advance_schedule=advance_schedule,
                apply_disable_policy=advance_schedule,
            )
            return _build_summary(
                task=task,
                trigger_source=trigger_source,
                status="failed",
                total_targets=len(target_specs),
                success_count=0,
                failed_count=len(target_specs),
                error_summary=reason,
            )

        except FloodWaitError as exc:
            error_message = f"FloodWait: {exc.seconds}秒"
            await handle_task_failure(
                session=session,
                task=task,
                error_message=error_message,
                max_failure_count=settings.max_failure_count,
                trigger_source=trigger_source,
                advance_schedule=advance_schedule,
                apply_disable_policy=advance_schedule,
            )

            if account_id_str != "default":
                action = await circuit_breaker.handle_flood_wait(account_id_str, exc)
                if action == FloodWaitAction.BAN:
                    suspend_until = now + 24 * 3600
                    account = await account_manager.get_account(account_id_str)
                    if account and account.flood_until:
                        suspend_until = max(suspend_until, int(account.flood_until.timestamp()))
                    await suspend_account_tasks(
                        session=session,
                        account_id=account_id_str,
                        suspend_until=suspend_until,
                        reason=f"FloodWait({exc.seconds}s)",
                    )
            return _build_summary(
                task=task,
                trigger_source=trigger_source,
                status="failed",
                total_targets=len(target_specs),
                success_count=0,
                failed_count=len(target_specs),
                error_summary=error_message,
            )

        except PeerFloodError:
            await handle_task_failure(
                session=session,
                task=task,
                error_message="PeerFloodError",
                max_failure_count=settings.max_failure_count,
                trigger_source=trigger_source,
                advance_schedule=advance_schedule,
                apply_disable_policy=advance_schedule,
            )
            if account_id_str != "default":
                suspend_until_dt = await circuit_breaker.handle_peer_flood(account_id_str)
                await suspend_account_tasks(
                    session=session,
                    account_id=account_id_str,
                    suspend_until=int(suspend_until_dt.timestamp()),
                    reason="PeerFloodError",
                )
            return _build_summary(
                task=task,
                trigger_source=trigger_source,
                status="failed",
                total_targets=len(target_specs),
                success_count=0,
                failed_count=len(target_specs),
                error_summary="PeerFloodError",
            )

        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("执行任务 {} 时出错: {}: {!r}", task_id, type(exc).__name__, exc)
            await handle_task_failure(
                session=session,
                task=task,
                error_message=str(exc),
                max_failure_count=settings.max_failure_count,
                trigger_source=trigger_source,
                advance_schedule=advance_schedule,
                apply_disable_policy=advance_schedule,
            )
            return _build_summary(
                task=task,
                trigger_source=trigger_source,
                status="failed",
                total_targets=len(target_specs),
                success_count=0,
                failed_count=len(target_specs),
                error_summary=str(exc),
            )
