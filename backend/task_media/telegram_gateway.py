"""Telegram-only media copy operations; no local file IO is permitted here."""

from __future__ import annotations

from backend.bot.account.manager import get_account_manager
from backend.bot.client_runtime.manager import bot_client
from backend.task_media.contract import (
    ClassifiedMedia,
    SavedMediaCopy,
    TaskMediaError,
    classify_message_media,
)


async def _resolve_source_message(*, client, message_id: int):
    try:
        bot_identity = await bot_client.get_me()
        bot_username = str(getattr(bot_identity, "username", "") or "").strip()
        if not bot_username:
            raise TaskMediaError(
                "MEDIA_SOURCE_CORRELATION_FAILED", "系统 Bot 缺少 username"
            )
        peer = await client.get_entity(bot_username)
        if int(getattr(peer, "id", 0) or 0) != int(bot_identity.id):
            raise TaskMediaError(
                "MEDIA_SOURCE_CORRELATION_FAILED", "系统 Bot 身份校验失败"
            )
        source = await client.get_messages(peer, ids=message_id)
    except TaskMediaError:
        raise
    except Exception as exc:
        raise TaskMediaError(
            "MEDIA_SOURCE_CORRELATION_FAILED",
            "执行账号无法回读系统 Bot 对话中的指定消息",
        ) from exc
    if not source or not getattr(source, "out", False):
        raise TaskMediaError(
            "MEDIA_SOURCE_CORRELATION_FAILED", "执行账号无法精确回读该媒体消息"
        )
    return source


def _verify_correlation(bot_message, source_message) -> ClassifiedMedia:
    bot_media = classify_message_media(bot_message)
    source_media = classify_message_media(source_message)
    if bot_media.media_type != source_media.media_type:
        raise TaskMediaError("MEDIA_SOURCE_CORRELATION_FAILED", "媒体类型校验不一致")
    if bot_media.telegram_media_id != source_media.telegram_media_id:
        raise TaskMediaError(
            "MEDIA_SOURCE_CORRELATION_FAILED", "Telegram 媒体标识校验不一致"
        )
    if getattr(bot_message, "reply_to_msg_id", None) != getattr(
        source_message, "reply_to_msg_id", None
    ):
        raise TaskMediaError("MEDIA_SOURCE_CORRELATION_FAILED", "回复锚点校验不一致")
    return source_media


async def copy_bot_message_to_saved(*, account_id: str, bot_message) -> SavedMediaCopy:
    """Copy an account's Bot-dialog media object to that account's Saved Messages."""
    manager = get_account_manager()
    client = await manager.get_client(account_id)
    if not client:
        raise TaskMediaError("MEDIA_SOURCE_COPY_FAILED", "执行账号客户端不可用")

    classify_message_media(bot_message)
    source = await _resolve_source_message(
        client=client, message_id=int(bot_message.id)
    )
    classified = _verify_correlation(bot_message, source)
    try:
        saved = await client.send_file(
            "me", file=source.media, caption=None, buttons=None
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
        source_message_id=int(source.id),
        saved_message_id=int(saved.id),
        meta=saved_media.meta,
    )
