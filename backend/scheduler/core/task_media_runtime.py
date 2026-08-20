"""Runtime resolution for Telegram-native V2 task media."""

from __future__ import annotations

from backend.task_media.contract import TaskMediaError, classify_message_media


def _media_value(value) -> str:
    return str(getattr(value, "value", value) or "none").lower()


async def resolve_v2_task_media(*, client, task):
    """Refetch the Saved Messages source so Telegram supplies a fresh file_reference."""
    if task.media_source_state != "valid":
        raise TaskMediaError("MEDIA_SOURCE_UNAVAILABLE", "任务媒体来源不是 valid 状态")
    if task.media_source_account_id != task.account_id:
        raise TaskMediaError(
            "MEDIA_SOURCE_ACCOUNT_MISMATCH", "任务媒体来源账号与执行账号不一致"
        )
    if not task.media_source_message_id:
        raise TaskMediaError(
            "MEDIA_SOURCE_UNAVAILABLE", "任务缺少 Saved Messages 消息 ID"
        )

    try:
        source = await client.get_messages("me", ids=int(task.media_source_message_id))
    except Exception as exc:
        raise TaskMediaError(
            "MEDIA_SOURCE_UNAVAILABLE", "无法回读 Telegram 收藏夹媒体"
        ) from exc
    if not source or not getattr(source, "media", None):
        raise TaskMediaError("MEDIA_SOURCE_UNAVAILABLE", "Telegram 收藏夹媒体已不存在")
    try:
        classified = classify_message_media(source)
    except TaskMediaError as exc:
        raise TaskMediaError(
            "MEDIA_SOURCE_TYPE_CHANGED", "Telegram 收藏夹媒体类型已变化"
        ) from exc
    if classified.media_type != _media_value(task.media_type):
        raise TaskMediaError(
            "MEDIA_SOURCE_TYPE_CHANGED", "Telegram 收藏夹媒体类型已变化"
        )
    return source.media
