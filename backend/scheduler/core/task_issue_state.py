"""Per-target task issue persistence and task target metadata helpers."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from backend.database.schema.models import ScheduledMessageTask, TaskTargetSendIssue
from backend.scheduler.core.task_issue_classifier import TaskIssueClassification

TARGET_DELIVERY_ACTIVE = "active"
TARGET_DELIVERY_SUSPENDED = "suspended"
TARGET_RUNTIME_METADATA_FIELDS = {
    "title",
    "last_sent_message_id",
    "delivery_status",
    "suspended_reason",
    "suspended_at",
    "last_error_type",
    "last_error_message",
}


def _target_identity(item: Any) -> tuple[str, int, int | None] | None:
    if not isinstance(item, dict):
        return None
    try:
        peer_id = int(item.get("peer_id"))
    except Exception:
        return None
    peer_type = str(item.get("peer_type") or "").strip().lower()
    if not peer_type:
        return None
    raw_access_hash = item.get("access_hash")
    access_hash: int | None = None
    if raw_access_hash not in (None, ""):
        try:
            access_hash = int(raw_access_hash)
        except Exception:
            access_hash = None
    return (peer_type, peer_id, access_hash)


def _match_target(item: Any, *, peer_id: int, peer_type: str) -> bool:
    if not isinstance(item, dict):
        return False
    try:
        item_peer_id = int(item.get("peer_id"))
    except Exception:
        return False
    item_peer_type = str(item.get("peer_type") or "").strip().lower()
    return item_peer_id == int(peer_id) and item_peer_type == str(peer_type or "").strip().lower()


def update_task_target_failure_metadata(
    task: ScheduledMessageTask,
    *,
    peer_id: int,
    peer_type: str,
    peer_title: str | None,
    error_type: str,
    error_message: str,
    suspension_reason: str | None,
) -> None:
    """Persist target failure state back into task.target_peers JSON."""
    raw_targets = getattr(task, "target_peers", None)
    if not isinstance(raw_targets, list):
        return

    updated_targets: list[dict[str, Any]] = []
    now_iso = datetime.now().isoformat()
    for item in raw_targets:
        if not isinstance(item, dict):
            updated_targets.append(item)
            continue

        updated_item = dict(item)
        if _match_target(updated_item, peer_id=peer_id, peer_type=peer_type):
            if peer_title:
                updated_item["title"] = str(peer_title).strip()
            updated_item["last_error_type"] = str(error_type)
            updated_item["last_error_message"] = str(error_message)
            if suspension_reason:
                updated_item["delivery_status"] = TARGET_DELIVERY_SUSPENDED
                updated_item["suspended_reason"] = str(suspension_reason)
                updated_item["suspended_at"] = now_iso
            else:
                updated_item["delivery_status"] = TARGET_DELIVERY_ACTIVE
                updated_item["suspended_reason"] = None
                updated_item["suspended_at"] = None
        updated_targets.append(updated_item)

    task.target_peers = updated_targets


def update_task_target_success_metadata(
    task: ScheduledMessageTask,
    *,
    peer_id: int,
    peer_type: str,
) -> None:
    """Clear failure metadata when a target recovers and succeeds again."""
    raw_targets = getattr(task, "target_peers", None)
    if not isinstance(raw_targets, list):
        return

    updated_targets: list[dict[str, Any]] = []
    for item in raw_targets:
        if not isinstance(item, dict):
            updated_targets.append(item)
            continue

        updated_item = dict(item)
        if _match_target(updated_item, peer_id=peer_id, peer_type=peer_type):
            updated_item["delivery_status"] = TARGET_DELIVERY_ACTIVE
            updated_item["suspended_reason"] = None
            updated_item["suspended_at"] = None
            updated_item["last_error_type"] = None
            updated_item["last_error_message"] = None
        updated_targets.append(updated_item)

    task.target_peers = updated_targets


def merge_target_runtime_metadata(
    *,
    incoming_targets: list[dict[str, Any]],
    existing_targets: list[dict[str, Any]] | None,
    reset_delivery_status: bool = True,
) -> list[dict[str, Any]]:
    """
    Preserve runtime metadata across normal task edits.

    If the user explicitly resubmits a target, treat it as a manual re-enable:
    keep last_sent/title/error summary, but clear suspension markers.
    """
    existing_map: dict[tuple[str, int], dict[str, Any]] = {}
    for item in existing_targets or []:
        if not isinstance(item, dict):
            continue
        try:
            peer_id = int(item.get("peer_id"))
        except Exception:
            continue
        peer_type = str(item.get("peer_type") or "").strip().lower()
        if not peer_type:
            continue
        existing_map[(peer_type, peer_id)] = dict(item)

    merged: list[dict[str, Any]] = []
    for item in incoming_targets:
        peer_id = int(item["peer_id"])
        peer_type = str(item["peer_type"] or "").strip().lower()
        existing = existing_map.get((peer_type, peer_id), {})
        merged_item = dict(item)

        if existing.get("title") and not merged_item.get("title"):
            merged_item["title"] = existing.get("title")
        if existing.get("last_sent_message_id") not in (None, ""):
            merged_item["last_sent_message_id"] = existing.get("last_sent_message_id")
        if existing.get("last_error_type"):
            merged_item["last_error_type"] = existing.get("last_error_type")
        if existing.get("last_error_message"):
            merged_item["last_error_message"] = existing.get("last_error_message")

        if reset_delivery_status:
            # User re-submitted the target, so remove any previous suspension flag.
            merged_item["delivery_status"] = TARGET_DELIVERY_ACTIVE
            merged_item["suspended_reason"] = None
            merged_item["suspended_at"] = None
        else:
            if "delivery_status" in existing:
                merged_item["delivery_status"] = existing.get("delivery_status")
            if "suspended_reason" in existing:
                merged_item["suspended_reason"] = existing.get("suspended_reason")
            if "suspended_at" in existing:
                merged_item["suspended_at"] = existing.get("suspended_at")

        merged.append(merged_item)

    return merged


def has_target_collection_changed(
    *,
    incoming_targets: list[dict[str, Any]],
    existing_targets: list[dict[str, Any]] | None,
) -> bool:
    """Return True when the submitted target collection materially changed."""
    incoming = sorted(
        identity for item in incoming_targets if (identity := _target_identity(item)) is not None
    )
    existing = sorted(
        identity for item in (existing_targets or []) if (identity := _target_identity(item)) is not None
    )
    return incoming != existing


async def record_task_target_send_issue(
    *,
    session,
    task: ScheduledMessageTask,
    peer_id: int,
    peer_type: str,
    peer_title: str | None,
    classification: TaskIssueClassification,
) -> TaskTargetSendIssue:
    """Create or refresh one active task-target issue row."""
    now = datetime.now()
    issue = (
        await session.execute(
            select(TaskTargetSendIssue).where(
                TaskTargetSendIssue.task_id == str(task.task_id),
                TaskTargetSendIssue.peer_id == int(peer_id),
                TaskTargetSendIssue.peer_type == str(peer_type),
            )
        )
    ).scalar_one_or_none()

    if issue is None:
        issue = TaskTargetSendIssue(
            task_id=str(task.task_id),
            user_id=int(task.user_id),
            account_id=str(task.account_id) if task.account_id else None,
            peer_id=int(peer_id),
            peer_type=str(peer_type),
            peer_title=(str(peer_title).strip() or None) if peer_title else None,
            current_error_type=classification.error_type,
            current_error_message=classification.user_message,
            issue_category=classification.issue_category,
            status="active",
            first_seen_at=now,
            last_seen_at=now,
            last_notified_at=None,
            muted_until=None,
            auto_suspended=bool(classification.should_auto_suspend_target),
            resolved_at=None,
            recovered_notified_at=None,
        )
        session.add(issue)
        return issue

    issue_changed = (
        str(issue.status) != "active"
        or str(issue.current_error_type or "") != str(classification.error_type)
        or str(issue.current_error_message or "") != str(classification.user_message)
        or str(issue.issue_category or "") != str(classification.issue_category)
        or bool(issue.auto_suspended) != bool(classification.should_auto_suspend_target)
    )

    issue.account_id = str(task.account_id) if task.account_id else None
    issue.user_id = int(task.user_id)
    issue.peer_title = (str(peer_title).strip() or None) if peer_title else issue.peer_title
    issue.current_error_type = classification.error_type
    issue.current_error_message = classification.user_message
    issue.issue_category = classification.issue_category
    issue.status = "active"
    issue.last_seen_at = now
    issue.auto_suspended = bool(classification.should_auto_suspend_target)
    issue.resolved_at = None
    issue.recovered_notified_at = None

    if issue_changed:
        issue.first_seen_at = now
        issue.last_notified_at = None
        issue.muted_until = None

    return issue


async def resolve_task_target_send_issue(
    *,
    session,
    task: ScheduledMessageTask,
    peer_id: int,
    peer_type: str,
) -> TaskTargetSendIssue | None:
    """Mark one active issue as resolved after the target succeeds again."""
    issue = (
        await session.execute(
            select(TaskTargetSendIssue).where(
                TaskTargetSendIssue.task_id == str(task.task_id),
                TaskTargetSendIssue.peer_id == int(peer_id),
                TaskTargetSendIssue.peer_type == str(peer_type),
                TaskTargetSendIssue.status == "active",
            )
        )
    ).scalar_one_or_none()

    if issue is None:
        return None

    issue.status = "resolved"
    issue.resolved_at = datetime.now()
    issue.recovered_notified_at = None
    return issue
