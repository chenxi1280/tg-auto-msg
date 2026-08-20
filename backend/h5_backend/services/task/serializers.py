"""Serialization helpers for task service responses."""
from __future__ import annotations

from typing import Any, Dict, List

from backend.database.schema.models import ScheduledMessageTask, TaskLog
from backend.h5_backend.services.task.helpers import media_value


def _serialize_public_target_peers(task: ScheduledMessageTask) -> List[Dict[str, Any]]:
    """Expose only user-facing target fields."""
    serialized: List[Dict[str, Any]] = []
    raw_targets = task.target_peers or []
    for item in raw_targets:
        if not isinstance(item, dict):
            continue
        serialized.append(
            {
                "peer_id": item.get("peer_id"),
                "peer_type": item.get("peer_type"),
                "title": item.get("title"),
                "delivery_status": item.get("delivery_status") or "active",
                "suspended_reason": item.get("suspended_reason"),
                "suspended_at": item.get("suspended_at"),
                "last_error_type": item.get("last_error_type"),
                "last_error_message": item.get("last_error_message"),
            }
        )
    return serialized


def serialize_task_list_item(task: ScheduledMessageTask) -> Dict[str, Any]:
    """Serialize one task for list endpoint."""
    return {
        "task_id": task.task_id,
        "account_id": task.account_id,
        "chat_id": task.chat_id,
        "target_peer_id": task.target_peer_id,
        "target_peer_type": task.target_peer_type,
        "target_peers": _serialize_public_target_peers(task),
        "title": task.title,
        "enabled": task.enabled,
        "trigger_mode": task.trigger_mode,
        "shortcut_slot": task.shortcut_slot,
        "shortcut_label": task.shortcut_label,
        "priority": task.priority,
        "repeat_interval_min": task.repeat_interval_min,
        "jitter_seconds": task.jitter_seconds,
        "delay_min_seconds": task.delay_min_seconds,
        "delay_max_seconds": task.delay_max_seconds,
        "day_start_hour": task.day_start_hour,
        "day_end_hour": task.day_end_hour,
        "start_at": task.start_at,
        "end_at": task.end_at,
        "text": task.text,
        "media_type": media_value(task.media_type),
        "media_source_state": task.media_source_state,
        "content_contract_version": task.content_contract_version,
        "revision": task.revision,
        "delete_previous": task.delete_previous,
        "pin_message": task.pin_message,
        "next_run_at": task.next_run_at,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def serialize_task_detail(task: ScheduledMessageTask) -> Dict[str, Any]:
    """Serialize one task for detail endpoint."""
    return {
        "task_id": task.task_id,
        "user_id": task.user_id,
        "account_id": task.account_id,
        "chat_id": task.chat_id,
        "target_peer_id": task.target_peer_id,
        "target_peer_type": task.target_peer_type,
        "target_access_hash": task.target_access_hash,
        "target_peers": _serialize_public_target_peers(task),
        "title": task.title,
        "enabled": task.enabled,
        "trigger_mode": task.trigger_mode,
        "shortcut_slot": task.shortcut_slot,
        "shortcut_label": task.shortcut_label,
        "priority": task.priority,
        "repeat_interval_min": task.repeat_interval_min,
        "jitter_seconds": task.jitter_seconds,
        "delay_min_seconds": task.delay_min_seconds,
        "delay_max_seconds": task.delay_max_seconds,
        "day_start_hour": task.day_start_hour,
        "day_end_hour": task.day_end_hour,
        "start_at": task.start_at,
        "end_at": task.end_at,
        "text": task.text,
        "media_type": media_value(task.media_type),
        "media_source_state": task.media_source_state,
        "media_source_meta": task.media_source_meta,
        "media_source_error_code": task.media_source_error_code,
        "media_source_verified_at": (
            task.media_source_verified_at.isoformat() if task.media_source_verified_at else None
        ),
        "content_contract_version": task.content_contract_version,
        "revision": task.revision,
        "buttons": task.buttons if int(task.content_contract_version or 1) == 1 else None,
        "delete_previous": task.delete_previous,
        "pin_message": task.pin_message,
        "last_sent_message_id": task.last_sent_message_id,
        "next_run_at": task.next_run_at,
        "failure_count": task.failure_count,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def serialize_task_logs(logs: List[TaskLog]) -> List[Dict[str, Any]]:
    """Serialize task log rows."""
    return [
        {
            "id": log.id,
            "send_at": log.send_at.isoformat() if log.send_at else None,
            "result": log.result,
            "trigger_source": log.trigger_source,
            "error_code": log.error_code,
            "error_message": log.error_message,
            "message_id": log.message_id,
        }
        for log in logs
    ]
