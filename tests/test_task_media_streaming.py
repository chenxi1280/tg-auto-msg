"""Cross-authorization Telegram media streaming regressions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telethon.tl.types import (
    DocumentAttributeAnimated,
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
)

from backend.task_media.contract import TaskMediaError
from backend.task_media.telegram_gateway import copy_bot_message_to_saved


def _message(media, **values):
    return SimpleNamespace(media=media, grouped_id=None, **values)


def _document(attributes):
    document = SimpleNamespace(
        id=202,
        attributes=attributes,
        mime_type="video/mp4",
        size=512,
    )
    return MessageMediaDocument(document=document)


def _photo_media(*, media_id=101, size=512):
    photo = SimpleNamespace(id=media_id, sizes=[SimpleNamespace(size=size)])
    return MessageMediaPhoto(photo=photo)


class _ChunkIterator:
    def __init__(self, *, payload=None, error=None):
        self._payload = payload
        self._error = error
        self.close = AsyncMock()

    async def __anext__(self):
        if self._error:
            raise self._error
        if self._payload is None:
            raise StopAsyncIteration
        payload = self._payload
        self._payload = None
        return payload


def _source_client(payload=b"telegram-media"):
    iterator = _ChunkIterator(payload=payload)
    return SimpleNamespace(iter_download=Mock(return_value=iterator))


def _send_file_mock(*, payload, result):
    async def send_file(_entity, *, file, file_size, **_options):
        assert file_size == len(payload)
        assert await file.read(file_size) == payload
        return result

    return AsyncMock(side_effect=send_file)


@pytest.mark.asyncio
async def test_saved_message_readback_validation_uses_copy_error_code():
    payload = b"telegram-media"
    bot_media = _photo_media(size=len(payload))
    bot_message = _message(bot_media, id=10, reply_to_msg_id=5)
    invalid_saved = _message(_document([DocumentAttributeFilename("report.pdf")]))
    client = SimpleNamespace(
        get_messages=AsyncMock(return_value=invalid_saved),
        send_file=_send_file_mock(payload=payload, result=SimpleNamespace(id=20)),
    )
    manager = SimpleNamespace(get_client=AsyncMock(return_value=client))

    with patch(
        "backend.task_media.telegram_gateway.get_account_manager",
        return_value=manager,
    ):
        with pytest.raises(TaskMediaError) as exc:
            await copy_bot_message_to_saved(
                source_client=_source_client(payload),
                account_id="acc-1",
                bot_message=bot_message,
            )

    assert exc.value.code == "MEDIA_SOURCE_COPY_FAILED"
    assert client.send_file.await_args.kwargs["file"].name.endswith(".jpg")


@pytest.mark.asyncio
async def test_operator_media_streams_through_owning_bot_session():
    payload = b"jpeg"
    bot_media = _photo_media(size=len(payload))
    bot_message = _message(bot_media, id=10, reply_to_msg_id=5)
    saved = _message(bot_media, id=20)
    client = SimpleNamespace(
        get_messages=AsyncMock(return_value=saved),
        send_file=_send_file_mock(payload=payload, result=SimpleNamespace(id=20)),
    )
    manager = SimpleNamespace(get_client=AsyncMock(return_value=client))
    source_client = _source_client(payload)

    with patch(
        "backend.task_media.telegram_gateway.get_account_manager",
        return_value=manager,
    ):
        copied = await copy_bot_message_to_saved(
            source_client=source_client,
            account_id="execution-account",
            bot_message=bot_message,
        )

    assert copied.media_type == "photo"
    assert copied.source_message_id == 10
    assert copied.saved_message_id == 20
    source_client.iter_download.assert_called_once_with(
        bot_media,
        chunk_size=len(payload),
        request_size=len(payload),
        file_size=len(payload),
    )
    kwargs = client.send_file.await_args.kwargs
    assert kwargs["caption"] is None
    assert kwargs["buttons"] is None
    assert kwargs["force_document"] is False
    assert kwargs["file_size"] == len(payload)


@pytest.mark.asyncio
async def test_video_copy_preserves_telegram_document_attributes():
    payload = b"v" * 512
    attributes = [
        DocumentAttributeFilename("clip.mp4"),
        DocumentAttributeVideo(
            duration=2,
            w=640,
            h=360,
            round_message=False,
            supports_streaming=True,
        ),
    ]
    bot_message = _message(_document(attributes), id=10, reply_to_msg_id=5)
    saved = _message(_document(attributes), id=20)
    client = SimpleNamespace(
        get_messages=AsyncMock(return_value=saved),
        send_file=_send_file_mock(payload=payload, result=SimpleNamespace(id=20)),
    )
    manager = SimpleNamespace(get_client=AsyncMock(return_value=client))

    with patch(
        "backend.task_media.telegram_gateway.get_account_manager",
        return_value=manager,
    ):
        copied = await copy_bot_message_to_saved(
            source_client=_source_client(payload),
            account_id="execution-account",
            bot_message=bot_message,
        )

    kwargs = client.send_file.await_args.kwargs
    assert copied.media_type == "video"
    assert kwargs["file"].name == "clip.mp4"
    assert kwargs["attributes"] == attributes
    assert kwargs["mime_type"] == "video/mp4"
    assert kwargs["supports_streaming"] is True


@pytest.mark.asyncio
async def test_animation_copy_preserves_telegram_document_attributes():
    payload = b"a" * 512
    attributes = [
        DocumentAttributeFilename("reaction.mp4"),
        DocumentAttributeAnimated(),
    ]
    bot_message = _message(_document(attributes), id=10, reply_to_msg_id=5)
    saved = _message(_document(attributes), id=20)
    client = SimpleNamespace(
        get_messages=AsyncMock(return_value=saved),
        send_file=_send_file_mock(payload=payload, result=SimpleNamespace(id=20)),
    )
    manager = SimpleNamespace(get_client=AsyncMock(return_value=client))

    with patch(
        "backend.task_media.telegram_gateway.get_account_manager",
        return_value=manager,
    ):
        copied = await copy_bot_message_to_saved(
            source_client=_source_client(payload),
            account_id="execution-account",
            bot_message=bot_message,
        )

    assert copied.media_type == "animation"
    assert client.send_file.await_args.kwargs["attributes"] == attributes


@pytest.mark.asyncio
async def test_source_stream_failure_never_reaches_saved_message_readback():
    bot_message = _message(_photo_media(), id=10, reply_to_msg_id=5)
    iterator = _ChunkIterator(error=RuntimeError("file reference expired"))
    source_client = SimpleNamespace(iter_download=Mock(return_value=iterator))

    async def consume_source(_entity, *, file, file_size, **_options):
        await file.read(file_size)

    client = SimpleNamespace(
        send_file=AsyncMock(side_effect=consume_source),
        get_messages=AsyncMock(),
    )
    manager = SimpleNamespace(get_client=AsyncMock(return_value=client))

    with patch(
        "backend.task_media.telegram_gateway.get_account_manager",
        return_value=manager,
    ):
        with pytest.raises(TaskMediaError) as exc:
            await copy_bot_message_to_saved(
                source_client=source_client,
                account_id="execution-account",
                bot_message=bot_message,
            )

    assert exc.value.code == "MEDIA_SOURCE_COPY_FAILED"
    assert "Bot 会话" in str(exc.value)
    client.get_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_copy_failure_releases_original_capture_prompt_for_retry():
    from backend.task_media.capture_service import try_consume_capture_reply

    capture = SimpleNamespace(capture_id="capture-1", account_id="acc-1")
    message = _message(_photo_media(), id=10, reply_to_msg_id=5)
    event = SimpleNamespace(
        sender_id=100,
        message=message,
        client=SimpleNamespace(),
        respond=AsyncMock(),
    )
    copy_error = TaskMediaError("MEDIA_SOURCE_COPY_FAILED", "copy failed")

    with (
        patch(
            "backend.task_media.capture_service._claim_capture",
            new=AsyncMock(return_value=capture),
        ),
        patch(
            "backend.task_media.capture_service.copy_bot_message_to_saved",
            new=AsyncMock(side_effect=copy_error),
        ),
        patch(
            "backend.task_media.capture_service.release_capture_for_retry",
            new=AsyncMock(),
        ) as release_capture,
        patch(
            "backend.task_media.capture_service.fail_capture",
            new=AsyncMock(),
        ) as fail_capture,
    ):
        handled = await try_consume_capture_reply(event)

    assert handled is True
    release_capture.assert_awaited_once_with(
        "capture-1", "MEDIA_SOURCE_COPY_FAILED"
    )
    fail_capture.assert_not_awaited()
    assert "继续回复原提示消息重试" in event.respond.await_args.args[0]
