"""
Bot 主处理器：命令、回调按钮、消息处理
"""
from datetime import datetime
from typing import Optional
import re
import hashlib
import hmac

from telethon import events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

from bot.client import bot_client, userbot_client, is_userbot_ready
from bot.fsm import fsm_storage, FSMState
from bot.keyboards import (
    get_task_list_keyboard, get_task_settings_keyboard,
    get_interval_keyboard, get_hour_select_keyboard,
    get_confirm_delete_keyboard, get_cancel_keyboard,
    build_inline_buttons, INTERVAL_OPTIONS
)
from bot.messages import *
from database.session import get_async_session
from database.models import ScheduledMessageTask, MediaType, TaskLog


# ============ 命令处理 ============

@bot_client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """开始命令"""
    user_id = event.sender_id
    fsm_storage.reset_state(user_id)

    # 检查 Userbot 是否已登录
    if not is_userbot_ready():
        # Userbot 未登录，引导用户扫码登录
        text = """👋 欢迎使用 **定时消息推送管理系统**！

⚠️ **需要先登录 Userbot**

Userbot 负责实际发送消息到群组/频道。请先完成登录：

**登录步骤：**
1. 点击下方「🔐 扫码登录」按钮
2. 在打开的页面中使用 Telegram 扫描二维码
3. 登录成功后返回 Bot 即可

💡 Userbot 登录一次即可长期使用，无需重复登录。
"""
        # 使用 WebApp URL 或直接发送链接
        keyboard = [[Button.url("🔐 扫码登录", f"{H5_BASE_URL}/login")]]
        await event.respond(text, buttons=keyboard, parse_mode='markdown')
        return

    # Userbot 已登录，显示正常欢迎消息
    text = """👋 欢迎使用 **定时消息推送管理系统**！

本系统可以帮助你在 Telegram 群组/频道中自动发送定时消息。

**主要功能：**
• 📢 定时推送消息（支持文本、媒体、按钮）
• ⏰ 灵活的时间控制（重复间隔、时段限制、起止日期）
• 🗑️ 自动删除上一条消息
• 📌 自动置顶新消息
• 🌐 H5 控制台（高级编辑）

点击下方按钮开始使用：
"""
    keyboard = [[Button.inline("📢 进入任务列表", data="task_list")]]

    await event.respond(text, buttons=keyboard, parse_mode='markdown')


@bot_client.on(events.NewMessage(pattern='/tasks'))
async def tasks_handler(event):
    """任务列表命令"""
    user_id = event.sender_id
    fsm_storage.reset_state(user_id)
    await show_task_list(event)


@bot_client.on(events.NewMessage(pattern='/bind'))
async def bind_handler(event):
    """绑定账号命令 /bind <code>"""
    user_id = event.sender_id

    # 解析绑定码
    text = event.message.message.strip()
    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        await event.respond(
            "📝 **使用方法：**`/bind <绑定码>`\n\n"
            "绑定码是 6 位数字，扫码登录成功后会显示。\n"
            "请先在 H5 页面完成扫码登录。",
            parse_mode='markdown'
        )
        return

    bind_code = parts[1].strip()

    # 验证格式
    if not bind_code.isdigit() or len(bind_code) != 6:
        await event.respond("❌ 绑定码格式错误，应为 6 位数字")
        return

    # 执行绑定
    await bind_account(event, user_id, bind_code)


@bot_client.on(events.NewMessage(pattern='/accounts'))
async def accounts_handler(event):
    """账号列表命令 /accounts"""
    user_id = event.sender_id
    await show_accounts_list(event, user_id)


@bot_client.on(events.NewMessage(pattern='/sync'))
async def sync_handler(event):
    """同步资源命令 /sync [account_id]"""
    user_id = event.sender_id
    text = event.message.message.strip()
    parts = text.split(maxsplit=1)

    account_id = None
    if len(parts) >= 2:
        account_id = parts[1].strip()

    await sync_account_resources(event, user_id, account_id)


@bot_client.on(events.NewMessage(pattern='/proxy'))
async def proxy_handler(event):
    """代理管理命令 /proxy"""
    user_id = event.sender_id
    await show_proxy_management(event, user_id)


# ============ 账号绑定功能 ============

async def bind_account(event, user_id: int, bind_code: str):
    """绑定账号"""
    from bot.account_manager import get_account_manager

    account_manager = get_account_manager()

    try:
        account = await account_manager.bind_account(user_id, bind_code)

        if account:
            text = f"""✅ **账号绑定成功！**

🔑 **账号信息**
• 用户名：@{account.username or account.account_id[:8]}
• 手机号：{account.phone or '未设置'}
• 状态：{'在线' if account.health_status == 'online' else '离线'}

• 系统正在自动同步您的群组/频道列表...
• 同步完成后即可在任务中使用该账号发送消息。

💡 您可以绑定多个账号，系统会自动选择合适的账号发送消息。"""

            keyboard = [[Button.inline("📢 查看我的账号", data="accounts_list")],
                       [Button.inline("📋 进入任务列表", data="task_list")]]
            await event.respond(text, buttons=keyboard, parse_mode='markdown')
        else:
            await event.respond(
                "❌ 绑定失败：绑定码无效或已过期\n\n"
                "请重新扫码登录获取新的绑定码。"
            )
    except Exception as e:
        logger.error(f"绑定账号失败: {e}")
        await event.respond(f"❌ 绑定失败：{str(e)}")


# ============ 账号管理功能 ============

async def show_accounts_list(event, user_id: int):
    """显示账号列表"""
    from bot.account_manager import get_account_manager
    from database.models import HealthStatus

    account_manager = get_account_manager()
    accounts = await account_manager.get_accounts(user_id)

    if not accounts:
        text = """📱 **我的账号**

您还没有绑定任何 Userbot 账号。

**绑定步骤：**
1. 点击「🔐 扫码登录」
2. 使用 Telegram 扫描二维码
3. 获得绑定码后，使用 `/bind <绑定码>` 命令绑定

💡 绑定后即可在任务中使用该账号发送消息。"""
        keyboard = [[Button.url("🔐 扫码登录", f"{H5_BASE_URL}/login")]]
    else:
        # 构建账号列表
        account_lines = []
        for acc in accounts:
            status_emoji = {
                HealthStatus.ONLINE: "🟢",
                HealthStatus.OFFLINE: "🔴",
                HealthStatus.BANNED: "⛔"
            }.get(acc.health_status, "⚪")

            flooding_info = " [⏱ FloodWait]" if acc.is_flooding else ""

            account_lines.append(
                f"{status_emoji} @{acc.username or acc.account_id[:8]}{flooding_info}\n"
                f"  已发送: {acc.messages_sent} 条"
            )

        accounts_text = "\n\n".join(account_lines)
        text = f"""📱 **我的账号** ({len(accounts)})

{accounts_text}

💡 提示：
• 点击下方「🔄 同步资源」可更新账号的群组列表
• 点击「➕ 添加账号」可绑定更多账号"""

        keyboard = [
            [Button.url("🔐 扫码登录", f"{H5_BASE_URL}/login")],
            [Button.inline("🔄 同步资源", data="sync_all")],
            [Button.inline("📋 进入任务列表", data="task_list")]
        ]

    await event.respond(text, buttons=keyboard, parse_mode='markdown')


# ============ 资源同步功能 ============

async def sync_account_resources(event, user_id: int, account_id: Optional[str]):
    """同步账号资源"""
    from bot.account_manager import get_account_manager
    from bot.resource_manager import get_resource_manager

    account_manager = get_account_manager()
    resource_manager = get_resource_manager()

    # 如果没有指定账号，获取用户的第一个账号
    if not account_id:
        accounts = await account_manager.get_accounts(user_id)
        if not accounts:
            await event.respond(
                "❌ 您还没有绑定任何账号\n\n"
                "请先使用 `/accounts` 查看账号列表，"
                "或使用「🔐 扫码登录」绑定账号。"
            )
            return
        account_id = accounts[0].account_id

    try:
        # 发送同步中消息
        status_msg = await event.respond("⏳ 正在同步资源，请稍候...")

        # 执行同步
        result = await resource_manager.full_sync(account_id)

        # 构建结果消息
        text = f"""📊 **资源同步完成**

**同步统计：**
• 总计：{result.synced} 个
• 新增：{result.new} 个
• 更新：{result.updated} 个
• 删除：{result.deleted} 个"""

        if result.error:
            text += f"\n⚠️ 错误：{result.error}"

        # 更新消息
        await status_msg.edit(text, parse_mode='markdown')

    except Exception as e:
        logger.error(f"同步资源失败: {e}")
        await event.respond(f"❌ 同步失败：{str(e)}")


# ============ 代理管理功能 ============

async def show_proxy_management(event, user_id: int):
    """显示代理管理"""
    from bot.proxy_pool import get_proxy_pool

    proxy_pool = get_proxy_pool()
    proxies = await proxy_pool.get_proxies(is_active=True, is_healthy=None)

    if not proxies:
        text = """🌐 **代理管理**

当前没有配置任何代理。

**代理功能：**
• 为每个 Userbot 账号分配独立代理
• 避免 IP 关联，提高账号安全性
• 自动健康检查和故障切换

**添加代理：**
请联系管理员添加代理配置。"""
        keyboard = [[Button.inline("📋 进入任务列表", data="task_list")]]
    else:
        # 构建代理列表
        proxy_lines = []
        for p in proxies:
            status_emoji = "🟢" if p.is_healthy else "🔴"
            assigned_info = f" → 已分配" if p.assigned_account_id else ""
            proxy_lines.append(
                f"{status_emoji} {p.proxy_type}://{p.host}:{p.port}{assigned_info}\n"
                f"  响应时间: {p.response_time_ms or '-'} ms | "
                f"使用次数: {p.usage_count}"
            )

        proxies_text = "\n\n".join(proxy_lines)
        text = f"""🌐 **代理管理** ({len(proxies)})

{proxies_text}

💡 提示：
• 健康代理会自动分配给新绑定的账号
• 系统会定期检查代理健康状态"""

        keyboard = [[Button.inline("📋 进入任务列表", data="task_list")]]

    await event.respond(text, buttons=keyboard, parse_mode='markdown')


# ============ 新增回调处理 ============

@bot_client.on(events.CallbackQuery())
async def callback_handler(event):
    """回调按钮处理"""
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
            await show_task_settings(event, task_id)
        else:
            await event.answer("请先完成当前输入，或点击取消", alert=True)


async def handle_callback(event, user_id: int, data: str):
    """处理所有回调按钮"""
    parts = data.split(":")
    action = parts[0]

    # ============ 新增回调 ============
    if action == "accounts_list":
        await show_accounts_list(event, user_id)

    elif action == "sync_all":
        # 同步所有账号的资源
        await sync_account_resources(event, user_id, None)

    # ============ 列表页操作 ============
    elif action == "task_list":
        await show_task_list(event)

    elif action == "refresh":
        await show_task_list(event)

    elif action == "add_task":
        await create_new_task(event, user_id)

    elif action == "view":
        task_id = parts[1]
        await show_task_settings(event, task_id)

    elif action == "toggle":
        task_id = parts[1]
        await toggle_task(event, task_id)

    elif action == "delete":
        task_id = parts[1]
        await confirm_delete_task(event, task_id)

    elif action == "confirm_delete":
        task_id = parts[1]
        await delete_task(event, task_id)

    elif action == "back_to_list":
        await show_task_list(event)

    # ============ 设置页操作 ============
    elif action == "settings":
        task_id = parts[1]
        await show_task_settings(event, task_id)

    elif action == "set_enable":
        task_id = parts[1]
        await update_task_enabled(event, task_id, True)

    elif action == "set_disable":
        task_id = parts[1]
        await update_task_enabled(event, task_id, False)

    elif action == "toggle_delete":
        task_id = parts[1]
        await toggle_delete_previous(event, task_id)

    elif action == "toggle_pin":
        task_id = parts[1]
        await toggle_pin_message(event, task_id)

    elif action == "edit_text":
        task_id = parts[1]
        await start_edit_text(event, user_id, task_id)

    elif action == "edit_media":
        task_id = parts[1]
        await start_edit_media(event, user_id, task_id)

    elif action == "edit_buttons":
        task_id = parts[1]
        await start_edit_buttons(event, user_id, task_id)

    elif action == "edit_interval":
        task_id = parts[1]
        await show_interval_selection(event, task_id)

    elif action == "edit_hours":
        task_id = parts[1]
        await start_edit_hours(event, user_id, task_id)

    elif action == "edit_start":
        task_id = parts[1]
        await start_edit_start_at(event, user_id, task_id)

    elif action == "edit_end":
        task_id = parts[1]
        await start_edit_end_at(event, user_id, task_id)

    elif action == "open_h5":
        task_id = parts[1]
        await open_h5_webapp(event, user_id, task_id)

    # ============ 时间选择操作 ============
    elif action == "set_interval":
        task_id = parts[1]
        interval = int(parts[2])
        await set_interval(event, task_id, interval)

    elif action == "set_hour":
        task_id = parts[1]
        is_start = parts[2] == "True"
        hour = int(parts[3])
        await set_hour(event, user_id, task_id, is_start, hour)


# ============ 消息处理（FSM 输入） ============

@bot_client.on(events.NewMessage(func=lambda e: e.sender_id))
async def message_handler(event):
    """处理用户输入消息（FSM 状态）"""
    user_id = event.sender_id
    state = fsm_storage.get_state(user_id)

    if state == FSMState.NONE:
        return

    # 根据状态处理输入
    data = fsm_storage.get_data(user_id)
    task_id = data.get("task_id")

    if state == FSMState.WAIT_TEXT:
        await handle_text_input(event, user_id, task_id, event.message.message)

    elif state == FSMState.WAIT_MEDIA:
        await handle_media_input(event, user_id, task_id, event.message.media)

    elif state == FSMState.WAIT_BUTTONS:
        await handle_buttons_input(event, user_id, task_id, event.message.message)

    elif state == FSMState.WAIT_START_AT:
        await handle_start_at_input(event, user_id, task_id, event.message.message)

    elif state == FSMState.WAIT_END_AT:
        await handle_end_at_input(event, user_id, task_id, event.message.message)


# ============ 任务列表展示 ============

async def show_task_list(event):
    """显示任务列表"""
    async with get_async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ScheduledMessageTask).order_by(ScheduledMessageTask.created_at.desc())
        )
        tasks = result.scalars().all()

    if not tasks:
        text = TASK_LIST_HEADER + TASK_EMPTY
        keyboard = [[Button.inline("➕ 添加任务", data="add_task")]]
    else:
        # 构建任务列表数据
        task_data = []
        for task in tasks:
            task_data.append((
                task.task_id,
                task.enabled,
                task.repeat_interval_min,
                task.media_type != MediaType.NONE,
                bool(task.buttons),
                bool(task.text),
                task.title[:30] + "..." if len(task.title) > 30 else task.title
            ))

        text = TASK_LIST_HEADER + f"📊 共 {len(tasks)} 个任务\n"
        keyboard = get_task_list_keyboard(task_data)

    if hasattr(event, 'edit'):
        await event.edit(text, buttons=keyboard, parse_mode='markdown')
    else:
        await event.respond(text, buttons=keyboard, parse_mode='markdown')


# ============ 任务设置展示 ============

async def show_task_settings(event, task_id: str):
    """显示任务设置页"""
    async with get_async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

    if not task:
        await event.answer("任务不存在", alert=True)
        return

    # 构建设置页面文本
    text = TASK_SETTINGS_TEMPLATE.format(
        title=task.title,
        enabled_status=STATUS_ENABLED if task.enabled else STATUS_DISABLED,
        interval=task.repeat_interval_min,
        time_range=f"{task.day_start_hour or '-'}:00 - {task.day_end_hour or '-'}:00",
        start_date=_format_timestamp(task.start_at),
        end_date=_format_timestamp(task.end_at),
        text_status=STATUS_HAS if task.text else STATUS_NOT_SET,
        media_status=task.media_type.value if task.media_type != MediaType.NONE else "无",
        buttons_status=STATUS_HAS if task.buttons else STATUS_NOT_SET,
        delete_status=STATUS_YES if task.delete_previous else STATUS_NO,
        pin_status=STATUS_YES if task.pin_message else STATUS_NO,
    )

    keyboard = get_task_settings_keyboard(task)
    keyboard.append([Button.inline(OPEN_H5_BUTTON, data=f"open_h5:{task_id}")])

    if hasattr(event, 'edit'):
        await event.edit(text, buttons=keyboard, parse_mode='markdown')
    else:
        await event.respond(text, buttons=keyboard, parse_mode='markdown')


# ============ 任务操作 ============

async def create_new_task(event, user_id: int):
    """创建新任务"""
    import uuid
    task_id = str(uuid.uuid4())

    async with get_async_session() as session:
        task = ScheduledMessageTask(
            task_id=task_id,
            user_id=user_id,
            chat_id=0,  # 需要用户设置
            title="新任务",
            repeat_interval_min=60,
            enabled=False,
        )
        session.add(task)
        await session.commit()

    await show_task_settings(event, task_id)


async def toggle_task(event, task_id: str):
    """切换任务启用状态"""
    async with get_async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if task:
            task.enabled = not task.enabled
            await session.commit()
            await event.answer(f"任务已{'启用' if task.enabled else '禁用'}")
            await show_task_list(event)


async def confirm_delete_task(event, task_id: str):
    """确认删除任务"""
    async with get_async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if task:
            text = CONFIRM_DELETE.format(title=task.title)
            keyboard = get_confirm_delete_keyboard(task_id)
            await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def delete_task(event, task_id: str):
    """删除任务"""
    async with get_async_session() as session:
        from sqlalchemy import delete
        await session.execute(
            delete(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        await session.commit()

    await event.answer("任务已删除")
    await show_task_list(event)


async def update_task_enabled(event, task_id: str, enabled: bool):
    """更新任务启用状态"""
    async with get_async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if task:
            task.enabled = enabled
            await session.commit()
            await event.answer(SUCCESS_TASK_ENABLED if enabled else SUCCESS_TASK_DISABLED)
            await show_task_settings(event, task_id)


async def toggle_delete_previous(event, task_id: str):
    """切换删除上一条设置"""
    async with get_async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if task:
            task.delete_previous = not task.delete_previous
            await session.commit()
            await show_task_settings(event, task_id)


async def toggle_pin_message(event, task_id: str):
    """切换置顶设置"""
    async with get_async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if task:
            task.pin_message = not task.pin_message
            await session.commit()
            await show_task_settings(event, task_id)


# ============ 编辑功能 ============

async def start_edit_text(event, user_id: int, task_id: str):
    """开始编辑文本"""
    async with get_async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            return

    fsm_storage.set_state(user_id, FSMState.WAIT_TEXT)
    fsm_storage.update_data(user_id, task_id=task_id)

    text = EDIT_TEXT_PROMPT.format(text=task.text or "（无）")
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def handle_text_input(event, user_id: int, task_id: str, text: str):
    """处理文本输入"""
    if len(text) > 4096:
        await event.respond(ERROR_TEXT_TOO_LONG)
        return

    async with get_async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if task:
            task.text = text
            await session.commit()

    fsm_storage.reset_state(user_id)
    await event.respond(SUCCESS_TEXT_UPDATED)
    await show_task_settings(event, task_id)


async def start_edit_media(event, user_id: int, task_id: str):
    """开始编辑媒体"""
    async with get_async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            return

    fsm_storage.set_state(user_id, FSMState.WAIT_MEDIA)
    fsm_storage.update_data(user_id, task_id=task_id)

    media_status = task.media_type.value if task.media_type != MediaType.NONE else "无"
    text = EDIT_MEDIA_PROMPT.format(current_media=media_status)
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def handle_media_input(event, user_id: int, task_id: str, media):
    """处理媒体输入"""
    media_type = MediaType.NONE
    file_id = None

    if isinstance(media, MessageMediaPhoto):
        media_type = MediaType.PHOTO
        file_id = media.photo.id
    elif isinstance(media, MessageMediaDocument):
        # 检测文档类型
        for attr in media.document.attributes:
            if hasattr(attr, 'video'):
                media_type = MediaType.VIDEO
            elif hasattr(attr, 'animated'):
                media_type = MediaType.ANIMATION
        file_id = media.document.id

    if media_type == MediaType.NONE:
        await event.respond(ERROR_INVALID_MEDIA)
        return

    async with get_async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if task:
            task.media_type = media_type
            task.media_file_id = str(file_id)
            await session.commit()

    fsm_storage.reset_state(user_id)
    await event.respond(SUCCESS_MEDIA_UPDATED)
    await show_task_settings(event, task_id)


async def start_edit_buttons(event, user_id: int, task_id: str):
    """开始编辑按钮"""
    async with get_async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            return

    fsm_storage.set_state(user_id, FSMState.WAIT_BUTTONS)
    fsm_storage.update_data(user_id, task_id=task_id)

    current_buttons = _format_buttons(task.buttons) if task.buttons else "无"
    text = EDIT_BUTTONS_PROMPT.format(current_buttons=current_buttons)
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def handle_buttons_input(event, user_id: int, task_id: str, text: str):
    """处理按钮输入"""
    try:
        buttons = parse_buttons(text)

        async with get_async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
            )
            task = result.scalar_one_or_none()

            if task:
                task.buttons = buttons
                await session.commit()

        fsm_storage.reset_state(user_id)
        await event.respond(SUCCESS_BUTTONS_UPDATED)
        await show_task_settings(event, task_id)

    except Exception as e:
        await event.respond(f"{ERROR_INVALID_BUTTON_FORMAT}\n错误: {str(e)}")


async def show_interval_selection(event, task_id: str):
    """显示间隔时间选择"""
    keyboard = get_interval_keyboard(task_id)
    text = SELECT_INTERVAL
    await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def set_interval(event, task_id: str, interval: int):
    """设置重复间隔"""
    async with get_async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if task:
            task.repeat_interval_min = interval
            await session.commit()
            await event.answer(SUCCESS_INTERVAL_UPDATED.format(interval=interval))
            await show_task_settings(event, task_id)


async def start_edit_hours(event, user_id: int, task_id: str):
    """开始编辑时段"""
    fsm_storage.set_state(user_id, FSMState.WAIT_DAY_START)
    fsm_storage.update_data(user_id, task_id=task_id)

    keyboard = get_hour_select_keyboard(task_id, for_start=True)
    text = SELECT_START_HOUR
    await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def set_hour(event, user_id: int, task_id: str, is_start: bool, hour: int):
    """设置小时"""
    state = fsm_storage.get_state(user_id)
    data = fsm_storage.get_data(user_id)

    if is_start:
        # 设置开始时间，然后询问结束时间
        fsm_storage.set_state(user_id, FSMState.WAIT_DAY_END)
        fsm_storage.update_data(user_id, day_start_hour=hour)

        keyboard = get_hour_select_keyboard(task_id, for_start=False)
        text = SELECT_END_HOUR
        await event.edit(text, buttons=keyboard, parse_mode='markdown')
    else:
        # 设置结束时间，保存
        day_start_hour = data.get("day_start_hour")
        day_end_hour = hour

        async with get_async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
            )
            task = result.scalar_one_or_none()

            if task:
                task.day_start_hour = day_start_hour
                task.day_end_hour = day_end_hour
                await session.commit()

        fsm_storage.reset_state(user_id)
        await event.answer(
            SUCCESS_TIME_RANGE_UPDATED.format(start=day_start_hour, end=day_end_hour)
        )
        await show_task_settings(event, task_id)


async def start_edit_start_at(event, user_id: int, task_id: str):
    """开始编辑开始时间"""
    fsm_storage.set_state(user_id, FSMState.WAIT_START_AT)
    fsm_storage.update_data(user_id, task_id=task_id)

    text = EDIT_START_AT_PROMPT
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def handle_start_at_input(event, user_id: int, task_id: str, text: str):
    """处理开始时间输入"""
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        timestamp = int(dt.timestamp())

        async with get_async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
            )
            task = result.scalar_one_or_none()

            if task:
                # 检查是否早于结束时间
                if task.end_at and timestamp >= task.end_at:
                    await event.respond(ERROR_END_BEFORE_START)
                    return

                task.start_at = timestamp
                await session.commit()

        fsm_storage.reset_state(user_id)
        await event.respond(SUCCESS_START_AT_UPDATED)
        await show_task_settings(event, task_id)

    except ValueError:
        await event.respond(ERROR_INVALID_TIME_FORMAT)


async def start_edit_end_at(event, user_id: int, task_id: str):
    """开始编辑结束时间"""
    fsm_storage.set_state(user_id, FSMState.WAIT_END_AT)
    fsm_storage.update_data(user_id, task_id=task_id)

    text = EDIT_END_AT_PROMPT
    keyboard = get_cancel_keyboard(task_id)
    await event.edit(text, buttons=keyboard, parse_mode='markdown')


async def handle_end_at_input(event, user_id: int, task_id: str, text: str):
    """处理结束时间输入"""
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        timestamp = int(dt.timestamp())

        async with get_async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
            )
            task = result.scalar_one_or_none()

            if task:
                # 检查是否早于开始时间
                if task.start_at and timestamp <= task.start_at:
                    await event.respond(ERROR_END_BEFORE_START)
                    return

                task.end_at = timestamp
                await session.commit()

        fsm_storage.reset_state(user_id)
        await event.respond(SUCCESS_END_AT_UPDATED)
        await show_task_settings(event, task_id)

    except ValueError:
        await event.respond(ERROR_INVALID_TIME_FORMAT)


async def open_h5_webapp(event, user_id: int, task_id: str):
    """打开 H5 控制台"""
    # 生成带签名的 URL
    url = generate_h5_url(user_id, task_id)

    # 使用 WebApp 或直接发送链接
    await event.answer(f"🌐 请点击下方链接进入 H5 控制台:\n{url}", alert=True)


# ============ 辅助函数 ============

def _format_timestamp(ts: Optional[int]) -> str:
    """格式化时间戳"""
    if ts is None:
        return "未设置"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def _format_buttons(buttons) -> str:
    """格式化按钮显示"""
    if not buttons:
        return "无"

    lines = []
    for row in buttons:
        btn_texts = [btn.get("text", "") for btn in row]
        lines.append(" | ".join(btn_texts))

    return "\n".join(lines)


def parse_buttons(text: str) -> list:
    """解析按钮输入"""
    buttons = []

    for line in text.strip().split("\n"):
        row = []
        parts = line.split("&&")

        for part in parts:
            part = part.strip()
            if " - " not in part:
                raise ValueError(f"按钮格式错误: {part}")

            btn_text, url = part.split(" - ", 1)
            btn_text = btn_text.strip()
            url = url.strip()

            # 自动补全 https
            if not url.startswith("http://") and not url.startswith("https://"):
                url = "https://" + url

            row.append({"text": btn_text, "url": url})

        if row:
            buttons.append(row)

    if len(buttons) > 3:
        raise ValueError("最多支持 3 行按钮")

    for row in buttons:
        if len(row) > 3:
            raise ValueError("每行最多 3 个按钮")

    return buttons


def generate_h5_url(user_id: int, task_id: str) -> str:
    """生成 H5 访问 URL（带签名）"""
    timestamp = int(datetime.now().timestamp())
    params = f"user_id={user_id}&task_id={task_id}&timestamp={timestamp}"

    # 生成签名（使用 HMAC-SHA256）
    secret = "your-secret-key"  # 应从配置中读取
    sign = hmac.new(
        secret.encode(),
        params.encode(),
        hashlib.sha256
    ).hexdigest()

    return f"{H5_BASE_URL}/task/{task_id}?{params}&sign={sign}"


# 需要导入 Button
from telethon import Button
