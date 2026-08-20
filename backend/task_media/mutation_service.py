"""Dedicated task-media mutations that never touch Telegram file bytes."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import update

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import ScheduledMessageTask
from backend.database.schema.task_media_models import TaskMediaCaptureSession
from backend.task_media.contract import SavedMediaCopy, utc_now

ACTIVE_CAPTURE_STATES = ("waiting", "processing")


def _revision_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "TASK_REVISION_CONFLICT",
            "message": "任务已被其他操作修改，请刷新后重试",
        },
    )


async def delete_task_media(
    *, task_id: str, user_id: int, expected_revision: int
) -> int:
    """Clear DB references without deleting the Telegram Saved Messages source."""
    async with get_async_session() as session:
        result = await session.execute(
            update(ScheduledMessageTask)
            .where(
                ScheduledMessageTask.task_id == task_id,
                ScheduledMessageTask.user_id == user_id,
                ScheduledMessageTask.revision == expected_revision,
            )
            .values(
                media_type="none",
                media_file_id=None,
                media_source_account_id=None,
                media_source_message_id=None,
                media_source_meta=None,
                media_source_state="none",
                media_source_error_code=None,
                media_source_verified_at=None,
                revision=ScheduledMessageTask.revision + 1,
                updated_at=utc_now(),
            )
        )
        if result.rowcount != 1:
            raise _revision_conflict()
        await session.execute(
            update(TaskMediaCaptureSession)
            .where(
                TaskMediaCaptureSession.task_id == task_id,
                TaskMediaCaptureSession.state.in_(ACTIVE_CAPTURE_STATES),
            )
            .values(state="cancelled", error_code="MEDIA_SOURCE_CLEARED")
        )
    return expected_revision + 1


async def update_task_from_capture(
    *, session, capture, copied: SavedMediaCopy, now: datetime
):
    """CAS one verified Saved Messages reference onto its frozen task."""
    return await session.execute(
        update(ScheduledMessageTask)
        .where(
            ScheduledMessageTask.task_id == capture.task_id,
            ScheduledMessageTask.account_id == capture.account_id,
            ScheduledMessageTask.revision == capture.expected_task_revision,
        )
        .values(
            content_contract_version=2,
            media_type=copied.media_type,
            media_file_id=f"tgmsg://{capture.account_id}/{copied.saved_message_id}",
            media_source_account_id=capture.account_id,
            media_source_message_id=copied.saved_message_id,
            media_source_meta=copied.meta,
            media_source_state="valid",
            media_source_error_code=None,
            media_source_verified_at=now,
            revision=ScheduledMessageTask.revision + 1,
            updated_at=now,
        )
    )


async def fail_capture(capture_id: str, error_code: str) -> None:
    """Persist one expected processing failure without overwriting terminal state."""
    async with get_async_session() as session:
        await session.execute(
            update(TaskMediaCaptureSession)
            .where(
                TaskMediaCaptureSession.capture_id == capture_id,
                TaskMediaCaptureSession.state == "processing",
            )
            .values(state="failed", error_code=error_code, consumed_at=utc_now())
        )
