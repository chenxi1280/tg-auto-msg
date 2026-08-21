"""Target-search text handling for Telegram task selectors."""
from __future__ import annotations

from loguru import logger

from backend.bot.handlers.task.selector_context import (
    get_selector_context,
    set_selector_context,
)
from backend.bot.state.fsm import FSMState, fsm_storage


def _update_search_context(user_id: int, ctx: dict, keyword: str) -> None:
    set_selector_context(
        user_id,
        task_id=str(ctx["task_id"]),
        account_id=ctx.get("account_id"),
        page=0,
        peer_filter=str(ctx.get("peer_filter") or "all"),
        search=keyword,
        draft_mode=bool(ctx.get("draft_mode")),
        draft_targets=list(ctx.get("draft_targets") or []),
        draft_trigger_mode=ctx.get("draft_trigger_mode"),
    )


async def _return_to_selector(event, user_id: int, ctx: dict) -> None:
    from backend.bot.handlers.task.target_selection import start_select_task_targets

    page = int(ctx.get("page") or 0)
    set_selector_context(
        user_id,
        task_id=str(ctx["task_id"]),
        account_id=ctx.get("account_id"),
        page=page,
        peer_filter=str(ctx.get("peer_filter") or "all"),
        search=str(ctx.get("search") or ""),
        expect_search=False,
        draft_mode=bool(ctx.get("draft_mode")),
        draft_targets=list(ctx.get("draft_targets") or []),
        draft_trigger_mode=ctx.get("draft_trigger_mode"),
    )
    await start_select_task_targets(event, user_id, str(ctx["task_id"]), page=page)


async def handle_target_search_input(event, user_id: int, text: str) -> None:
    """Apply one search keyword and return to the target selector."""
    ctx = get_selector_context(user_id)
    if not ctx:
        fsm_storage.set_state(user_id, FSMState.NONE)
        logger.warning("selector context missing during search input: user_id={}", user_id)
        await event.respond(
            "⚠️ 当前选择流程已失效。\n下一步：请重新进入任务设置或重新点击任务创建入口。"
        )
        return
    keyword = (text or "").strip()
    logger.info(
        "目标搜索输入: user_id={}, state={}, raw={!r}",
        user_id,
        fsm_storage.get_state(user_id),
        keyword,
    )
    if keyword.lower() in {"cancel", "/cancel"}:
        fsm_storage.set_state(user_id, FSMState.NONE)
        await _return_to_selector(event, user_id, ctx)
        return
    if keyword.startswith("/"):
        keyword = keyword.lstrip("/")
    if keyword.lower() in {"clear", "清空"}:
        keyword = ""
    if len(keyword) > 32:
        await event.respond("⚠️ 搜索关键词过长，请控制在 32 个字符以内。")
        return
    fsm_storage.set_state(user_id, FSMState.NONE)
    _update_search_context(user_id, ctx, keyword)
    from backend.bot.handlers.task.target_selection import start_select_task_targets

    await start_select_task_targets(event, user_id, str(ctx["task_id"]), page=0)
