"""Shared one-shot task execution service for scheduler, bot, and API."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import select, text
from telethon.errors import FloodWaitError, PeerFloodError

from backend.bot.account.manager import AccountManager, get_account_manager
from backend.bot.account.reauth import is_reauth_required_account
from backend.bot.account.reauth_notifier import (
    mark_account_reauth_required,
    notify_account_authorization_required,
)
from backend.bot.account.proxy_observation import (
    claim_proxy_observation_send_budget,
    is_proxy_observation_active,
    proxy_observation_has_send_budget,
)
from backend.bot.circuit.breaker import FloodWaitAction, get_circuit_breaker
from backend.config.core.settings import settings
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account, HealthStatus, ScheduledMessageTask, TaskTriggerSource
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


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


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
    account_display: Optional[str] = None
    success_targets: Optional[list[str]] = None
    failed_targets: Optional[list[str]] = None
    message_preview: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _ValidationResult:
    """Intermediate result from task + account validation."""

    task: ScheduledMessageTask
    account_display: str
    account: object = None
    target_specs: list[dict] = field(default_factory=list)
    client: object = None
    account_id_str: str = "default"


# ---------------------------------------------------------------------------
# Helpers: display / preview
# ---------------------------------------------------------------------------


def _truncate_preview(value: str, limit: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _build_task_message_preview(task: ScheduledMessageTask) -> Optional[str]:
    text = str(task.text or "").strip()
    if text:
        return _truncate_preview(text, 80)
    if task.media_type and str(task.media_type) != "none":
        return f"{task.media_type.value if hasattr(task.media_type, 'value') else task.media_type} 媒体消息"
    if task.buttons:
        return "按钮消息"
    return None


def _account_display_name(account, account_id: Optional[str]) -> str:
    if account is not None:
        username = str(getattr(account, "username", "") or "").strip()
        if username:
            return username if username.startswith("@") else f"@{username}"
        first_name = str(getattr(account, "first_name", "") or "").strip()
        if first_name:
            return first_name
        phone = str(getattr(account, "phone", "") or "").strip()
        if phone:
            return phone
    if account_id:
        return str(account_id)[:8]
    return "默认账号"


def _build_summary(
    *,
    task: ScheduledMessageTask,
    trigger_source: str,
    status: str,
    total_targets: int,
    success_count: int,
    failed_count: int,
    error_summary: Optional[str] = None,
    account_display: Optional[str] = None,
    success_targets: Optional[list[str]] = None,
    failed_targets: Optional[list[str]] = None,
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
        account_display=account_display,
        success_targets=success_targets or [],
        failed_targets=failed_targets or [],
        message_preview=_build_task_message_preview(task),
    )


def _defer_task_until_observation_end(task: ScheduledMessageTask, *, now: int, account) -> None:
    until = getattr(account, "proxy_observation_until", None)
    task.next_run_at = max(now + 60, int(until.timestamp())) if until is not None else now + 60


async def _mark_reauth_required_and_defer(
    *,
    task: ScheduledMessageTask,
    account,
    session,
    now: int,
    advance_schedule: bool,
) -> None:
    await mark_account_reauth_required(
        task.account_id,
        str(getattr(account, "reauth_reason", "") or "session_unauthorized"),
    )
    if advance_schedule:
        task.next_run_at = now + max(1, int(task.repeat_interval_min or 1)) * 60
        await session.commit()


def _account_health_value(account) -> str:
    raw_status = getattr(account, "health_status", "") or ""
    if hasattr(raw_status, "value"):
        raw_status = raw_status.value
    return str(raw_status).strip().lower()


def _is_account_unavailable(account) -> bool:
    status = _account_health_value(account)
    return bool(status) and status != HealthStatus.ONLINE.value


async def _defer_unavailable_account(
    *,
    task: ScheduledMessageTask,
    session,
    now: int,
    advance_schedule: bool,
    trigger_source: str,
    account_display: str,
) -> TaskExecutionSummary:
    if advance_schedule:
        task.next_run_at = now + max(1, int(task.repeat_interval_min or 1)) * 60
        await session.commit()
    return _build_summary(
        task=task,
        trigger_source=trigger_source,
        status="skipped",
        total_targets=0,
        success_count=0,
        failed_count=0,
        error_summary="当前执行账号离线，已暂缓任务发送",
        account_display=account_display,
    )


def _target_label(spec: dict) -> str:
    title = spec.get("title")
    if title:
        return str(title)
    peer_type = str(spec.get("peer_type") or "user")
    peer_id = spec.get("peer_id")
    return f"{peer_type}:{peer_id}"


# ---------------------------------------------------------------------------
# Phase 1: Load, validate, resolve account & client
# ---------------------------------------------------------------------------


async def _validate_and_resolve(
    *,
    task_id: str,
    now: int,
    advance_schedule: bool,
    trigger_source: str,
    session,
    account_manager: AccountManager,
) -> _ValidationResult | TaskExecutionSummary:
    """Load task, check auth/reauth, fix next_run_at, collect targets, resolve client.

    Returns _ValidationResult on success, or TaskExecutionSummary for early-exit.
    """
    result = await session.execute(
        select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task.enabled:
        raise HTTPException(status_code=400, detail="任务已禁用，无法执行")

    account = None
    account_display = _account_display_name(None, task.account_id)

    # 授权校验
    if task.account_id:
        auth_summary = await get_account_authorization_summary(task.account_id, session=session)
        if not auth_summary.can_create_tasks:
            disabled_count = await disable_tasks_for_account_if_unlicensed(
                account_id=task.account_id, session=session,
            )
            await session.commit()
            await notify_account_authorization_required(task.account_id, "authorization_expired")
            raise HTTPException(
                status_code=400,
                detail=f"当前执行账号已无有效授权，已停用该账号下任务 {disabled_count} 条",
            )

    # 账号健康校验
    if task.account_id:
        account = await account_manager.get_account(task.account_id)
        account_display = _account_display_name(account, task.account_id)
        if account and is_reauth_required_account(account):
            await _mark_reauth_required_and_defer(
                task=task, account=account, session=session,
                now=now, advance_schedule=advance_schedule,
            )
            return _build_summary(
                task=task, trigger_source=trigger_source,
                status="skipped", total_targets=0, success_count=0, failed_count=0,
                error_summary="当前执行账号需要重新绑定后才能发送，相关任务已暂缓",
                account_display=account_display,
            )
        if account and _is_account_unavailable(account):
            return await _defer_unavailable_account(
                task=task,
                session=session,
                now=now,
                advance_schedule=advance_schedule,
                trigger_source=trigger_source,
                account_display=account_display,
            )
        if account and is_proxy_observation_active(account) and not proxy_observation_has_send_budget(account):
            if advance_schedule:
                _defer_task_until_observation_end(task, now=now, account=account)
                await session.commit()
            return _build_summary(
                task=task, trigger_source=trigger_source,
                status="skipped", total_targets=0, success_count=0, failed_count=0,
                error_summary="账号正在代理观察期内，已达到 24 小时观察期发送上限",
                account_display=account_display,
            )

    # 修复缺失的 next_run_at
    if advance_schedule and task.next_run_at is None:
        start_at_ts = int(task.start_at or 0)
        task.next_run_at = max(now, start_at_ts) if start_at_ts > 0 else now
        await session.commit()

    # 尚未到调度时间
    if advance_schedule and task.next_run_at and task.next_run_at > now:
        return _build_summary(
            task=task, trigger_source=trigger_source,
            status="skipped", total_targets=0, success_count=0, failed_count=0,
            error_summary="任务尚未到执行时间",
        )

    # 收集目标
    target_specs = collect_task_targets(task)
    if account and is_proxy_observation_active(account):
        target_specs = target_specs[:1]
    if not target_specs:
        return await _handle_no_targets(
            task=task, session=session, now=now,
            advance_schedule=advance_schedule,
            trigger_source=trigger_source,
        )

    # 解析客户端
    account_id_str, client = await _resolve_client(task, account_manager)
    if client is None:
        return await _handle_client_failure(
            task=task, session=session,
            advance_schedule=advance_schedule,
            target_count=len(target_specs),
            trigger_source=trigger_source,
        )

    return _ValidationResult(
        task=task,
        account_display=account_display,
        account=account,
        target_specs=target_specs,
        client=client,
        account_id_str=account_id_str,
    )


async def _handle_no_targets(
    *,
    task: ScheduledMessageTask,
    session,
    now: int,
    advance_schedule: bool,
    trigger_source: str,
) -> TaskExecutionSummary:
    """Handle the case where no valid send targets exist."""
    configured_count = count_configured_task_targets(task)
    if configured_count > 0:
        if advance_schedule:
            task.next_run_at = now + task.repeat_interval_min * 60
            await session.commit()
            return _build_summary(
                task=task, trigger_source=trigger_source,
                status="skipped", total_targets=configured_count,
                success_count=0, failed_count=configured_count,
                error_summary="当前没有可发送目标（目标可能已被系统暂停）",
            )
        await handle_task_failure(
            session=session, task=task,
            error_message="当前没有可发送目标（目标可能已被系统暂停）",
            max_failure_count=settings.max_failure_count,
            trigger_source=trigger_source,
            advance_schedule=False, apply_disable_policy=False,
        )
        return _build_summary(
            task=task, trigger_source=trigger_source,
            status="failed", total_targets=configured_count,
            success_count=0, failed_count=configured_count,
            error_summary="当前没有可发送目标（目标可能已被系统暂停）",
        )

    await handle_task_failure(
        session=session, task=task,
        error_message="缺少目标 Peer ID",
        max_failure_count=settings.max_failure_count,
        trigger_source=trigger_source,
        advance_schedule=advance_schedule,
        apply_disable_policy=advance_schedule,
    )
    return _build_summary(
        task=task, trigger_source=trigger_source,
        status="failed", total_targets=0, success_count=0, failed_count=0,
        error_summary="缺少目标 Peer ID",
    )


async def _resolve_client(task, account_manager):
    """Resolve (account_id_str, TelegramClient) for the task."""
    if task.account_id:
        await account_manager.ensure_account_proxy(task.account_id)
        client = await account_manager.get_client(task.account_id)
        return task.account_id, client

    from backend.bot.client_runtime.manager import userbot_client
    return "default", userbot_client


async def _handle_client_failure(
    *,
    task, session, advance_schedule, target_count, trigger_source,
) -> TaskExecutionSummary:
    await handle_task_failure(
        session=session, task=task,
        error_message="无法获取账号客户端",
        max_failure_count=settings.max_failure_count,
        trigger_source=trigger_source,
        advance_schedule=advance_schedule,
        apply_disable_policy=advance_schedule,
    )
    return _build_summary(
        task=task, trigger_source=trigger_source,
        status="failed", total_targets=target_count,
        success_count=0, failed_count=target_count,
        error_summary="无法获取账号客户端",
    )


# ---------------------------------------------------------------------------
# Phase 2: Schedule constraint check
# ---------------------------------------------------------------------------


async def _check_schedule_constraints(
    *,
    task: ScheduledMessageTask,
    now: int,
    current_hour: int,
    advance_schedule: bool,
    respect_schedule_constraints: bool,
    trigger_source: str,
    session,
    target_count: int,
) -> TaskExecutionSummary | None:
    """Return a 'skipped' summary if constraints block execution, else None."""
    if not respect_schedule_constraints:
        return None

    if task.start_at and now < task.start_at:
        if advance_schedule:
            task.next_run_at = max(task.next_run_at or 0, task.start_at)
            await session.commit()
        return _build_summary(
            task=task, trigger_source=trigger_source,
            status="skipped", total_targets=target_count,
            success_count=0, failed_count=0,
            error_summary="任务未到开始时间",
        )

    if task.end_at and now > task.end_at:
        if advance_schedule:
            task.enabled = False
            await session.commit()
        return _build_summary(
            task=task, trigger_source=trigger_source,
            status="skipped", total_targets=target_count,
            success_count=0, failed_count=0,
            error_summary="任务已超过结束时间",
        )

    allowed, next_run_at = check_time_limit(task, current_hour, now)
    if not allowed:
        if advance_schedule and next_run_at is not None:
            task.next_run_at = next_run_at
            await session.commit()
        return _build_summary(
            task=task, trigger_source=trigger_source,
            status="skipped", total_targets=target_count,
            success_count=0, failed_count=0,
            error_summary="当前不在任务允许的执行时段内",
        )

    return None


def _is_postgres_session(session) -> bool:
    try:
        bind = session.get_bind()
        return str(bind.dialect.name).lower().startswith("postgres")
    except Exception:
        return False


async def _lock_and_recheck_observation_budget(
    *,
    task: ScheduledMessageTask,
    target_specs: list[dict],
    session,
    now: int,
    advance_schedule: bool,
    trigger_source: str,
    account_display: str,
) -> tuple[TaskExecutionSummary | None, list[dict]]:
    account_id = str(task.account_id or "").strip()
    if not account_id:
        return None, target_specs

    account = await session.get(Account, account_id)
    if account is None or not is_proxy_observation_active(account):
        return None, target_specs

    if _is_postgres_session(session):
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"proxy-observation:{account_id}"},
        )
        await session.refresh(account)

    if not is_proxy_observation_active(account):
        return None, target_specs

    if not proxy_observation_has_send_budget(account):
        if advance_schedule:
            _defer_task_until_observation_end(task, now=now, account=account)
            await session.commit()
        return (
            _build_summary(
                task=task, trigger_source=trigger_source,
                status="skipped", total_targets=0, success_count=0, failed_count=0,
                error_summary="账号正在代理观察期内，已达到 24 小时观察期发送上限",
                account_display=account_display,
            ),
            [],
        )

    if not await claim_proxy_observation_send_budget(session, account_id):
        if advance_schedule:
            _defer_task_until_observation_end(task, now=now, account=account)
            await session.commit()
        return (
            _build_summary(
                task=task, trigger_source=trigger_source,
                status="skipped", total_targets=0, success_count=0, failed_count=0,
                error_summary="账号正在代理观察期内，发送预算已被其他任务占用",
                account_display=account_display,
            ),
            [],
        )

    return None, target_specs[:1]


# ---------------------------------------------------------------------------
# Phase 3: Per-target send loop
# ---------------------------------------------------------------------------


async def _send_to_targets(
    *,
    task: ScheduledMessageTask,
    target_specs: list[dict],
    client,
    account_id_str: str,
    session,
    now: int,
    advance_schedule: bool,
    trigger_source: str,
    account_manager,
    account_display: str,
) -> TaskExecutionSummary:
    """Send message to every target and handle success/failure lifecycle."""
    from backend.bot.resources.manager import get_resource_manager
    resource_manager = get_resource_manager()

    send_errors: list[str] = []
    partial_failure_summaries: list[str] = []
    target_message_ids: dict[tuple[str, int], int] = {}
    success_target_labels: list[str] = []
    failed_target_labels: list[str] = []
    last_message_id: int | None = None

    for spec in target_specs:
        target_peer_id = int(spec["peer_id"])
        target_peer_type = spec.get("peer_type")
        target_access_hash = spec.get("access_hash")
        target_title = spec.get("title")
        normalized_type = str(
            target_peer_type or task.target_peer_type or "user"
        ).strip().lower()
        label = _target_label(spec)
        previous_msg_id = get_target_last_message_id(
            task, target_peer_id=target_peer_id, target_peer_type=target_peer_type,
        )

        try:
            send_target = await resolve_send_target(
                client=client, task=task,
                target_peer_id=target_peer_id,
                target_peer_type=target_peer_type,
                target_access_hash=target_access_hash,
                resource_manager=resource_manager,
            )
            message_id = await send_with_protections(
                client=client, task=task,
                send_target=send_target,
                lock_peer_id=target_peer_id,
                account_id=account_id_str,
                previous_message_id=previous_msg_id,
                media_ref_prefix="tgmsg://",
            )
        except (FloodWaitError, PeerFloodError):
            raise
        except Exception as send_err:
            classification = classify_task_send_error(send_err)
            send_errors.append(f"peer={target_peer_id}: {type(send_err).__name__}: {send_err}")
            partial_failure_summaries.append(f"{label}: {classification.user_message}")
            failed_target_labels.append(str(label))
            issue = await record_task_target_send_issue(
                session=session, task=task,
                peer_id=target_peer_id, peer_type=normalized_type,
                peer_title=str(target_title).strip() if target_title else None,
                classification=classification,
            )
            update_task_target_failure_metadata(
                task,
                peer_id=target_peer_id, peer_type=normalized_type,
                peer_title=str(target_title).strip() if target_title else None,
                error_type=classification.error_type,
                error_message=classification.user_message,
                suspension_reason=classification.suspension_reason if issue.auto_suspended else None,
            )
            logger.warning(
                "任务 {} 发送目标失败: peer={}, error={}: {}",
                task.task_id, target_peer_id, type(send_err).__name__, send_err,
            )
            continue

        if message_id:
            await resolve_task_target_send_issue(
                session=session, task=task,
                peer_id=target_peer_id, peer_type=normalized_type,
            )
            update_task_target_success_metadata(task, peer_id=target_peer_id, peer_type=normalized_type)
            last_message_id = message_id
            target_message_ids[(normalized_type, target_peer_id)] = message_id
            success_target_labels.append(str(label))
        else:
            send_errors.append(f"peer={target_peer_id}: send_message returned empty")
            classification = classify_task_send_error(RuntimeError("send_message returned empty"))
            partial_failure_summaries.append(f"{label}: {classification.user_message}")
            failed_target_labels.append(str(label))
            issue = await record_task_target_send_issue(
                session=session, task=task,
                peer_id=target_peer_id, peer_type=normalized_type,
                peer_title=str(target_title).strip() if target_title else None,
                classification=classification,
            )
            update_task_target_failure_metadata(
                task,
                peer_id=target_peer_id, peer_type=normalized_type,
                peer_title=str(target_title).strip() if target_title else None,
                error_type=classification.error_type,
                error_message=classification.user_message,
                suspension_reason=classification.suspension_reason if issue.auto_suspended else None,
            )

    # --- Lifecycle: success or all-failed ---
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
            session=session, task=task,
            message_id=last_message_id,
            target_message_ids=target_message_ids,
            error_message=partial_failure_summary,
            now=now, account_manager=account_manager,
            trigger_source=trigger_source, advance_schedule=advance_schedule,
        )
        if send_errors:
            logger.warning(
                "任务 {} 部分目标发送失败: {} 个; 错误示例: {}",
                task.task_id, len(send_errors), send_errors[0],
            )
        return _build_summary(
            task=task, trigger_source=trigger_source,
            status="partial_success" if failed_count else "success",
            total_targets=len(target_specs),
            success_count=success_count, failed_count=failed_count,
            error_summary=partial_failure_summary,
            account_display=account_display,
            success_targets=success_target_labels,
            failed_targets=failed_target_labels,
        )

    reason = send_errors[0] if send_errors else "发送失败"
    if partial_failure_summaries:
        reason = f"目标发送全部失败，共 {len(send_errors)} 个；示例：{partial_failure_summaries[0]}"
    await handle_task_failure(
        session=session, task=task,
        error_message=reason,
        max_failure_count=settings.max_failure_count,
        trigger_source=trigger_source,
        advance_schedule=advance_schedule,
        apply_disable_policy=advance_schedule,
    )
    return _build_summary(
        task=task, trigger_source=trigger_source,
        status="failed", total_targets=len(target_specs),
        success_count=0, failed_count=len(target_specs),
        error_summary=reason,
        account_display=account_display,
        success_targets=success_target_labels,
        failed_targets=failed_target_labels or [_target_label(s) for s in target_specs],
    )


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


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
    circuit_breaker = get_circuit_breaker()

    async with get_async_session() as session:
        # --- Phase 1: validate & resolve ---
        vr = await _validate_and_resolve(
            task_id=task_id, now=now,
            advance_schedule=advance_schedule,
            trigger_source=trigger_source,
            session=session, account_manager=account_manager,
        )
        if isinstance(vr, TaskExecutionSummary):
            return vr
        assert isinstance(vr, _ValidationResult)

        task = vr.task
        target_specs = vr.target_specs
        account_id_str = vr.account_id_str

        # --- Phase 2: schedule constraints ---
        skipped = await _check_schedule_constraints(
            task=task, now=now, current_hour=current_hour,
            advance_schedule=advance_schedule,
            respect_schedule_constraints=respect_schedule_constraints,
            trigger_source=trigger_source,
            session=session, target_count=len(target_specs),
        )
        if skipped is not None:
            return skipped

        observation_skipped, target_specs = await _lock_and_recheck_observation_budget(
            task=task, target_specs=target_specs,
            session=session, now=now,
            advance_schedule=advance_schedule,
            trigger_source=trigger_source,
            account_display=vr.account_display,
        )
        if observation_skipped is not None:
            return observation_skipped

        # --- Phase 3: send with error recovery ---
        try:
            return await _send_to_targets(
                task=task, target_specs=target_specs,
                client=vr.client, account_id_str=account_id_str,
                session=session, now=now,
                advance_schedule=advance_schedule,
                trigger_source=trigger_source,
                account_manager=account_manager,
                account_display=vr.account_display,
            )

        except FloodWaitError as exc:
            error_message = f"FloodWait: {exc.seconds}秒"
            await handle_task_failure(
                session=session, task=task,
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
                    acc = await account_manager.get_account(account_id_str)
                    if acc and acc.flood_until:
                        suspend_until = max(suspend_until, int(acc.flood_until.timestamp()))
                    await suspend_account_tasks(
                        session=session, account_id=account_id_str,
                        suspend_until=suspend_until, reason=f"FloodWait({exc.seconds}s)",
                    )
            return _build_summary(
                task=task, trigger_source=trigger_source,
                status="failed", total_targets=len(target_specs),
                success_count=0, failed_count=len(target_specs),
                error_summary=error_message,
            )

        except PeerFloodError:
            await handle_task_failure(
                session=session, task=task,
                error_message="PeerFloodError",
                max_failure_count=settings.max_failure_count,
                trigger_source=trigger_source,
                advance_schedule=advance_schedule,
                apply_disable_policy=advance_schedule,
            )
            if account_id_str != "default":
                suspend_until_dt = await circuit_breaker.handle_peer_flood(account_id_str)
                await suspend_account_tasks(
                    session=session, account_id=account_id_str,
                    suspend_until=int(suspend_until_dt.timestamp()), reason="PeerFloodError",
                )
            return _build_summary(
                task=task, trigger_source=trigger_source,
                status="failed", total_targets=len(target_specs),
                success_count=0, failed_count=len(target_specs),
                error_summary="PeerFloodError",
            )

        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("执行任务 {} 时出错: {}: {!r}", task_id, type(exc).__name__, exc)
            await handle_task_failure(
                session=session, task=task,
                error_message=str(exc),
                max_failure_count=settings.max_failure_count,
                trigger_source=trigger_source,
                advance_schedule=advance_schedule,
                apply_disable_policy=advance_schedule,
            )
            return _build_summary(
                task=task, trigger_source=trigger_source,
                status="failed", total_targets=len(target_specs),
                success_count=0, failed_count=len(target_specs),
                error_summary=str(exc),
            )
