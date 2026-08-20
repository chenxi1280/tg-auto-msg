from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pathlib import Path

import pytest
from fastapi import HTTPException
from telethon.tl.types import (
    DocumentAttributeAnimated,
    DocumentAttributeFilename,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    MessageMediaDocument,
    MessageMediaPhoto,
)

from backend.database.schema.models import MediaType
from backend.h5_backend.services.task.payload import validate_task_payload
from backend.h5_backend.services.task.v2_payload import coerce_expected_revision
from backend.scheduler.core.task_execution import do_send_message
from backend.task_media.contract import (
    TaskMediaError,
    classify_message_media,
    utf16_length,
    validate_message_length,
)
from backend.task_media.migration import V1TaskSnapshot, parse_legacy_media_ref
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


def test_media_classifier_accepts_one_photo():
    media = MessageMediaPhoto(photo=SimpleNamespace(id=101))
    classified = classify_message_media(_message(media))
    assert classified.media_type == "photo"
    assert classified.telegram_media_id == 101


def test_animation_takes_precedence_over_video():
    attributes = [
        DocumentAttributeVideo(duration=1.5, w=320, h=240, round_message=False),
        DocumentAttributeAnimated(),
    ]
    classified = classify_message_media(_message(_document(attributes)))
    assert classified.media_type == "animation"


@pytest.mark.parametrize(
    "attributes",
    [
        [DocumentAttributeFilename("report.pdf")],
        [DocumentAttributeVideo(duration=1, w=10, h=10, round_message=True)],
    ],
)
def test_classifier_rejects_documents_and_round_videos(attributes):
    with pytest.raises(TaskMediaError, match="仅支持图片、视频或动图"):
        classify_message_media(_message(_document(attributes)))


def test_classifier_rejects_album():
    media = MessageMediaPhoto(photo=SimpleNamespace(id=101))
    with pytest.raises(TaskMediaError, match="不支持相册"):
        classify_message_media(SimpleNamespace(media=media, grouped_id=9))


@pytest.mark.parametrize(
    "media",
    [MessageMediaPhoto(photo=None), MessageMediaDocument(document=None)],
)
def test_classifier_rejects_incomplete_telegram_media(media):
    with pytest.raises(TaskMediaError, match="结构不完整"):
        classify_message_media(_message(media))


@pytest.mark.parametrize(
    "attributes",
    [
        [
            DocumentAttributeSticker(alt="🙂", stickerset=None),
            DocumentAttributeAnimated(),
        ],
        [
            DocumentAttributeSticker(alt="🙂", stickerset=None),
            DocumentAttributeVideo(duration=1, w=128, h=128, round_message=False),
        ],
    ],
)
def test_classifier_rejects_animated_and_video_stickers(attributes):
    with pytest.raises(TaskMediaError, match="不支持贴纸"):
        classify_message_media(_message(_document(attributes)))


def test_utf16_caption_limit_counts_non_bmp_characters():
    assert utf16_length("😀") == 2
    validate_message_length("😀" * 512, has_media=True)
    with pytest.raises(TaskMediaError) as exc:
        validate_message_length("😀" * 513, has_media=True)
    assert exc.value.code == "MEDIA_CAPTION_TOO_LONG"


def test_v2_payload_rejects_userbot_buttons():
    payload = {
        "repeat_interval_min": 60,
        "media_type": "none",
        "buttons": [[{"text": "官网", "url": "https://example.com"}]],
    }
    with pytest.raises(HTTPException) as exc:
        validate_task_payload(payload, current_task=None)
    assert "TASK_BUTTONS_UNSUPPORTED_FOR_USER_ACCOUNT" in str(exc.value.detail)


@pytest.mark.parametrize("value", [None, "abc", 0, -1])
def test_expected_revision_rejects_invalid_external_values(value):
    with pytest.raises(HTTPException) as exc:
        coerce_expected_revision(value)
    assert exc.value.detail["code"] == "EXPECTED_REVISION_INVALID"


def test_enabled_scheduled_task_requires_text_or_media():
    payload = {
        "repeat_interval_min": 60,
        "media_type": "none",
        "trigger_mode": "scheduled",
        "enabled": True,
        "text": None,
    }
    with pytest.raises(HTTPException, match="TASK_CONTENT_REQUIRED"):
        validate_task_payload(payload, current_task=None)


def test_v2_invalid_media_does_not_count_as_usable_content():
    current_task = SimpleNamespace(
        trigger_mode="scheduled",
        shortcut_slot=None,
        shortcut_label=None,
        repeat_interval_min=60,
        priority=0,
        content_contract_version=2,
        media_type=MediaType.PHOTO,
        media_file_id="tgmsg://acc-1/20",
        media_source_state="invalid",
        text=None,
        buttons=None,
        enabled=False,
    )
    validate_task_payload({"enabled": False}, current_task=current_task)
    with pytest.raises(HTTPException, match="MEDIA_SOURCE_UNAVAILABLE"):
        validate_task_payload({"enabled": True}, current_task=current_task)


def test_capture_rejects_buttons_before_any_telegram_copy():
    from backend.task_media.capture_service import _validate_capture_target

    task = SimpleNamespace(buttons=[[{"text": "x"}]], text=None, user_id=1)
    account = SimpleNamespace(
        user_id=1,
        tg_user_id=100,
        is_active=True,
        is_banned=False,
        reauth_required=False,
        reauth_reason=None,
    )
    with pytest.raises(HTTPException) as exc:
        _validate_capture_target(task, account)
    assert exc.value.detail["code"] == "TASK_BUTTONS_UNSUPPORTED_FOR_USER_ACCOUNT"


def test_capture_rejects_overlong_caption_before_any_telegram_copy():
    from backend.task_media.capture_service import _validate_capture_target

    task = SimpleNamespace(buttons=None, text="😀" * 513, user_id=1)
    account = SimpleNamespace(
        user_id=1,
        tg_user_id=100,
        is_active=True,
        is_banned=False,
        reauth_required=False,
        reauth_reason=None,
    )
    with pytest.raises(HTTPException) as exc:
        _validate_capture_target(task, account)
    assert exc.value.detail["code"] == "MEDIA_CAPTION_TOO_LONG"


@pytest.mark.asyncio
async def test_new_capture_does_not_cancel_processing_capture():
    from datetime import timedelta
    from backend.task_media.capture_service import _replace_waiting_capture
    from backend.task_media.contract import utc_now

    processing = SimpleNamespace(
        state="processing",
        expires_at=utc_now() + timedelta(minutes=1),
        error_code=None,
    )
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [processing]))
    )
    with pytest.raises(HTTPException) as exc:
        await _replace_waiting_capture(session, "task-1")
    assert exc.value.detail["code"] == "MEDIA_CAPTURE_PROCESSING"
    assert processing.state == "processing"


@pytest.mark.asyncio
async def test_saved_message_readback_validation_uses_copy_error_code():
    bot_media = MessageMediaPhoto(photo=SimpleNamespace(id=101))
    bot_message = _message(bot_media, id=10, reply_to_msg_id=5)
    source = _message(bot_media, id=10, reply_to_msg_id=5, out=True)
    invalid_saved = _message(_document([DocumentAttributeFilename("report.pdf")]))
    client = SimpleNamespace(
        get_entity=AsyncMock(return_value=SimpleNamespace(id=99)),
        get_messages=AsyncMock(side_effect=[source, invalid_saved]),
        send_file=AsyncMock(return_value=SimpleNamespace(id=20)),
    )
    manager = SimpleNamespace(get_client=AsyncMock(return_value=client))

    with (
        patch(
            "backend.task_media.telegram_gateway.get_account_manager",
            return_value=manager,
        ),
        patch(
            "backend.task_media.telegram_gateway.bot_client.get_me",
            new=AsyncMock(return_value=SimpleNamespace(id=99, username="system_bot")),
        ),
    ):
        with pytest.raises(TaskMediaError) as exc:
            await copy_bot_message_to_saved(account_id="acc-1", bot_message=bot_message)
    assert exc.value.code == "MEDIA_SOURCE_COPY_FAILED"


@pytest.mark.asyncio
async def test_v2_runtime_wraps_saved_message_rpc_failure():
    from backend.scheduler.core.task_media_runtime import resolve_v2_task_media

    client = SimpleNamespace(
        get_messages=AsyncMock(side_effect=RuntimeError("rpc down"))
    )
    task = SimpleNamespace(
        media_source_state="valid",
        media_source_account_id="acc-1",
        media_source_message_id=20,
        account_id="acc-1",
        media_type=MediaType.PHOTO,
    )
    with pytest.raises(TaskMediaError) as exc:
        await resolve_v2_task_media(client=client, task=task)
    assert exc.value.code == "MEDIA_SOURCE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_migration_rpc_failure_is_retained_per_task():
    from backend.task_media.migration import _migrate_snapshot

    snapshot = V1TaskSnapshot(
        task_id="task-v1",
        account_id="acc-1",
        revision=1,
        media_type="photo",
        media_file_id="tgmsg://acc-1/20",
        has_buttons=False,
        media_source_state="none",
        media_source_error_code=None,
    )
    client = SimpleNamespace(
        get_messages=AsyncMock(side_effect=RuntimeError("rpc down"))
    )
    with patch(
        "backend.task_media.migration._write_migration_failure",
        new=AsyncMock(return_value="failed"),
    ) as write_failure:
        outcome = await _migrate_snapshot(client=client, snapshot=snapshot)
    assert outcome == "failed"
    assert write_failure.await_args.kwargs["error_code"] == "MEDIA_SOURCE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_task_delete_is_rejected_during_media_copy():
    from backend.h5_backend.services.task.v2_payload import (
        reject_task_delete_while_capturing,
    )

    session = SimpleNamespace(scalar=AsyncMock(return_value="capture-1"))
    with pytest.raises(HTTPException) as exc:
        await reject_task_delete_while_capturing(session, "task-1")
    assert exc.value.detail["code"] == "MEDIA_CAPTURE_PROCESSING"


@pytest.mark.asyncio
async def test_v2_send_refetches_saved_message_media():
    stored_media = MessageMediaPhoto(photo=SimpleNamespace(id=303))
    stored = _message(stored_media)
    sent = SimpleNamespace(id=404)
    client = SimpleNamespace(
        get_messages=AsyncMock(return_value=stored),
        send_file=AsyncMock(return_value=sent),
        delete_messages=AsyncMock(),
        pin_message=AsyncMock(),
    )
    task = SimpleNamespace(
        task_id="task-v2",
        text=None,
        buttons=None,
        media_type=MediaType.PHOTO,
        content_contract_version=2,
        media_source_state="valid",
        media_source_account_id="acc-1",
        media_source_message_id=303,
        account_id="acc-1",
        delete_previous=False,
        pin_message=False,
    )

    message_id = await do_send_message(
        client=client,
        task=task,
        send_target=99,
        previous_message_id=None,
        media_ref_prefix="tgmsg://",
    )

    assert message_id == 404
    client.get_messages.assert_awaited_once_with("me", ids=303)
    assert client.send_file.await_args.kwargs["file"] is stored_media
    assert client.send_file.await_args.kwargs["buttons"] is None


@pytest.mark.asyncio
async def test_userbot_buttons_fail_without_retrying_send():
    client = SimpleNamespace(send_message=AsyncMock(), delete_messages=AsyncMock())
    task = SimpleNamespace(
        task_id="task-buttons",
        text="hello",
        buttons=[[{"text": "x", "url": "https://example.com"}]],
        media_type=MediaType.NONE,
        content_contract_version=2,
        delete_previous=False,
        pin_message=False,
    )

    with pytest.raises(TaskMediaError) as exc:
        await do_send_message(
            client=client,
            task=task,
            send_target=99,
            previous_message_id=None,
            media_ref_prefix="tgmsg://",
        )
    assert exc.value.code == "TASK_BUTTONS_UNSUPPORTED_FOR_USER_ACCOUNT"
    client.send_message.assert_not_awaited()


def test_legacy_ref_parser_is_strict_and_account_scoped():
    assert parse_legacy_media_ref("tgmsg://acc-1/456") == ("acc-1", 456)
    with pytest.raises(TaskMediaError) as exc:
        parse_legacy_media_ref("/tmp/task-video.mp4")
    assert exc.value.code == "LEGACY_MEDIA_LOCAL_PATH"


def test_new_media_surfaces_do_not_accept_server_file_uploads():
    root = Path(__file__).resolve().parents[1]
    route_source = (root / "backend/h5_backend/routers/tasks.py").read_text()
    editor_source = (root / "frontend/h5/src/views/TaskEditor.vue").read_text()
    gateway_source = (root / "backend/task_media/telegram_gateway.py").read_text()
    migration_source = (root / "backend/task_media/migration.py").read_text()
    assert "upload-media" not in route_source
    assert 'type="file"' not in editor_source
    assert "download_media" not in gateway_source
    assert "BytesIO" not in gateway_source
    assert 'ScheduledMessageTask.media_source_state != "invalid"' in migration_source


def test_task_buttons_persist_python_none_as_sql_null():
    from backend.database.schema.models import ScheduledMessageTask

    assert ScheduledMessageTask.__table__.c.buttons.type.none_as_null is True


def test_json_null_buttons_are_normalized_before_v2_migration():
    root = Path(__file__).resolve().parents[1]
    migration_source = (
        root / "sql/migrations/035_normalize_task_buttons_null.sql"
    ).read_text()
    assert "SET buttons = NULL" in migration_source
    assert "buttons::text = 'null'" in migration_source
    assert "buttons IS NULL OR buttons::text = 'null'" in migration_source
