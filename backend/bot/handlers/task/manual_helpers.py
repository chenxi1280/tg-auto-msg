"""Shared helpers for bot-side manual task creation and editing."""
from __future__ import annotations

from io import BytesIO

from fastapi import HTTPException
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto

from backend.bot.account.manager import get_account_manager
from backend.bot.client_runtime.manager import bot_client
from backend.database.schema.models import MediaType, ScheduledMessageTask
from backend.h5_backend.services.task.helpers import build_telegram_media_ref


def task_has_manual_content(task: ScheduledMessageTask) -> bool:
    """Return whether a task satisfies manual-task content requirements."""
    has_text = bool(str(task.text or "").strip())
    has_buttons = bool(task.buttons)
    has_media = task.media_type != MediaType.NONE and bool(str(task.media_file_id or "").strip())
    return has_text or has_buttons or has_media


def derive_uploaded_media_name(media, media_type: MediaType) -> str:
    """Derive a stable filename for one uploaded media message."""
    if isinstance(media, MessageMediaDocument):
        for attr in getattr(media.document, "attributes", []) or []:
            file_name = getattr(attr, "file_name", None)
            if file_name:
                return str(file_name)
        extensions = {
            MediaType.VIDEO: ".mp4",
            MediaType.ANIMATION: ".gif",
            MediaType.STICKER: ".webp",
        }
        ext = extensions.get(media_type, ".bin")
        return f"task-media-{getattr(media.document, 'id', 'file')}{ext}"
    if isinstance(media, MessageMediaPhoto):
        return f"task-photo-{getattr(media.photo, 'id', 'image')}.jpg"
    return "task-media.bin"


async def store_task_media_from_bot_message(*, account_id: str, event, media, media_type: MediaType) -> str:
    """Persist bot-uploaded media into account Saved Messages and return telegram media ref."""
    message = getattr(event, "message", None)
    if message is None:
        raise HTTPException(status_code=400, detail="未找到媒体消息，请重新上传后再试")

    account_manager = get_account_manager()
    client = await account_manager.get_client(account_id)
    if not client:
        raise HTTPException(status_code=400, detail="执行账号客户端不可用，请重新绑定该账号")

    raw_data = await bot_client.download_media(message, file=bytes)
    if not raw_data:
        raise HTTPException(status_code=400, detail="媒体下载失败，请重新上传后再试")

    file_buffer = BytesIO(raw_data)
    file_buffer.name = derive_uploaded_media_name(media, media_type)
    try:
        sent_msg = await client.send_file("me", file=file_buffer, caption=f"[task-media] {file_buffer.name}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"上传媒体到执行账号失败: {exc}") from exc

    return build_telegram_media_ref(account_id, int(sent_msg.id))
