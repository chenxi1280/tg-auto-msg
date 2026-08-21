"""V2-only task mutation boundaries used by the H5 service."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException
from sqlalchemy import select, update

from backend.database.schema.models import ScheduledMessageTask
from backend.database.schema.task_media_models import TaskMediaCaptureSession

MEDIA_SOURCE_INPUT_FIELDS = {
    "media_type",
    "media_file_id",
    "media_source_account_id",
    "media_source_message_id",
    "media_source_meta",
    "media_source_state",
    "media_source_error_code",
    "media_source_verified_at",
    "content_contract_version",
    "revision",
}


def reject_media_source_input(payload: Dict[str, Any]) -> None:
    forbidden = sorted(MEDIA_SOURCE_INPUT_FIELDS.intersection(payload))
    if not forbidden:
        return
    raise HTTPException(
        status_code=400,
        detail={
            "code": "TASK_MEDIA_DEDICATED_API_REQUIRED",
            "message": "媒体只能通过 Telegram Bot 设置或专用删除接口清除",
            "fields": forbidden,
        },
    )


def prepare_v2_create_payload(payload: Dict[str, Any]) -> None:
    media_type = str(payload.pop("media_type", None) or "none").strip().lower()
    legacy_media_ref = payload.pop("media_file_id", None)
    reject_media_source_input(payload)
    if media_type not in {"", "none"} or legacy_media_ref:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "TASK_MEDIA_DEDICATED_API_REQUIRED",
                "message": "请先创建任务，再通过 Telegram Bot 设置媒体",
            },
        )
    if payload.get("buttons"):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "TASK_BUTTONS_UNSUPPORTED_FOR_USER_ACCOUNT",
                "message": "执行账号不是 Bot，任务不支持消息按钮",
            },
        )
    if not str(payload.get("text") or "").strip():
        raise HTTPException(
            status_code=400,
            detail={
                "code": "TASK_CONTENT_REQUIRED",
                "message": "H5 创建任务必须填写消息文本",
            },
        )
    payload.update(
        content_contract_version=2,
        revision=1,
        media_type="none",
        media_file_id=None,
        media_source_state="none",
        buttons=None,
    )


def coerce_expected_revision(value: Any) -> int:
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "EXPECTED_REVISION_INVALID",
                "message": "expected_revision 必须是正整数",
            },
        ) from exc
    if revision < 1:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "EXPECTED_REVISION_INVALID",
                "message": "expected_revision 必须是正整数",
            },
        )
    return revision


def extract_expected_revision(
    payload: Dict[str, Any], task: ScheduledMessageTask
) -> int:
    raw_value = payload.pop("expected_revision", None)
    if int(task.content_contract_version or 1) == 2 and raw_value is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "EXPECTED_REVISION_REQUIRED",
                "message": "保存任务必须携带 expected_revision",
            },
        )
    value = raw_value if raw_value is not None else task.revision
    return coerce_expected_revision(value)


def clear_task_media_fields(task: ScheduledMessageTask) -> None:
    task.media_type = "none"
    task.media_file_id = None
    task.media_source_account_id = None
    task.media_source_message_id = None
    task.media_source_meta = None
    task.media_source_state = "none"
    task.media_source_error_code = None
    task.media_source_verified_at = None


async def cancel_task_captures(session, task_id: str) -> None:
    await session.execute(
        update(TaskMediaCaptureSession)
        .where(
            TaskMediaCaptureSession.task_id == task_id,
            TaskMediaCaptureSession.state.in_(("waiting", "processing")),
        )
        .values(state="cancelled", error_code="MEDIA_CAPTURE_ACCOUNT_CHANGED")
    )


async def reject_task_delete_while_capturing(session, task_id: str) -> None:
    capture_id = await session.scalar(
        select(TaskMediaCaptureSession.capture_id).where(
            TaskMediaCaptureSession.task_id == task_id,
            TaskMediaCaptureSession.state == "processing",
        )
    )
    if capture_id is None:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "code": "MEDIA_CAPTURE_PROCESSING",
            "message": "媒体正在复制到 Telegram 收藏夹，请等待捕获完成后再删除任务",
        },
    )
