"""
FSM 状态机定义
"""
from __future__ import annotations

import time
from enum import Enum

# FSM 状态过期时间（秒）
_FSM_TTL_SECONDS = 30 * 60  # 30 分钟


class FSMState(str, Enum):
    """FSM 状态枚举"""
    NONE = "none"  # 默认状态
    WAIT_TEXT = "wait_text"  # 等待输入文本
    WAIT_DAY_START = "wait_day_start"  # 等待选择时段开始小时
    WAIT_DAY_END = "wait_day_end"  # 等待选择时段结束小时
    WAIT_START_AT = "wait_start_at"  # 等待输入开始时间
    WAIT_END_AT = "wait_end_at"  # 等待输入结束时间
    WAIT_INTERVAL = "wait_interval"  # 等待选择重复间隔
    WAIT_TARGET_SEARCH = "wait_target_search"  # 等待输入目标聊天搜索词
    WAIT_SHORTCUT_LABEL = "wait_shortcut_label"  # 等待输入快捷按钮名称
    WAIT_TASK_CREATE_TEXT = "wait_task_create_text"  # 等待输入新任务文本
    WAIT_REGISTER_USERNAME = "wait_register_username"  # 等待输入注册用户名
    WAIT_REGISTER_PASSWORD = "wait_register_password"  # 等待输入注册密码
    WAIT_REGISTER_EMAIL = "wait_register_email"  # 等待输入注册邮箱
    WAIT_ACTIVATION_CODE = "wait_activation_code"  # 等待输入卡密
    WAIT_LOGIN_PHONE = "wait_login_phone"  # 等待输入手机号
    WAIT_LOGIN_CODE = "wait_login_code"  # 等待输入验证码
    WAIT_LOGIN_PASSWORD = "wait_login_password"  # 等待输入 Telegram 二步密码


class FSMStorage:
    """FSM 状态存储器（带 TTL 自动过期）"""

    def __init__(self, ttl_seconds: int = _FSM_TTL_SECONDS):
        self._states: dict[int, FSMState] = {}
        self._data: dict[int, dict] = {}
        self._timestamps: dict[int, float] = {}
        self._ttl = ttl_seconds
        self._cleanup_counter = 0

    def _maybe_cleanup(self) -> None:
        """每隔 100 次写操作清理一次过期条目"""
        self._cleanup_counter += 1
        if self._cleanup_counter < 100:
            return
        self._cleanup_counter = 0
        now = time.monotonic()
        expired = [uid for uid, ts in self._timestamps.items() if now - ts > self._ttl]
        for uid in expired:
            self._states.pop(uid, None)
            self._data.pop(uid, None)
            self._timestamps.pop(uid, None)

    def _touch(self, user_id: int) -> None:
        """更新用户活跃时间戳"""
        self._timestamps[user_id] = time.monotonic()

    def _is_expired(self, user_id: int) -> bool:
        ts = self._timestamps.get(user_id)
        return ts is None or (time.monotonic() - ts) > self._ttl

    def get_state(self, user_id: int) -> FSMState:
        """获取用户状态"""
        if self._is_expired(user_id):
            self.reset_state(user_id)
            return FSMState.NONE
        return self._states.get(user_id, FSMState.NONE)

    def set_state(self, user_id: int, state: FSMState) -> None:
        """设置用户状态"""
        self._maybe_cleanup()
        self._states[user_id] = state
        self._touch(user_id)

    def reset_state(self, user_id: int) -> None:
        """重置用户状态"""
        self._states.pop(user_id, None)
        self._data.pop(user_id, None)
        self._timestamps.pop(user_id, None)

    def get_data(self, user_id: int) -> dict:
        """获取用户数据"""
        if self._is_expired(user_id):
            self.reset_state(user_id)
            return {}
        return self._data.get(user_id, {})

    def update_data(self, user_id: int, **kwargs) -> None:
        """更新用户数据"""
        self._maybe_cleanup()
        if user_id not in self._data:
            self._data[user_id] = {}
        self._data[user_id].update(kwargs)
        self._touch(user_id)


# 全局 FSM 存储器
fsm_storage = FSMStorage()
