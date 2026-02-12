"""
Bot 键盘定义
"""
from typing import Optional, List, Any
from telethon import Button
from telethon.tl.types import KeyboardButton, KeyboardButtonUrl

from backend.database.schema.models import ScheduledMessageTask, MediaType

# ============ 任务列表页 ============

def get_task_list_keyboard(
    tasks: list[tuple[str, bool, int, bool, bool, bool, bool]]
) -> list:
    """
    获取任务列表键盘

    Args:
        tasks: 任务列表，每个元素为 (task_id, enabled, interval, has_media, has_buttons, has_text, title)

    Returns:
        InlineKeyboardMarkup
    """
    buttons = []

    for task_id, enabled, interval, has_media, has_buttons, has_text, title in tasks:
        task_row = [
            Button.inline(f"📢 {title}", data=f"view:{task_id}"),
            Button.inline("✅" if enabled else "❌", data=f"toggle:{task_id}"),
        ]
        buttons.append(task_row)

        # 第二行：设置和删除按钮
        settings_row = [
            Button.inline("⚙️ 设置", data=f"settings:{task_id}"),
            Button.inline("🗑️ 删除", data=f"delete:{task_id}"),
        ]
        buttons.append(settings_row)

    # 底部按钮
    buttons.append([
        Button.inline("➕ 添加任务", data="add_task"),
        Button.inline("🔄 刷新", data="refresh"),
    ])

    return buttons


# ============ 任务设置页 ============

def get_task_settings_keyboard(task: ScheduledMessageTask) -> list:
    """
    获取任务设置页键盘

    Args:
        task: 任务对象

    Returns:
        InlineKeyboardMarkup
    """
    buttons = []

    # 状态开关
    buttons.append([
        Button.inline("🟢 启用", data=f"set_enable:{task.task_id}") if not task.enabled
        else Button.inline("🔴 禁用", data=f"set_disable:{task.task_id}")
    ])

    # 账号与目标选择
    buttons.append([
        Button.inline("👤 执行账号", data=f"edit_account:{task.task_id}"),
        Button.inline("🎯 目标聊天", data=f"edit_targets:{task.task_id}"),
    ])

    # 功能开关
    buttons.append([
        Button.inline(
            f"🗑️ 删除上一条 {'✅' if task.delete_previous else '❌'}",
            data=f"toggle_delete:{task.task_id}"
        ),
    ])

    buttons.append([
        Button.inline(
            f"📌 置顶 {'✅' if task.pin_message else '❌'}",
            data=f"toggle_pin:{task.task_id}"
        ),
    ])

    # 编辑入口
    buttons.append([
        Button.inline(
            f"📝 文本 {'✅' if task.text else '❌'}",
            data=f"edit_text:{task.task_id}"
        ),
        Button.inline(
            f"🖼️ 媒体 {'✅' if task.media_type != MediaType.NONE else '❌'}",
            data=f"edit_media:{task.task_id}"
        ),
        Button.inline(
            f"🔘 按钮 {'✅' if task.buttons else '❌'}",
            data=f"edit_buttons:{task.task_id}"
        ),
    ])

    # 时间控制
    buttons.append([
        Button.inline(
            f"⏰ 重复: 每 {task.repeat_interval_min} 分钟",
            data=f"edit_interval:{task.task_id}"
        ),
    ])

    buttons.append([
        Button.inline(
            f"🌅 时段: {task.day_start_hour or '-'}:00 - {task.day_end_hour or '-'}:00",
            data=f"edit_hours:{task.task_id}"
        ),
    ])

    buttons.append([
        Button.inline(
            f"📅 开始: {_format_timestamp(task.start_at)}",
            data=f"edit_start:{task.task_id}"
        ),
        Button.inline(
            f"📆 结束: {_format_timestamp(task.end_at)}",
            data=f"edit_end:{task.task_id}"
        ),
    ])

    # 返回按钮
    buttons.append([
        Button.inline("⬅️ 返回", data="back_to_list"),
    ])

    return buttons


# ============ 时间间隔选择 ============

INTERVAL_OPTIONS = [5, 10, 15, 30, 60, 120, 180, 240, 360, 720, 1440]  # 分钟


def get_interval_keyboard(task_id: str) -> list:
    """
    获取间隔时间选择键盘

    Args:
        task_id: 任务 ID

    Returns:
        InlineKeyboardMarkup
    """
    buttons = []

    row = []
    for interval in INTERVAL_OPTIONS:
        label = f"{interval}分钟" if interval < 60 else f"{interval//60}小时"
        row.append(Button.inline(label, data=f"set_interval:{task_id}:{interval}"))

        if len(row) == 3:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    # 返回按钮
    buttons.append([
        Button.inline("⬅️ 取消", data=f"settings:{task_id}"),
    ])

    return buttons


# ============ 小时选择 ============

def get_hour_select_keyboard(task_id: str, for_start: bool = True) -> list:
    """
    获取小时选择键盘

    Args:
        task_id: 任务 ID
        for_start: 是否为开始时间

    Returns:
        InlineKeyboardMarkup
    """
    buttons = []

    row = []
    for hour in range(24):
        row.append(Button.inline(f"{hour:02d}:00", data=f"set_hour:{task_id}:{for_start}:{hour}"))

        if len(row) == 6:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    # 返回按钮
    buttons.append([
        Button.inline("⬅️ 返回", data=f"settings:{task_id}"),
    ])

    return buttons


# ============ 确认删除 ============

def get_confirm_delete_keyboard(task_id: str) -> list:
    """
    获取确认删除键盘

    Args:
        task_id: 任务 ID

    Returns:
        InlineKeyboardMarkup
    """
    return [
        [
            Button.inline("✅ 确认删除", data=f"confirm_delete:{task_id}"),
            Button.inline("❌ 取消", data="back_to_list"),
        ]
    ]


# ============ 取消按钮（用于 FSM 输入） ============

def get_cancel_keyboard(task_id: str) -> list:
    """
    获取取消键盘（用于等待输入状态）

    Args:
        task_id: 任务 ID

    Returns:
        InlineKeyboardMarkup
    """
    return [
        [
            Button.inline("❌ 取消", data=f"settings:{task_id}"),
        ]
    ]


# ============ 消息按钮构建 ============

def build_inline_buttons(buttons_data: List[Any]) -> Optional[List[List[KeyboardButtonUrl]]]:
    """
    构建内联按钮（用于发送消息）

    Args:
        buttons_data: 按钮数据（二维数组）

    Returns:
        Telegram 按钮列表或 None
    """
    if not buttons_data:
        return None

    result = []
    for row in buttons_data:
        row_buttons = []
        for btn in row:
            if isinstance(btn, dict) and "text" in btn and "url" in btn:
                row_buttons.append(Button.url(btn["text"], btn["url"]))
        if row_buttons:
            result.append(row_buttons)

    return result if result else None


# ============ 辅助函数 ============

def _format_timestamp(ts: Optional[int]) -> str:
    """
    格式化时间戳为可读字符串

    Args:
        ts: Unix 时间戳

    Returns:
        格式化后的字符串
    """
    if ts is None:
        return "未设置"
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
