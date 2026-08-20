"""Pure Telegram task-media contract and classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from telethon.tl.types import (
    DocumentAttributeAnimated,
    DocumentAttributeFilename,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
)

SUPPORTED_MEDIA_TYPES = frozenset({"photo", "video", "animation"})
MAX_MEDIA_CAPTION_UTF16 = 1024
MAX_TEXT_MESSAGE_UTF16 = 4096


def utc_now() -> datetime:
    """Return naive UTC for existing TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(UTC).replace(tzinfo=None)


class TaskMediaError(RuntimeError):
    """Explicit task-media domain failure."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ClassifiedMedia:
    """Safe media facts; never contains media bytes or Telegram file references."""

    media_type: str
    telegram_media_id: int
    meta: dict[str, Any]


@dataclass(frozen=True)
class SavedMediaCopy:
    """Verified Telegram-side copy facts, without media bytes or file references."""

    media_type: str
    source_message_id: int
    saved_message_id: int
    meta: dict[str, Any]


@dataclass(frozen=True)
class CaptureStart:
    """One-time capture entry returned without exposing its token hash."""

    capture_id: str
    state: str
    expires_at: datetime
    bot_deep_link: str
    required_tg_user_id: str


def utf16_length(value: str | None) -> int:
    """Return Telegram entity length units."""
    return len((value or "").encode("utf-16-le")) // 2


def validate_message_length(text: str | None, *, has_media: bool) -> None:
    """Validate final text after all mutations, without truncation."""
    limit = MAX_MEDIA_CAPTION_UTF16 if has_media else MAX_TEXT_MESSAGE_UTF16
    if utf16_length(text) <= limit:
        return
    code = "MEDIA_CAPTION_TOO_LONG" if has_media else "TEXT_MESSAGE_TOO_LONG"
    raise TaskMediaError(code, f"消息超过 Telegram 限制（{limit} UTF-16 units）")


def _document_meta(document: Any, attributes: list[Any]) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "mime_type": getattr(document, "mime_type", None),
        "size": getattr(document, "size", None),
    }
    for attribute in attributes:
        if isinstance(attribute, DocumentAttributeFilename):
            meta["filename"] = attribute.file_name
        if isinstance(attribute, DocumentAttributeVideo):
            meta.update(
                width=attribute.w,
                height=attribute.h,
                duration=attribute.duration,
            )
    return {key: value for key, value in meta.items() if value is not None}


def classify_message_media(message: Any) -> ClassifiedMedia:
    """Classify one non-album photo, video, or animation message."""
    if getattr(message, "grouped_id", None) is not None:
        raise TaskMediaError(
            "MEDIA_SOURCE_TYPE_UNSUPPORTED", "不支持相册，请只发送一份媒体"
        )

    media = getattr(message, "media", None)
    if isinstance(media, MessageMediaPhoto):
        photo_id = getattr(getattr(media, "photo", None), "id", None)
        if photo_id is None:
            raise TaskMediaError("MEDIA_SOURCE_TYPE_UNSUPPORTED", "图片媒体结构不完整")
        return ClassifiedMedia("photo", int(photo_id), {})
    if not isinstance(media, MessageMediaDocument):
        raise TaskMediaError("MEDIA_SOURCE_TYPE_UNSUPPORTED", "仅支持图片、视频或动图")

    document = getattr(media, "document", None)
    document_id = getattr(document, "id", None)
    if document_id is None:
        raise TaskMediaError("MEDIA_SOURCE_TYPE_UNSUPPORTED", "文档媒体结构不完整")
    attributes = list(getattr(document, "attributes", []) or [])
    if any(isinstance(item, DocumentAttributeSticker) for item in attributes):
        raise TaskMediaError("MEDIA_SOURCE_TYPE_UNSUPPORTED", "不支持贴纸")
    if any(isinstance(item, DocumentAttributeAnimated) for item in attributes):
        return ClassifiedMedia(
            "animation", int(document_id), _document_meta(document, attributes)
        )

    video = next(
        (item for item in attributes if isinstance(item, DocumentAttributeVideo)),
        None,
    )
    if video is not None and not bool(getattr(video, "round_message", False)):
        return ClassifiedMedia(
            "video", int(document_id), _document_meta(document, attributes)
        )
    raise TaskMediaError("MEDIA_SOURCE_TYPE_UNSUPPORTED", "仅支持图片、视频或动图")
