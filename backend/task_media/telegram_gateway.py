"""Telegram-only media copy operations; no local file IO is permitted here."""

from __future__ import annotations

from backend.bot.account.manager import get_account_manager
from backend.task_media.contract import (
    SavedMediaCopy,
    TaskMediaError,
    classify_message_media,
)


async def copy_bot_message_to_saved(*, account_id: str, bot_message) -> SavedMediaCopy:
    """Copy operator-submitted Telegram media to the execution account's Saved Messages."""
    manager = get_account_manager()
    client = await manager.get_client(account_id)
    if not client:
        raise TaskMediaError("MEDIA_SOURCE_COPY_FAILED", "执行账号客户端不可用")

    classified = classify_message_media(bot_message)
    try:
        saved = await client.send_file(
            "me", file=bot_message.media, caption=None, buttons=None
        )
        if not saved or not getattr(saved, "id", None):
            raise RuntimeError("send_file returned no Telegram message")
        verified = await client.get_messages("me", ids=int(saved.id))
        if not verified or not getattr(verified, "media", None):
            raise RuntimeError("Saved Messages readback returned no media")
    except Exception as exc:
        raise TaskMediaError(
            "MEDIA_SOURCE_COPY_FAILED", "复制媒体到 Telegram 收藏夹失败"
        ) from exc

    try:
        saved_media = classify_message_media(verified)
    except TaskMediaError as exc:
        raise TaskMediaError(
            "MEDIA_SOURCE_COPY_FAILED", "收藏夹媒体回读校验失败"
        ) from exc
    if saved_media.media_type != classified.media_type:
        raise TaskMediaError("MEDIA_SOURCE_COPY_FAILED", "收藏夹媒体回读类型不一致")
    return SavedMediaCopy(
        media_type=classified.media_type,
        source_message_id=int(bot_message.id),
        saved_message_id=int(saved.id),
        meta=saved_media.meta,
    )
