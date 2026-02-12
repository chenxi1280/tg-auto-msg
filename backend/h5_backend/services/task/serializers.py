"""Serialization helpers for task service responses."""
from __future__ import annotations

from typing import Any, Dict, List

from backend.database.schema.models import ScheduledMessageTask, TaskLog
from backend.h5_backend.services.task.helpers import media_value


def serialize_task_list_item(task: ScheduledMessageTask) -> Dict[str, Any]:
    """Serialize one task for list endpoint."""
    return {
        "task_id": task.task_id,
        "account_id": task.account_id,
        "chat_id": task.chat_id,
        "target_peer_id": task.target_peer_id,
        "target_peer_type": task.target_peer_type,
        "target_peers": task.target_peers or [],
        "title": task.title,
        "enabled": task.enabled,
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
        "target_peers": task.target_peers or [],
        "title": task.title,
        "enabled": task.enabled,
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
        "media_file_id": task.media_file_id,
        "buttons": task.buttons,
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
            "error_code": log.error_code,
            "error_message": log.error_message,
            "message_id": log.message_id,
        }
        for log in logs
    ]
