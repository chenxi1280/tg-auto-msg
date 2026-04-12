"""Payload normalization/validation helpers for task service."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from backend.database.schema.models import (
    Account,
    MediaType,
    ScheduledMessageTask,
    TaskTriggerMode,
)
from backend.h5_backend.services.task.helpers import (
    build_auto_delay_profile,
    normalize_media_type,
    normalize_target_peers,
)
from backend.scheduler.core.task_issue_state import (
    has_target_collection_changed,
    merge_target_runtime_metadata,
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
        targets = merge_target_runtime_metadata(
            incoming_targets=normalize_target_peers(fallback_task.target_peers),
            existing_targets=fallback_task.target_peers,
            reset_delivery_status=False,
        )
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

    if incoming_target_peers or incoming_single_target:
        should_reset_delivery_status = True
        if fallback_task is not None and not has_target_collection_changed(
            incoming_targets=targets,
            existing_targets=fallback_task.target_peers,
        ):
            should_reset_delivery_status = False
        targets = merge_target_runtime_metadata(
            incoming_targets=targets,
            existing_targets=fallback_task.target_peers if fallback_task is not None else None,
            reset_delivery_status=should_reset_delivery_status,
        )

    primary = targets[0]
    payload["target_peers"] = targets
    payload["target_peer_id"] = primary["peer_id"]
    payload["target_peer_type"] = primary["peer_type"]
    payload["target_access_hash"] = primary.get("access_hash")
    payload["chat_id"] = primary["peer_id"]


def validate_task_payload(payload: Dict[str, Any], current_task: Optional[ScheduledMessageTask]) -> None:
    """Validate and coerce task payload fields."""
    raw_trigger_mode = payload.get("trigger_mode")
    if raw_trigger_mode is None and current_task is not None:
        raw_trigger_mode = current_task.trigger_mode
    trigger_mode = str(raw_trigger_mode or TaskTriggerMode.SCHEDULED.value).strip().lower()
    if trigger_mode not in {TaskTriggerMode.SCHEDULED.value, TaskTriggerMode.MANUAL_SHORTCUT.value}:
        raise HTTPException(status_code=400, detail="trigger_mode 非法")
    payload["trigger_mode"] = trigger_mode

    shortcut_slot_value = payload.get("shortcut_slot")
    if shortcut_slot_value is None and current_task is not None:
        shortcut_slot_value = current_task.shortcut_slot
    shortcut_slot: Optional[int] = None
    if shortcut_slot_value not in (None, "", 0, "0"):
        try:
            shortcut_slot = int(shortcut_slot_value)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="shortcut_slot 非法") from exc
        if shortcut_slot not in {1, 2, 3}:
            raise HTTPException(status_code=400, detail="shortcut_slot 仅支持 1-3")
    payload["shortcut_slot"] = shortcut_slot

    shortcut_label_value = payload.get("shortcut_label")
    if shortcut_label_value is None and current_task is not None:
        shortcut_label_value = current_task.shortcut_label
    shortcut_label = str(shortcut_label_value or "").strip()
    if len(shortcut_label) > 20:
        raise HTTPException(status_code=400, detail="shortcut_label 最长 20 个字符")
    payload["shortcut_label"] = shortcut_label or None

    if trigger_mode != TaskTriggerMode.MANUAL_SHORTCUT.value and shortcut_slot is not None:
        raise HTTPException(status_code=400, detail="仅手动快捷任务可加入快捷栏")
    if trigger_mode != TaskTriggerMode.MANUAL_SHORTCUT.value:
        payload["shortcut_label"] = None
    elif not payload["shortcut_label"]:
        raise HTTPException(status_code=400, detail="手动任务必须设置按钮名称")

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

    buttons = payload.get("buttons")
    if buttons is None and current_task is not None:
        buttons = current_task.buttons
    text_value = str(payload.get("text") if payload.get("text") is not None else (current_task.text if current_task is not None else "") or "").strip()
    has_buttons = bool(buttons)
    has_media = media_type != MediaType.NONE
    enabled_value = payload.get("enabled")
    if enabled_value is None and current_task is not None:
        enabled_value = current_task.enabled
    enabled_now = bool(enabled_value)
    if trigger_mode == TaskTriggerMode.MANUAL_SHORTCUT.value and enabled_now and not (text_value or has_buttons or has_media):
        raise HTTPException(status_code=400, detail="手动任务至少需要填写文本、按钮或上传媒体中的一种内容")


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
    trigger_mode = str(
        payload.get(
            "trigger_mode",
            current_task.trigger_mode if current_task is not None else TaskTriggerMode.SCHEDULED.value,
        )
        or TaskTriggerMode.SCHEDULED.value
    ).strip().lower()

    if current_task is None:
        enabled = bool(payload.get("enabled"))
        has_next = payload.get("next_run_at") is not None
        start_at_ts = int(payload.get("start_at") or 0)
        if trigger_mode != TaskTriggerMode.SCHEDULED.value:
            payload["next_run_at"] = None
        elif enabled and not has_next:
            payload["next_run_at"] = max(now_ts, start_at_ts) if start_at_ts > 0 else now_ts
        return

    previous_enabled = bool(current_task.enabled) if was_enabled is None else was_enabled
    if "enabled" in payload:
        current_task.enabled = bool(payload["enabled"])
    enabled_now = bool(current_task.enabled)

    start_at_value = payload.get("start_at", current_task.start_at)
    start_at_ts = int(start_at_value or 0)
    if trigger_mode != TaskTriggerMode.SCHEDULED.value:
        current_task.next_run_at = None
        return
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
        "shortcut_slot",
        "shortcut_label",
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
