"""
二维码登录管理模块

管理 Userbot 的二维码登录流程
"""
from typing import Optional, Dict
from enum import Enum
import asyncio
from datetime import datetime, timedelta
from loguru import logger


class LoginStatus(str, Enum):
    """登录状态枚举"""
    PENDING = "pending"       # 等待扫码
    SCANNING = "scanning"     # 已扫描，等待确认
    CONFIRMED = "confirmed"   # 已确认，登录成功
    EXPIRED = "expired"       # 已过期
    ERROR = "error"           # 登录失败


class LoginSession:
    """登录会话"""

    def __init__(self, login_id: str, expires_in: int = 300):
        self.login_id = login_id
        self.status = LoginStatus.PENDING
        self.created_at = datetime.now()
        self.expires_at = self.created_at + timedelta(seconds=expires_in)
        self.phone: Optional[str] = None
        self.password: Optional[str] = None
        self.error: Optional[str] = None
        self.user_id: Optional[int] = None

    def is_expired(self) -> bool:
        """检查会话是否过期"""
        return datetime.now() > self.expires_at

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "login_id": self.login_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "phone": self.phone,
            "user_id": self.user_id,
            "error": self.error
        }


class LoginManager:
    """登录管理器 - 单例模式"""

    _instance: Optional['LoginManager'] = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 存储登录会话: login_id -> LoginSession
        self._sessions: Dict[str, LoginSession] = {}

        # 存储用户登录状态: user_id -> bool
        self._user_logins: Dict[int, bool] = {}

    def create_session(self, login_id: str, expires_in: int = 300) -> LoginSession:
        """创建新的登录会话"""
        session = LoginSession(login_id, expires_in)
        self._sessions[login_id] = session
        logger.info(f"创建登录会话: {login_id}")
        return session

    def get_session(self, login_id: str) -> Optional[LoginSession]:
        """获取登录会话"""
        session = self._sessions.get(login_id)
        if session and session.is_expired():
            session.status = LoginStatus.EXPIRED
        return session

    def update_session_status(self, login_id: str, status: LoginStatus, **kwargs) -> bool:
        """更新会话状态"""
        session = self.get_session(login_id)
        if not session:
            return False

        session.status = status
        for key, value in kwargs.items():
            if hasattr(session, key):
                setattr(session, key, value)

        logger.info(f"更新登录会话状态: {login_id} -> {status.value}")
        return True

    def set_user_logged_in(self, user_id: int):
        """设置用户已登录"""
        self._user_logins[user_id] = True
        logger.info(f"用户已登录: {user_id}")

    def is_user_logged_in(self, user_id: int) -> bool:
        """检查用户是否已登录"""
        return self._user_logins.get(user_id, False)

    def cleanup_expired_sessions(self):
        """清理过期会话"""
        now = datetime.now()
        expired_ids = [
            login_id for login_id, session in self._sessions.items()
            if now > session.expires_at
        ]
        for login_id in expired_ids:
            del self._sessions[login_id]
        if expired_ids:
            logger.info(f"清理过期会话: {len(expired_ids)} 个")


# 全局登录管理器实例
login_manager = LoginManager()
