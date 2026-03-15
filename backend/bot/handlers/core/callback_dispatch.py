"""Callback action dispatch for Telegram bot handlers."""
from __future__ import annotations

from typing import Optional

from loguru import logger
from telethon import Button

from backend.bot.state.fsm import FSMState, fsm_storage
from backend.bot.handlers.core.auth_gate import require_db_user_id
from backend.bot.handlers.account.management import (
    confirm_unbind_account,
    refresh_bind_code,
    relogin_account,
    set_current_account,
    show_account_menu,
    show_accounts_list,
    sync_single_account,
    sync_account_resources,
    unbind_account,
)
from backend.bot.handlers.task.target_selection import (
    _handle_pick_account,
    _handle_pick_clear,
    _handle_pick_done,
    _handle_pick_resource,
    start_select_task_account,
    start_select_task_targets,
)
from backend.bot.handlers.task.editing import (
    set_hours_allday,
    set_end_at_timestamp,
    set_hour,
    set_interval,
    set_start_at_timestamp,
    show_interval_selection,
    start_edit_buttons,
    start_edit_end_at,
    start_edit_hours,
    start_edit_media,
    start_edit_start_at,
    start_edit_text,
    toggle_delete_previous,
    toggle_pin_message,
)
from backend.bot.handlers.core.helpers import (
    login_help_text as _login_help_text,
    normalize_target_filter as _normalize_target_filter,
)
from backend.bot.handlers.task.selector_context import (
    get_selector_context as _get_selector_context,
    set_selector_context as _set_selector_context,
)
from backend.bot.handlers.task.management import (
    confirm_delete_task,
    create_new_task,
    create_new_task_for_account,
    delete_task,
    open_h5_webapp,
    show_task_list,
    show_task_settings,
    toggle_task,
    update_task_enabled,
)


async def _handle_show_login_help(event, user_id: int):
    del user_id
    await event.answer(_login_help_text(), alert=True)


async def _handle_pick_noop(event, user_id: int):
    del user_id
    await event.answer("使用上下页切换资源列表")


def _parse_task_id(parts: list[str]) -> Optional[str]:
    if len(parts) < 2 or not parts[1]:
        return None
    return parts[1]


async def _handle_set_interval_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 3:
        await event.answer("参数错误", alert=True)
        return
    task_id = parts[1]
    interval = int(parts[2])
    await set_interval(event, user_id, task_id, interval)


async def _handle_set_hour_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 4:
        await event.answer("参数错误", alert=True)
        return
    task_id = parts[1]
    is_start = parts[2] == "True"
    hour = int(parts[3])
    await set_hour(event, user_id, task_id, is_start, hour)


async def _handle_set_hours_allday_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 2:
        await event.answer("参数错误", alert=True)
        return
    task_id = parts[1]
    await set_hours_allday(event, user_id, task_id)


async def _handle_set_start_ts_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 3:
        await event.answer("参数错误", alert=True)
        return
    task_id = parts[1]
    timestamp = int(parts[2])
    await set_start_at_timestamp(event, user_id, task_id, timestamp)


async def _handle_set_end_ts_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 3:
        await event.answer("参数错误", alert=True)
        return
    task_id = parts[1]
    timestamp = int(parts[2])
    await set_end_at_timestamp(event, user_id, task_id, timestamp)


async def _handle_pick_acc_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 2:
        await event.answer("参数错误", alert=True)
        return
    await _handle_pick_account(event, user_id, parts[1])


async def _handle_pick_res_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 2:
        await event.answer("参数错误", alert=True)
        return
    await _handle_pick_resource(event, user_id, int(parts[1]))


async def _handle_pick_page_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 2:
        await event.answer("参数错误", alert=True)
        return
    ctx = _get_selector_context(user_id)
    if not ctx:
        await event.answer("会话已过期，请重新进入任务设置", alert=True)
        return
    task_id = str(ctx["task_id"])
    page = max(0, int(parts[1]))
    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=ctx.get("account_id"),
        page=page,
        peer_filter=str(ctx.get("peer_filter") or "all"),
        search=str(ctx.get("search") or ""),
        expect_search=bool(ctx.get("expect_search")),
    )
    await start_select_task_targets(event, user_id, task_id, page=page)


async def _handle_pick_type_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 2:
        await event.answer("参数错误", alert=True)
        return
    ctx = _get_selector_context(user_id)
    if not ctx:
        await event.answer("会话已过期，请重新进入任务设置", alert=True)
        return
    peer_filter = _normalize_target_filter(parts[1])
    task_id = str(ctx["task_id"])
    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=ctx.get("account_id"),
        page=0,
        peer_filter=peer_filter,
        search=str(ctx.get("search") or ""),
        expect_search=False,
    )
    await start_select_task_targets(event, user_id, task_id, page=0)


async def _handle_pick_search_callback(event, user_id: int, parts: list[str]):
    del parts
    ctx = _get_selector_context(user_id)
    if not ctx:
        await event.answer("会话已过期，请重新进入任务设置", alert=True)
        return
    fsm_storage.set_state(user_id, FSMState.WAIT_TARGET_SEARCH)
    _set_selector_context(
        user_id,
        task_id=str(ctx["task_id"]),
        account_id=ctx.get("account_id"),
        page=int(ctx.get("page") or 0),
        peer_filter=str(ctx.get("peer_filter") or "all"),
        search=str(ctx.get("search") or ""),
        expect_search=True,
    )
    fsm_storage.update_data(user_id, task_id=str(ctx["task_id"]))
    await event.respond(
        "🔎 请输入搜索关键词（支持名称/@username/ID）\n"
        "发送 `clear` 可清空搜索，发送 `/cancel` 取消输入。",
        buttons=[[Button.inline("取消搜索输入", data="pick_search_cancel")]],
        parse_mode="markdown",
    )


async def _handle_pick_search_clear_callback(event, user_id: int, parts: list[str]):
    del parts
    ctx = _get_selector_context(user_id)
    if not ctx:
        await event.answer("会话已过期，请重新进入任务设置", alert=True)
        return
    task_id = str(ctx["task_id"])
    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=ctx.get("account_id"),
        page=0,
        peer_filter=str(ctx.get("peer_filter") or "all"),
        search="",
        expect_search=False,
    )
    await start_select_task_targets(event, user_id, task_id, page=0)


async def _handle_pick_search_cancel_callback(event, user_id: int, parts: list[str]):
    del parts
    fsm_storage.set_state(user_id, FSMState.NONE)
    ctx = _get_selector_context(user_id)
    if not ctx:
        await event.answer("会话已过期，请重新进入任务设置", alert=True)
        return
    task_id = str(ctx["task_id"])
    _set_selector_context(
        user_id,
        task_id=task_id,
        account_id=ctx.get("account_id"),
        page=int(ctx.get("page") or 0),
        peer_filter=str(ctx.get("peer_filter") or "all"),
        search=str(ctx.get("search") or ""),
        expect_search=False,
    )
    await start_select_task_targets(event, user_id, task_id, page=int(ctx.get("page") or 0))


async def _handle_sync_all(event, user_id: int):
    await sync_account_resources(event, user_id, None)


async def _handle_edit_targets(event, user_id: int, task_id: str):
    await start_select_task_targets(event, user_id, task_id, page=0)


async def _handle_acc_menu_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 2:
        await event.answer("参数错误", alert=True)
        return
    await show_account_menu(event, user_id, parts[1])


async def _handle_acc_set_active_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 2:
        await event.answer("参数错误", alert=True)
        return
    await set_current_account(event, user_id, parts[1])


async def _handle_acc_sync_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 2:
        await event.answer("参数错误", alert=True)
        return
    await sync_single_account(event, user_id, parts[1])


async def _handle_acc_relogin_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 2:
        await event.answer("参数错误", alert=True)
        return
    await relogin_account(event, user_id, parts[1])


async def _handle_acc_bindcode_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 2:
        await event.answer("参数错误", alert=True)
        return
    await refresh_bind_code(event, user_id, parts[1])


async def _handle_acc_unbind_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 2:
        await event.answer("参数错误", alert=True)
        return
    await confirm_unbind_account(event, user_id, parts[1])


async def _handle_acc_unbind_confirm_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 2:
        await event.answer("参数错误", alert=True)
        return
    await unbind_account(event, user_id, parts[1])


async def _handle_acc_add_task_callback(event, user_id: int, parts: list[str]):
    if len(parts) < 2:
        await event.answer("参数错误", alert=True)
        return
    await create_new_task_for_account(event, user_id, parts[1])


_SIMPLE_ACTION_HANDLERS = {
    "accounts_list": show_accounts_list,
    "show_login_help": _handle_show_login_help,
    "sync_all": _handle_sync_all,
    "task_list": show_task_list,
    "refresh": show_task_list,
    "add_task": create_new_task,
    "back_to_list": show_task_list,
    "pick_clear": _handle_pick_clear,
    "pick_done": _handle_pick_done,
    "pick_noop": _handle_pick_noop,
}

_TASK_ACTION_HANDLERS = {
    "view": show_task_settings,
    "toggle": toggle_task,
    "delete": confirm_delete_task,
    "confirm_delete": delete_task,
    "settings": show_task_settings,
    "edit_account": start_select_task_account,
    "edit_targets": _handle_edit_targets,
    "toggle_delete": toggle_delete_previous,
    "toggle_pin": toggle_pin_message,
    "edit_text": start_edit_text,
    "edit_media": start_edit_media,
    "edit_buttons": start_edit_buttons,
    "edit_interval": show_interval_selection,
    "edit_hours": start_edit_hours,
    "edit_start": start_edit_start_at,
    "edit_end": start_edit_end_at,
    "open_h5": open_h5_webapp,
}

_SET_ENABLE_ACTIONS = {
    "set_enable": True,
    "set_disable": False,
}

_CUSTOM_ACTION_HANDLERS = {
    "set_interval": _handle_set_interval_callback,
    "set_hour": _handle_set_hour_callback,
    "set_hours_allday": _handle_set_hours_allday_callback,
    "set_start_ts": _handle_set_start_ts_callback,
    "set_end_ts": _handle_set_end_ts_callback,
    "pick_acc": _handle_pick_acc_callback,
    "pick_res": _handle_pick_res_callback,
    "pick_page": _handle_pick_page_callback,
    "pick_type": _handle_pick_type_callback,
    "pick_search": _handle_pick_search_callback,
    "pick_search_clear": _handle_pick_search_clear_callback,
    "pick_search_cancel": _handle_pick_search_cancel_callback,
    "acc_menu": _handle_acc_menu_callback,
    "acc_set_active": _handle_acc_set_active_callback,
    "acc_sync": _handle_acc_sync_callback,
    "acc_relogin": _handle_acc_relogin_callback,
    "acc_bindcode": _handle_acc_bindcode_callback,
    "acc_unbind": _handle_acc_unbind_callback,
    "acc_unbind_confirm": _handle_acc_unbind_confirm_callback,
    "acc_add_task": _handle_acc_add_task_callback,
}


async def dispatch_callback(event, user_id: int, data: str):
    """Dispatch callback action by route maps."""
    parts = data.split(":")
    action = parts[0]

    if action == "show_login_help":
        await _handle_show_login_help(event, user_id)
        return

    if await require_db_user_id(event, user_id, alert=True) is None:
        return

    simple_handler = _SIMPLE_ACTION_HANDLERS.get(action)
    if simple_handler:
        await simple_handler(event, user_id)
        return

    task_handler = _TASK_ACTION_HANDLERS.get(action)
    if task_handler:
        task_id = _parse_task_id(parts)
        if not task_id:
            await event.answer("参数错误", alert=True)
            return
        await task_handler(event, user_id, task_id)
        return

    if action in _SET_ENABLE_ACTIONS:
        task_id = _parse_task_id(parts)
        if not task_id:
            await event.answer("参数错误", alert=True)
            return
        await update_task_enabled(event, user_id, task_id, _SET_ENABLE_ACTIONS[action])
        return

    custom_handler = _CUSTOM_ACTION_HANDLERS.get(action)
    if custom_handler:
        await custom_handler(event, user_id, parts)
        return

    logger.warning(f"未处理的回调动作: action={action}, raw={data}")
