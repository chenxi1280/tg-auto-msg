"""Selector context helpers for task target picking flow."""
from __future__ import annotations

from typing import Any, Optional

from backend.bot.state.fsm import fsm_storage
from backend.bot.handlers.core.helpers import normalize_target_filter

TASK_SELECTOR_KEY = "task_selector_ctx"


def set_selector_context(
    user_id: int,
    *,
    task_id: str,
    account_id: Optional[str] = None,
    page: int = 0,
    peer_filter: str = "all",
    search: str = "",
    expect_search: bool = False,
    draft_mode: bool = False,
    draft_targets: Optional[list[dict[str, Any]]] = None,
    draft_trigger_mode: Optional[str] = None,
) -> None:
    """Store selector context in FSM user data."""
    fsm_storage.update_data(
        user_id,
        **{
            TASK_SELECTOR_KEY: {
                "task_id": task_id,
                "account_id": account_id,
                "page": max(0, int(page)),
                "peer_filter": normalize_target_filter(peer_filter),
                "search": str(search or "").strip(),
                "expect_search": bool(expect_search),
                "draft_mode": bool(draft_mode),
                "draft_targets": draft_targets or [],
                "draft_trigger_mode": draft_trigger_mode,
            }
        }
    )


def get_selector_context(user_id: int) -> Optional[dict[str, Any]]:
    """Load selector context from FSM user data."""
    data = fsm_storage.get_data(user_id)
    ctx = data.get(TASK_SELECTOR_KEY)
    if isinstance(ctx, dict) and ctx.get("task_id"):
        return ctx
    return None


def clear_selector_context(user_id: int) -> None:
    """Clear selector context for user."""
    fsm_storage.update_data(user_id, **{TASK_SELECTOR_KEY: None})
