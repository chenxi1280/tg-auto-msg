from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backend.task_media.capture_authorization import resolve_capture_actor
from backend.task_media.contract import utc_now


@pytest.mark.asyncio
async def test_bot_capture_uses_linked_operator_not_execution_account():
    with patch(
        "backend.task_media.capture_authorization.get_linked_system_user_id",
        new=AsyncMock(return_value=7),
    ):
        actor_id = await resolve_capture_actor(
            session=object(), user_id=7, actor_tg_user_id=100
        )
    assert actor_id == 100


@pytest.mark.asyncio
async def test_h5_capture_is_claimed_by_the_first_authorized_operator():
    actor_id = await resolve_capture_actor(
        session=object(), user_id=7, actor_tg_user_id=None
    )
    assert actor_id == 0


@pytest.mark.asyncio
async def test_capture_rejects_an_operator_linked_to_another_system_user():
    with patch(
        "backend.task_media.capture_authorization.get_linked_system_user_id",
        new=AsyncMock(return_value=8),
    ):
        with pytest.raises(HTTPException) as exc:
            await resolve_capture_actor(
                session=object(), user_id=7, actor_tg_user_id=100
            )
    assert exc.value.detail["code"] == "MEDIA_CAPTURE_OPERATOR_UNAUTHORIZED"


def test_first_authorized_operator_atomically_claims_h5_capture():
    from backend.task_media.capture_activation import validate_activation

    capture = SimpleNamespace(
        actor_tg_user_id=0,
        user_id=7,
        expires_at=utc_now() + timedelta(minutes=1),
        state="waiting",
        prompt_message_id=None,
    )
    error = validate_activation(capture, 100, linked_user_id=7)
    assert error is None
    assert capture.actor_tg_user_id == 100


def test_unlinked_operator_cannot_claim_h5_capture():
    from backend.task_media.capture_activation import validate_activation

    capture = SimpleNamespace(
        actor_tg_user_id=0,
        user_id=7,
        expires_at=utc_now() + timedelta(minutes=1),
        state="waiting",
        prompt_message_id=None,
    )
    error = validate_activation(capture, 100, linked_user_id=8)
    assert error.code == "MEDIA_CAPTURE_OPERATOR_MISMATCH"
    assert capture.actor_tg_user_id == 0
