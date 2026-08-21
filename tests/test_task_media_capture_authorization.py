from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backend.task_media.capture_authorization import resolve_capture_actor


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
async def test_h5_capture_resolves_the_system_users_linked_operator():
    with patch(
        "backend.task_media.capture_authorization.load_latest_linked_tg_user_ids",
        new=AsyncMock(return_value={7: 100}),
    ):
        actor_id = await resolve_capture_actor(
            session=object(), user_id=7, actor_tg_user_id=None
        )
    assert actor_id == 100


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
