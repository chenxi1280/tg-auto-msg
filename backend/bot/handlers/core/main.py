"""Bot 主处理器：命令、回调按钮、消息处理。"""

from loguru import logger
from telethon import events
from telethon.errors.rpcerrorlist import MessageNotModifiedError

from backend.bot.client_runtime.manager import bot_client
from backend.bot.state.fsm import FSMState, fsm_storage
from backend.bot.handlers.task.selector_context import get_selector_context as _get_selector_context
from backend.bot.handlers.task.management import show_task_settings
from backend.bot.handlers.task.target_selection import handle_target_search_input
from backend.bot.handlers.core.callback_dispatch import dispatch_callback
from backend.bot.handlers.core.message_dispatch import dispatch_message_by_state
from backend.bot.handlers.core.command_handlers import (
    dispatch_short_command,
    handle_bind_command,
    handle_start_command,
)


# ============ 命令处理 ============

@bot_client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """开始命令"""
    await handle_start_command(event)


@bot_client.on(events.NewMessage(func=lambda e: bool((e.raw_text or "").strip().startswith("/"))))
async def command_trace_handler(event):
    """记录收到的命令，便于定位 Bot 不回包问题。"""
    if getattr(event, "out", False):
        return
    text = (event.raw_text or "").strip().replace("\n", "\\n")
    if len(text) > 120:
        text = text[:117] + "..."
    logger.info(
        f"收到命令: sender={event.sender_id}, chat={event.chat_id}, text={text!r}"
    )


@bot_client.on(events.NewMessage())
async def bind_handler(event):
    """绑定账号命令 /bind <code>"""
    await handle_bind_command(event)


@bot_client.on(events.NewMessage(pattern=r'(?i)^/(tasks|accounts|sync|proxy)(?:@[\w\d_]+)?(?:\s+.*)?$'))
async def short_commands_handler(event):
    """短命令入口：/tasks /accounts /sync /proxy"""
    await dispatch_short_command(event)


# ============ 新增回调处理 ============

@bot_client.on(events.CallbackQuery())
async def callback_handler(event):
    """回调按钮处理"""
    try:
        user_id = event.sender_id
        data = event.data.decode()

        # 重置 FSM 状态
        current_state = fsm_storage.get_state(user_id)

        # 如果不在 FSM 等待状态，则处理回调
        if current_state == FSMState.NONE:
            await handle_callback(event, user_id, data)
        else:
            # 在等待输入状态，只允许取消
            if data.startswith("settings:"):
                fsm_storage.reset_state(user_id)
                task_id = data.split(":")[1]
                await show_task_settings(event, user_id, task_id)
            elif current_state == FSMState.WAIT_TARGET_SEARCH and data.startswith("pick_"):
                fsm_storage.set_state(user_id, FSMState.NONE)
                await handle_callback(event, user_id, data)
            else:
                await event.answer("请先完成当前输入，或点击取消", alert=True)
    except MessageNotModifiedError:
        # 点击刷新/重复点击同一选项时，内容可能完全一致。
        # Telethon 会抛 MessageNotModifiedError，这不是业务错误。
        try:
            await event.answer("已是最新内容")
        except Exception:
            pass
    except Exception as e:
        logger.exception(f"回调处理失败: {type(e).__name__}: {e!r}")
        await event.answer("操作失败，请稍后重试", alert=True)


async def handle_callback(event, user_id: int, data: str):
    """处理所有回调按钮（委托到 callback_dispatch）。"""
    await dispatch_callback(event, user_id, data)


@bot_client.on(events.NewMessage(func=lambda e: e.sender_id))
async def message_handler(event):
    """处理用户输入消息（FSM 状态）"""
    user_id = event.sender_id
    state = fsm_storage.get_state(user_id)

    if state == FSMState.NONE:
        # 容错：如果搜索输入状态丢失，但选择器上下文仍在，继续按搜索词处理
        selector_ctx = _get_selector_context(user_id)
        if selector_ctx and selector_ctx.get("expect_search"):
            await handle_target_search_input(event, user_id, event.message.message or "")
        return

    # 根据状态处理输入
    data = fsm_storage.get_data(user_id)
    task_id = data.get("task_id")

    await dispatch_message_by_state(event, user_id, state, task_id)
