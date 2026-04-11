"""
FSM 状态机定义
"""
from enum import Enum


class FSMState(str, Enum):
    """FSM 状态枚举"""
    NONE = "none"  # 默认状态
    WAIT_TEXT = "wait_text"  # 等待输入文本
    WAIT_MEDIA = "wait_media"  # 等待发送媒体
    WAIT_BUTTONS = "wait_buttons"  # 等待输入按钮内容
    WAIT_DAY_START = "wait_day_start"  # 等待选择时段开始小时
    WAIT_DAY_END = "wait_day_end"  # 等待选择时段结束小时
    WAIT_START_AT = "wait_start_at"  # 等待输入开始时间
    WAIT_END_AT = "wait_end_at"  # 等待输入结束时间
    WAIT_INTERVAL = "wait_interval"  # 等待选择重复间隔
    WAIT_TARGET_SEARCH = "wait_target_search"  # 等待输入目标聊天搜索词
    WAIT_SHORTCUT_LABEL = "wait_shortcut_label"  # 等待输入快捷按钮名称
    WAIT_REGISTER_USERNAME = "wait_register_username"  # 等待输入注册用户名
    WAIT_REGISTER_PASSWORD = "wait_register_password"  # 等待输入注册密码
    WAIT_REGISTER_EMAIL = "wait_register_email"  # 等待输入注册邮箱
    WAIT_ACTIVATION_CODE = "wait_activation_code"  # 等待输入卡密
    WAIT_LOGIN_PHONE = "wait_login_phone"  # 等待输入手机号
    WAIT_LOGIN_CODE = "wait_login_code"  # 等待输入验证码
    WAIT_LOGIN_PASSWORD = "wait_login_password"  # 等待输入 Telegram 二步密码


# FSM 存储器（内存存储，生产环境可使用 Redis）
class FSMStorage:
    """FSM 状态存储器"""

    def __init__(self):
        self._states: dict[int, FSMState] = {}
        self._data: dict[int, dict] = {}

    def get_state(self, user_id: int) -> FSMState:
        """获取用户状态"""
        return self._states.get(user_id, FSMState.NONE)

    def set_state(self, user_id: int, state: FSMState) -> None:
        """设置用户状态"""
        self._states[user_id] = state

    def reset_state(self, user_id: int) -> None:
        """重置用户状态"""
        self._states.pop(user_id, None)
        self._data.pop(user_id, None)

    def get_data(self, user_id: int) -> dict:
        """获取用户数据"""
        return self._data.get(user_id, {})

    def update_data(self, user_id: int, **kwargs) -> None:
        """更新用户数据"""
        if user_id not in self._data:
            self._data[user_id] = {}
        self._data[user_id].update(kwargs)


# 全局 FSM 存储器
fsm_storage = FSMStorage()
