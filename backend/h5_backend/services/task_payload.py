"""Payload normalization/validation helpers for task service."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from backend.database.models import Account, MediaType, ScheduledMessageTask
from backend.h5_backend.services.task_helpers import (
    build_auto_delay_profile,
    normalize_media_type,
    normalize_target_peers,
)

ALLOWED_PEER_TYPES = {"user", "chat", "supergroup", "channel"}


def build_single_target(raw_peer_id: Any, raw_peer_type: Any, raw_access_hash: Any) -> Dict[str, Any]:
    """Build one normalized target dict from legacy single-target fields."""
    if raw_peer_id in (None, ""):
        raise HTTPException(status_code=400, detail="缺少发送目标")
    try:
        peer_id = int(raw_peer_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="target_peer_id/chat_id 非法") from exc

    peer_type = str(raw_peer_type or "").strip().lower() or "user"
    if peer_type not in ALLOWED_PEER_TYPES:
        raise HTTPException(status_code=400, detail="target_peer_type 非法")

    access_hash: Optional[int] = None
    if raw_access_hash not in (None, ""):
        try:
            access_hash = int(raw_access_hash)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="target_access_hash 非法") from exc

    return {"peer_id": peer_id, "peer_type": peer_type, "access_hash": access_hash}


def normalize_targets(payload: Dict[str, Any], fallback_task: Optional[ScheduledMessageTask]) -> None:
    """Normalize target fields into unified target_peers structure."""
    incoming_target_peers = "target_peers" in payload
    incoming_single_target = any(
        key in payload for key in ("target_peer_id", "target_peer_type", "target_access_hash", "chat_id")
    )

    targets: List[Dict[str, Any]] = []
    if incoming_target_peers:
        targets = normalize_target_peers(payload.get("target_peers"))
        if not targets:
            raise HTTPException(status_code=400, detail="target_peers 不能为空")
    elif incoming_single_target:
        raw_peer_id = payload.get("target_peer_id", payload.get("chat_id"))
        raw_peer_type = payload.get("target_peer_type", "user")
        raw_access_hash = payload.get("target_access_hash")
        targets = [build_single_target(raw_peer_id, raw_peer_type, raw_access_hash)]
    elif fallback_task is not None:
        targets = normalize_target_peers(fallback_task.target_peers)
        if not targets:
            raw_peer_id = fallback_task.target_peer_id or fallback_task.chat_id
            if raw_peer_id:
                targets = [
                    build_single_target(
                        raw_peer_id,
                        fallback_task.target_peer_type or "user",
                        fallback_task.target_access_hash,
                    )
                ]

    if not targets:
        raise HTTPException(status_code=400, detail="缺少发送目标（target_peers/target_peer_id/chat_id）")

    primary = targets[0]
    payload["target_peers"] = targets
    payload["target_peer_id"] = primary["peer_id"]
    payload["target_peer_type"] = primary["peer_type"]
    payload["target_access_hash"] = primary.get("access_hash")
    payload["chat_id"] = primary["peer_id"]


def validate_task_payload(payload: Dict[str, Any], current_task: Optional[ScheduledMessageTask]) -> None:
    """Validate and coerce task payload fields."""
    repeat_value = payload.get("repeat_interval_min")
    if repeat_value is None and current_task is not None:
        repeat_value = current_task.repeat_interval_min
    repeat_interval_min = int(repeat_value or 0)
    if repeat_interval_min <= 0:
        raise HTTPException(status_code=400, detail="repeat_interval_min 必须大于 0")
    payload["repeat_interval_min"] = repeat_interval_min

    priority_value = payload.get("priority")
    if priority_value is None and current_task is not None:
        priority_value = current_task.priority
    priority = int(priority_value or 0)
    if priority < 0:
        raise HTTPException(status_code=400, detail="priority 不能小于 0")
    payload["priority"] = priority

    raw_media_type = payload.get("media_type")
    if raw_media_type is None and current_task is not None:
        raw_media_type = current_task.media_type
    media_type = normalize_media_type(raw_media_type or MediaType.NONE.value)
    payload["media_type"] = media_type.value

    media_file_id = payload.get("media_file_id")
    if media_file_id is None and current_task is not None:
        media_file_id = current_task.media_file_id

    if media_type == MediaType.NONE:
        payload["media_file_id"] = None
    elif not media_file_id:
        raise HTTPException(status_code=400, detail="已选择媒体类型，请先上传媒体文件")


def apply_system_strategy_fields(payload: Dict[str, Any], account: Optional[Account]) -> None:
    """Apply system-controlled fields and automatic jitter profile."""
    payload["pin_message"] = False
    payload["day_start_hour"] = None
    payload["day_end_hour"] = None

    priority = int(payload.get("priority", 0) or 0)
    delay_min_seconds, delay_max_seconds, jitter_seconds = build_auto_delay_profile(priority, account)
    payload["delay_min_seconds"] = delay_min_seconds
    payload["delay_max_seconds"] = delay_max_seconds
    payload["jitter_seconds"] = jitter_seconds


def ensure_initial_next_run(
    payload: Dict[str, Any],
    now_ts: int,
    current_task: Optional[ScheduledMessageTask],
    was_enabled: Optional[bool] = None,
) -> None:
    """Initialize or refresh next_run_at when enabling task."""
    if current_task is None:
        enabled = bool(payload.get("enabled"))
        has_next = payload.get("next_run_at") is not None
        start_at_ts = int(payload.get("start_at") or 0)
        if enabled and not has_next:
            payload["next_run_at"] = max(now_ts, start_at_ts) if start_at_ts > 0 else now_ts
        return

    previous_enabled = bool(current_task.enabled) if was_enabled is None else was_enabled
    if "enabled" in payload:
        current_task.enabled = bool(payload["enabled"])
    enabled_now = bool(current_task.enabled)

    start_at_value = payload.get("start_at", current_task.start_at)
    start_at_ts = int(start_at_value or 0)
    if enabled_now and (not previous_enabled or current_task.next_run_at is None):
        current_task.next_run_at = max(now_ts, start_at_ts) if start_at_ts > 0 else now_ts
        if not previous_enabled:
            current_task.failure_count = 0


def apply_update_payload(task: ScheduledMessageTask, payload: Dict[str, Any]) -> None:
    """Apply updatable payload fields onto ORM task object."""
    nullable_fields = {
        "media_file_id",
        "day_start_hour",
        "day_end_hour",
        "start_at",
        "end_at",
        "text",
        "buttons",
        "target_access_hash",
    }

    for key, value in payload.items():
        if not hasattr(task, key):
            continue
        if key in {"user_id", "task_id"}:
            continue
        if value is None and key not in nullable_fields:
            continue
        setattr(task, key, value)

    if task.target_peer_id and not task.chat_id:
        task.chat_id = task.target_peer_id
