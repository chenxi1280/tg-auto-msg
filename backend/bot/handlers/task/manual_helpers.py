"""Shared helpers for bot-side manual task creation and editing."""
from __future__ import annotations

from backend.database.schema.models import MediaType, ScheduledMessageTask


def task_has_content(task: ScheduledMessageTask) -> bool:
    """Return whether a task has text or a usable versioned media reference."""
    has_text = bool(str(task.text or "").strip())
    is_v2 = int(task.content_contract_version or 1) == 2
    source_id = task.media_source_message_id if is_v2 else task.media_file_id
    has_media = task.media_type != MediaType.NONE and bool(source_id)
    if is_v2:
        has_media = has_media and task.media_source_state == "valid"
    return has_text or has_media
