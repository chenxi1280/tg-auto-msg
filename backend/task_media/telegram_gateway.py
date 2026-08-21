"""Telegram-only media streaming; no complete file buffer or local IO."""

from __future__ import annotations

from io import IOBase
import mimetypes

from loguru import logger
from telethon.tl.types import (
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
)

from backend.bot.account.manager import get_account_manager
from backend.task_media.contract import (
    ClassifiedMedia,
    SavedMediaCopy,
    TaskMediaError,
    classify_message_media,
)


class TelegramMediaStream(IOBase):
    """Async file-like bridge from one Telegram authorization to another."""

    def __init__(self, *, source_client, media, name: str, size: int):
        self.name = name
        self.size = size
        self._source_client = source_client
        self._media = media
        self._iterator = None

    async def read(self, amount: int) -> bytes:
        if self._iterator is None:
            self._iterator = self._source_client.iter_download(
                self._media,
                chunk_size=amount,
                request_size=amount,
                file_size=self.size,
            )
        try:
            chunk = await self._iterator.__anext__()
        except StopAsyncIteration:
            return b""
        except Exception as exc:
            logger.exception(
                "task media source stream failed: exception_type={}",
                type(exc).__name__,
            )
            raise TaskMediaError(
                "MEDIA_SOURCE_COPY_FAILED", "从 Bot 会话读取 Telegram 媒体失败"
            ) from exc
        return chunk if isinstance(chunk, bytes) else chunk.tobytes()

    async def aclose(self) -> None:
        if self._iterator is not None:
            await self._iterator.close()


def _source_document(message):
    media = getattr(message, "media", None)
    if not isinstance(media, MessageMediaDocument):
        return None
    return getattr(media, "document", None)


def _photo_size(message) -> int | None:
    media = getattr(message, "media", None)
    if not isinstance(media, MessageMediaPhoto):
        return None
    photo = getattr(media, "photo", None)
    sizes = list(getattr(photo, "sizes", []) or [])
    if not sizes:
        return None
    largest = sizes[-1]
    size = getattr(largest, "size", None)
    progressive = list(getattr(largest, "sizes", []) or [])
    return int(size or (max(progressive) if progressive else 0)) or None


def _source_size(message) -> int:
    document = _source_document(message)
    size = getattr(document, "size", None) or _photo_size(message)
    if not size:
        raise TaskMediaError(
            "MEDIA_SOURCE_COPY_FAILED", "无法确定 Telegram 媒体大小"
        )
    return int(size)


def _upload_filename(message, classified: ClassifiedMedia) -> str:
    document = _source_document(message)
    for attribute in list(getattr(document, "attributes", []) or []):
        if isinstance(attribute, DocumentAttributeFilename):
            name = str(attribute.file_name).replace("\\", "/").rsplit("/", 1)[-1]
            if name:
                return name
    mime_type = getattr(document, "mime_type", None)
    extension = mimetypes.guess_extension(mime_type or "") or ".bin"
    if classified.media_type == "photo":
        extension = ".jpg"
    return f"task-media-{classified.telegram_media_id}{extension}"


def _upload_options(message) -> dict:
    document = _source_document(message)
    attributes = list(getattr(document, "attributes", []) or [])
    video = next(
        (item for item in attributes if isinstance(item, DocumentAttributeVideo)),
        None,
    )
    options = {"force_document": False}
    if document is None:
        return options
    options.update(
        attributes=attributes,
        mime_type=getattr(document, "mime_type", None),
        supports_streaming=bool(getattr(video, "supports_streaming", False)),
    )
    return options


async def _upload_and_readback(*, client, stream, message):
    try:
        saved = await client.send_file(
            "me",
            file=stream,
            file_size=stream.size,
            caption=None,
            buttons=None,
            **_upload_options(message),
        )
        if not saved or not getattr(saved, "id", None):
            raise RuntimeError("send_file returned no Telegram message")
        verified = await client.get_messages("me", ids=int(saved.id))
        if not verified or not getattr(verified, "media", None):
            raise RuntimeError("Saved Messages readback returned no media")
        return saved, verified
    except TaskMediaError:
        raise
    except Exception as exc:
        logger.exception(
            "task media Saved Messages upload failed: exception_type={}",
            type(exc).__name__,
        )
        raise TaskMediaError(
            "MEDIA_SOURCE_COPY_FAILED", "上传媒体到执行账号的 Telegram 收藏夹失败"
        ) from exc
    finally:
        await stream.aclose()
        stream.close()


def _verify_copy(*, classified, verified) -> ClassifiedMedia:
    try:
        saved_media = classify_message_media(verified)
    except TaskMediaError as exc:
        raise TaskMediaError(
            "MEDIA_SOURCE_COPY_FAILED", "收藏夹媒体回读校验失败"
        ) from exc
    if saved_media.media_type != classified.media_type:
        raise TaskMediaError("MEDIA_SOURCE_COPY_FAILED", "收藏夹媒体回读类型不一致")
    return saved_media


async def copy_bot_message_to_saved(
    *, source_client, account_id: str, bot_message
) -> SavedMediaCopy:
    """Stream Bot-owned media into the execution account's Saved Messages."""
    manager = get_account_manager()
    client = await manager.get_client(account_id)
    if not client:
        raise TaskMediaError("MEDIA_SOURCE_COPY_FAILED", "执行账号客户端不可用")

    classified = classify_message_media(bot_message)
    stream = TelegramMediaStream(
        source_client=source_client,
        media=bot_message.media,
        name=_upload_filename(bot_message, classified),
        size=_source_size(bot_message),
    )
    saved, verified = await _upload_and_readback(
        client=client,
        stream=stream,
        message=bot_message,
    )
    saved_media = _verify_copy(classified=classified, verified=verified)
    return SavedMediaCopy(
        media_type=classified.media_type,
        source_message_id=int(bot_message.id),
        saved_message_id=int(saved.id),
        meta=saved_media.meta,
    )
