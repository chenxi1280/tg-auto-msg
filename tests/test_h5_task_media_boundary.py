import pytest
from fastapi import HTTPException

from backend.h5_backend.services.task.v2_payload import prepare_v2_create_payload


def test_h5_create_requires_text_instead_of_a_media_draft():
    payload = {"enabled": False, "text": "", "media_type": "none"}

    with pytest.raises(HTTPException) as exc:
        prepare_v2_create_payload(payload)

    assert exc.value.detail["code"] == "TASK_CONTENT_REQUIRED"


def test_h5_create_accepts_text_and_forces_no_media():
    payload = {"text": "通知内容", "media_type": "none"}

    prepare_v2_create_payload(payload)

    assert payload["text"] == "通知内容"
    assert payload["media_type"] == "none"
    assert payload["media_source_state"] == "none"
