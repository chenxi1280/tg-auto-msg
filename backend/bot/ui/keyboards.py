"""
Bot 键盘定义
"""
from typing import Optional, List, Any
from telethon import Button
from telethon.tl.types import KeyboardButtonUrl

from backend.database.schema.models import ScheduledMessageTask, MediaType, TaskTriggerMode

def _display_hour(hour: Optional[int]) -> str:
    """Render hour value for UI, preserving 0."""
    return "-" if hour is None else f"{hour:02d}"


def _format_time_range(start_hour: Optional[int], end_hour: Optional[int]) -> str:
    """Render time range, converting default all-day to readable label."""
    if (start_hour is None and end_hour is None) or (start_hour == 0 and end_hour == 24):
        return "全天(24h)"
    return f"{_display_hour(start_hour)}:00 - {_display_hour(end_hour)}:00"


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
            Button.inline(f"📋 {title}", data=f"view:{task_id}"),
            Button.inline("✅" if enabled else "❌", data=f"toggle:{task_id}"),
        ]
        buttons.append(task_row)

        # 第二行：设置和删除按钮
        settings_row = [
            Button.inline("⚙️ 查看设置", data=f"settings:{task_id}"),
            Button.inline("删除任务", data=f"delete:{task_id}"),
        ]
        buttons.append(settings_row)

    # 底部按钮
    buttons.append([Button.inline("⏰ 创建定时任务", data="add_scheduled_task")])
    buttons.append([Button.inline("🖱️ 创建手动任务", data="add_manual_task"), Button.inline("🔄 刷新列表", data="refresh")])
    buttons.append([
        Button.inline("🏠 返回主菜单", data="bot_home"),
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
    is_manual_shortcut = str(task.trigger_mode or TaskTriggerMode.SCHEDULED.value) == TaskTriggerMode.MANUAL_SHORTCUT.value

    # 状态开关
    buttons.append([
        Button.inline("🟢 启用任务", data=f"set_enable:{task.task_id}") if not task.enabled
        else Button.inline("🔴 禁用任务", data=f"set_disable:{task.task_id}")
    ])

    # 账号与目标选择
    buttons.append([
        Button.inline("👥 选择账号", data=f"edit_account:{task.task_id}"),
        Button.inline("📋 选择目标", data=f"edit_targets:{task.task_id}"),
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

    buttons.append([
        Button.inline(
            f"🕹️ 类型: {'手动任务' if is_manual_shortcut else '定时任务'}",
            data=f"toggle_trigger_mode:{task.task_id}",
        ),
    ])

    if is_manual_shortcut:
        slot_label = f"槽位 {task.shortcut_slot}" if task.shortcut_slot else "未加入"
        buttons.append([
            Button.inline(f"📌 快捷栏: {slot_label}", data=f"edit_shortcut_slot:{task.task_id}"),
            Button.inline("🏷️ 快捷名称", data=f"edit_shortcut_label:{task.task_id}"),
        ])
        buttons.append([
            Button.inline("🚀 立即执行一次", data=f"trigger_once:{task.task_id}"),
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
            f"🧷 按钮 {'✅' if task.buttons else '❌'}",
            data=f"edit_buttons:{task.task_id}"
        ),
    ])

    # 时间控制
    if not is_manual_shortcut:
        buttons.append([
            Button.inline(
                f"⏰ 间隔: 每 {task.repeat_interval_min} 分钟",
                data=f"edit_interval:{task.task_id}"
            ),
        ])

        buttons.append([
            Button.inline(
                f"⏰ 时段: {_format_time_range(task.day_start_hour, task.day_end_hour)}",
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

    buttons.append([
        Button.inline("📋 查看记录", data=f"task_logs:{task.task_id}"),
    ])

    # 返回按钮
    buttons.append([
        Button.inline("⬅️ 返回任务页", data="back_to_list"),
        Button.inline("🏠 返回主菜单", data="bot_home"),
    ])

    return buttons


def get_shortcut_slot_keyboard(task_id: str, current_slot: Optional[int]) -> list:
    """快捷栏位置选择。"""
    return [
        [
            Button.inline(f"{'✅ ' if current_slot == 1 else ''}槽位 1", data=f"set_shortcut_slot:{task_id}:1"),
            Button.inline(f"{'✅ ' if current_slot == 2 else ''}槽位 2", data=f"set_shortcut_slot:{task_id}:2"),
            Button.inline(f"{'✅ ' if current_slot == 3 else ''}槽位 3", data=f"set_shortcut_slot:{task_id}:3"),
        ],
        [
            Button.inline("⬅️ 返回任务设置", data=f"settings:{task_id}"),
            Button.inline("🏠 返回主菜单", data="bot_home"),
        ],
    ]


def build_reply_shortcut_keyboard(labels: List[str]) -> list:
    """Build reply keyboard for manual shortcut tasks."""
    if labels:
        return [[Button.text(label, resize=True) for label in labels[:3]]]
    return [[Button.text("🏠 主菜单", resize=True)]]


# ============ 时间间隔选择 ============

INTERVAL_OPTIONS = [60, 120, 180, 240, 360, 720, 1440]  # 分钟，Bot 定时任务最小 1 小时


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

    buttons.append([Button.inline("✏️ 自定义分钟", data=f"edit_interval_custom:{task_id}")])

    # 返回按钮
    buttons.append([
        Button.inline("⬅️ 返回任务设置", data=f"settings:{task_id}"),
        Button.inline("🏠 返回主菜单", data="bot_home"),
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

    buttons.append([Button.inline("🌐 全天 00:00-24:00", data=f"set_hours_allday:{task_id}")])

    # 返回按钮
    buttons.append([
        Button.inline("⬅️ 返回任务设置", data=f"settings:{task_id}"),
        Button.inline("🏠 返回主菜单", data="bot_home"),
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
            Button.inline("确认删除", data=f"confirm_delete:{task_id}"),
            Button.inline("⬅️ 返回任务页", data="back_to_list"),
        ]
        ,
        [Button.inline("🏠 返回主菜单", data="bot_home")]
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
            Button.inline("⬅️ 返回任务设置", data=f"settings:{task_id}"),
            Button.inline("🏠 返回主菜单", data="bot_home"),
        ]
    ]


def get_start_time_keyboard(
    task_id: str,
    now_ts: int,
    plus_10_ts: int,
    now_label: str,
    plus_10_label: str,
) -> list:
    """开始时间快捷键盘。"""
    del now_ts, plus_10_ts, now_label, plus_10_label
    return [
        [
            Button.inline("⬅️ 返回任务设置", data=f"settings:{task_id}"),
            Button.inline("🏠 返回主菜单", data="bot_home"),
        ],
    ]


def get_end_time_keyboard(
    task_id: str,
    next_midnight_ts: int,
    plus_1_day_ts: int,
    next_midnight_label: str,
    plus_1_day_label: str,
) -> list:
    """结束时间快捷键盘。"""
    del next_midnight_ts, plus_1_day_ts, next_midnight_label, plus_1_day_label
    return [
        [
            Button.inline("⬅️ 返回任务设置", data=f"settings:{task_id}"),
            Button.inline("🏠 返回主菜单", data="bot_home"),
        ],
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
