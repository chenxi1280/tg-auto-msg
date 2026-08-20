"""Bot 主处理器：命令、回调按钮、消息处理。"""

from fastapi import HTTPException
from loguru import logger
from telethon import events
from telethon.errors.rpcerrorlist import MessageNotModifiedError

from backend.bot.account.reauth import (
    get_reauth_required_message,
    is_reauth_required_error_message,
)
from backend.bot.client_runtime.manager import bot_client
from backend.bot.state.fsm import FSMState, fsm_storage
from backend.bot.handlers.task.selector_context import get_selector_context as _get_selector_context
from backend.bot.handlers.task.management import show_task_settings, try_handle_manual_shortcut_message
from backend.bot.handlers.task.target_selection import handle_target_search_input
from backend.bot.handlers.core.callback_dispatch import dispatch_callback
from backend.bot.handlers.core.message_dispatch import dispatch_message_by_state
from backend.bot.onboarding import get_onboarding_service
from backend.bot.handlers.core.command_handlers import (
    dispatch_short_command,
    handle_bind_command,
    handle_start_command,
)
from backend.h5_backend.services.admin_panel.service import get_admin_panel_service
from backend.task_media.capture_service import try_consume_capture_reply


# ============ 命令处理 ============

@bot_client.on(events.NewMessage(pattern=r'(?i)^/start(?:@[\w\d_]+)?(?:\s+.*)?$'))
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


@bot_client.on(events.NewMessage(pattern=r'(?i)^/(help|notice|login|newtask|tasks|accounts|sync|proxy)(?:@[\w\d_]+)?(?:\s+.*)?$'))
async def short_commands_handler(event):
    """短命令入口：/help /notice /login /newtask /tasks /accounts /sync /proxy"""
    await dispatch_short_command(event)


# ============ 新增回调处理 ============

@bot_client.on(events.CallbackQuery())
async def callback_handler(event):
    """回调按钮处理"""
    try:
        user_id = event.sender_id
        data = event.data.decode()

        if data.startswith("admapp:"):
            parts = data.split(":")
            if len(parts) < 3:
                await event.answer("审批参数错误", alert=True)
                return
            decision = parts[1]
            request_id = parts[2]
            await get_admin_panel_service().handle_tg_approval_callback(
                tg_user_id=int(user_id),
                request_id=request_id,
                decision="approve" if decision == "approve" else "reject",
            )
            await event.answer("审批已处理")
            try:
                await event.edit("该审批已通过 TG 完成处理。")
            except Exception:
                pass
            return

        # 重置 FSM 状态
        current_state = fsm_storage.get_state(user_id)

        # 如果不在 FSM 等待状态，则处理回调
        if current_state == FSMState.NONE:
            await handle_callback(event, user_id, data)
        else:
            # 在等待输入状态，允许取消和时间快捷按钮
            if data.startswith("settings:"):
                fsm_storage.reset_state(user_id)
                task_id = data.split(":")[1]
                await show_task_settings(event, user_id, task_id)
            elif data in {"bot_home", "bot_notice", "bot_purchase", "bot_authorization"}:
                fsm_storage.reset_state(user_id)
                await handle_callback(event, user_id, data)
            elif current_state in {
                FSMState.WAIT_REGISTER_USERNAME,
                FSMState.WAIT_REGISTER_PASSWORD,
                FSMState.WAIT_REGISTER_EMAIL,
                FSMState.WAIT_ACTIVATION_CODE,
                FSMState.WAIT_LOGIN_PASSWORD,
            } and data in {"bot_home", "bot_notice"}:
                fsm_storage.reset_state(user_id)
                await handle_callback(event, user_id, data)
            elif current_state == FSMState.WAIT_LOGIN_CODE and (
                data.startswith("bot_cancel_login:")
                or data.startswith("bot_login_code_digit:")
                or data in {
                    "bot_login_code_backspace",
                    "bot_login_code_clear",
                    "bot_login_code_submit",
                    "bot_login_code_resend",
                }
            ):
                await handle_callback(event, user_id, data)
            elif current_state == FSMState.WAIT_LOGIN_PASSWORD and data.startswith("bot_cancel_login:"):
                fsm_storage.reset_state(user_id)
                await handle_callback(event, user_id, data)
            elif current_state in {FSMState.WAIT_START_AT, FSMState.WAIT_END_AT} and data.startswith(
                ("set_start_ts:", "set_end_ts:")
            ):
                await handle_callback(event, user_id, data)
            elif current_state in {FSMState.WAIT_DAY_START, FSMState.WAIT_DAY_END} and data.startswith(
                ("set_hour:", "set_hours_allday:")
            ):
                await handle_callback(event, user_id, data)
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
    except HTTPException as e:
        detail = str(e.detail or "操作失败，请稍后重试。")
        logger.warning(f"回调处理业务失败: status={e.status_code}, detail={detail!r}")
        if is_reauth_required_error_message(detail):
            await event.answer(get_reauth_required_message(), alert=True)
            return
        await event.answer(detail, alert=True)
    except Exception as e:
        logger.exception(f"回调处理失败: {type(e).__name__}: {e!r}")
        if is_reauth_required_error_message(str(e)):
            await event.answer(get_reauth_required_message(), alert=True)
            return
        await event.answer("操作失败，请稍后重试。\n如果当前正在输入内容，可先取消后重新进入。", alert=True)


async def handle_callback(event, user_id: int, data: str):
    """处理所有回调按钮（委托到 callback_dispatch）。"""
    await dispatch_callback(event, user_id, data)


_RECOGNIZED_COMMANDS = {"start", "bind", "help", "notice", "login", "newtask", "tasks", "accounts", "sync", "proxy"}


def _extract_command_name(text: str) -> str:
    first_token = (text or "").strip().split(maxsplit=1)[0]
    if not first_token.startswith("/"):
        return ""
    command = first_token[1:]
    if "@" in command:
        command = command.split("@", 1)[0]
    return command.lower()


def _message_type(event) -> str:
    message = getattr(event, "message", None)
    if message is None:
        return "unknown"
    if getattr(message, "sticker", None):
        return "sticker"
    if getattr(message, "gif", None):
        return "gif"
    if getattr(message, "photo", None):
        return "photo"
    if getattr(message, "video", None):
        return "video"
    if getattr(message, "voice", None):
        return "voice"
    if getattr(message, "audio", None):
        return "audio"
    if getattr(message, "document", None):
        return "document"
    if getattr(message, "media", None):
        return "media"
    if getattr(message, "message", None):
        return "text"
    return "unknown"


@bot_client.on(events.NewMessage(func=lambda e: e.sender_id))
async def message_handler(event):
    """处理用户输入消息（FSM 状态）"""
    user_id = event.sender_id
    state = fsm_storage.get_state(user_id)
    onboarding_service = get_onboarding_service()
    text = (event.raw_text or event.message.message or "").strip()

    if await try_consume_capture_reply(event):
        return

    if state == FSMState.NONE:
        # 容错：如果搜索输入状态丢失，但选择器上下文仍在，继续按搜索词处理
        selector_ctx = _get_selector_context(user_id)
        if selector_ctx and selector_ctx.get("expect_search"):
            await handle_target_search_input(event, user_id, event.message.message or "")
            return

        if await try_handle_manual_shortcut_message(event, user_id, text):
            return

        command_name = _extract_command_name(text)
        if command_name in _RECOGNIZED_COMMANDS:
            return

        logger.info(
            "fallback menu reply: sender={}, chat={}, state={}, message_type={}, text_len={}",
            user_id,
            event.chat_id,
            state.value,
            _message_type(event),
            len(text),
        )

        if command_name == "cancel":
            await onboarding_service.reply_idle_main_menu(
                event,
                user_id,
                prefix_text="⚠️ 当前没有进行中的输入流程。\n下一步：请点击下方菜单继续操作，或发送 /start 重新开始。",
            )
            return

        if command_name:
            await onboarding_service.reply_idle_main_menu(
                event,
                user_id,
                prefix_text="⚠️ 未识别的命令。\n下一步：请点击下方菜单继续操作，或发送 /start 查看入口。",
            )
            return

        await onboarding_service.reply_idle_main_menu(
            event,
            user_id,
            prefix_text="⚠️ 当前你不在输入流程中。\n下一步：请点击下方菜单继续操作，或发送 /start 重新开始。",
        )
        return

    # 根据状态处理输入
    data = fsm_storage.get_data(user_id)
    task_id = data.get("task_id")

    await dispatch_message_by_state(event, user_id, state, task_id)
