"""
Redis 登录管理模块

使用 Redis 存储登录会话，支持分布式部署。
替代原有的内存 LoginManager。
"""
import json
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta
from loguru import logger

import redis.asyncio as redis
from backend.config.core.settings import settings


class LoginStatus(str, Enum):
    """登录状态枚举"""
    PENDING = "pending"       # 等待扫码
    SCANNING = "scanning"     # 已扫描，等待确认
    PHONE_INPUT_REQUIRED = "phone_input_required"  # 等待输入手机号
    CODE_INPUT_REQUIRED = "code_input_required"  # 等待输入验证码
    PASSWORD_REQUIRED = "password_required"  # 需要二步密码
    CONFIRMED = "confirmed"   # 已确认，登录成功
    EXPIRED = "expired"       # 已过期
    ERROR = "error"           # 登录失败


@dataclass
class LoginSession:
    """登录会话数据类"""
    login_id: str
    status: LoginStatus
    created_at: str
    expires_at: str
    qr_url: str = ""  # TG 二维码登录 URL (tg://login?token=xxx)
    login_mode: str = "qr"
    phone_number: str = ""
    phone_code_hash: str = ""
    code_sent_at: str = ""
    code_attempts: str = "0"
    tg_user_id: str = ""
    username: str = ""
    phone: str = ""
    error: str = ""
    bind_code: str = ""
    confirmed_session_encrypted: str = ""
    password_hint: str = ""
    pending_session_encrypted: str = ""
    account_id: str = ""
    system_user_id: Optional[int] = None
    developer_app_id: Optional[int] = None


class RedisLoginManager:
    """
    Redis 登录管理器

    Redis 数据结构：
    - login:session:{login_id} - Hash，存储会话信息（TTL: 300秒）
    - login:bind:{bind_code} - Hash，存储绑定码映射（TTL: 600秒）
    - login:user:{user_id} - String，存储用户登录状态
    """

    # Redis Key 前缀
    SESSION_KEY_PREFIX = "login:session:"
    BIND_KEY_PREFIX = "login:bind:"
    USER_KEY_PREFIX = "login:user:"
    SYSTEM_BIND_KEY_PREFIX = "login:system-bind:"

    # 会话过期时间（秒）
    SESSION_TTL = 300      # 5 分钟
    BIND_CODE_TTL = 600    # 10 分钟
    SYSTEM_BIND_TTL = 600  # 10 分钟

    def __init__(self, redis_url: str | None = None):
        """
        初始化 Redis 登录管理器

        Args:
            redis_url: Redis 连接 URL，默认从配置读取
        """
        self._redis_url = redis_url or settings.redis_url
        self._redis_client: Optional[redis.Redis] = None

    async def _get_redis(self) -> redis.Redis:
        """获取 Redis 客户端（懒加载）"""
        if self._redis_client is None:
            self._redis_client = await redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        return self._redis_client

    async def close(self):
        """关闭 Redis 连接"""
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None

    # ==================== 会话管理 ====================

    async def create_session(
        self,
        login_id: str,
        expires_in: int = SESSION_TTL
    ) -> LoginSession:
        """
        创建新的登录会话

        Args:
            login_id: 登录会话 ID
            expires_in: 过期时间（秒）

        Returns:
            LoginSession 对象
        """
        r = await self._get_redis()

        now = datetime.now()
        expires_at = now + timedelta(seconds=expires_in)

        session_data = {
            "login_id": login_id,
            "status": LoginStatus.PENDING.value,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "login_mode": "qr",
            "phone_number": "",
            "phone_code_hash": "",
            "code_sent_at": "",
            "code_attempts": "0",
            "tg_user_id": "",
            "username": "",
            "phone": "",
            "error": "",
            "bind_code": "",
            "confirmed_session_encrypted": "",
            "password_hint": "",
            "pending_session_encrypted": "",
            "account_id": "",
            "system_user_id": "",
            "developer_app_id": "",
        }

        key = self.SESSION_KEY_PREFIX + login_id

        # 存储到 Redis 并设置过期时间
        await r.hset(key, mapping=session_data)
        await r.expire(key, expires_in)

        logger.info(f"创建登录会话: {login_id}")
        return LoginSession(**session_data)

    async def get_session(self, login_id: str) -> Optional[LoginSession]:
        """
        获取登录会话

        Args:
            login_id: 登录会话 ID

        Returns:
            LoginSession 对象，如果不存在或已过期返回 None
        """
        r = await self._get_redis()
        key = self.SESSION_KEY_PREFIX + login_id

        data = await r.hgetall(key)

        if not data:
            return None

        # 检查是否过期
        try:
            expires_at = datetime.fromisoformat(data.get("expires_at", ""))
            if datetime.now() > expires_at:
                # 标记为过期
                await self.update_status(login_id, LoginStatus.EXPIRED)
                expired_data = {**data, "status": LoginStatus.EXPIRED}
                raw_owner = expired_data.get("system_user_id")
                if raw_owner in ("", None):
                    expired_data["system_user_id"] = None
                else:
                    try:
                        expired_data["system_user_id"] = int(raw_owner)
                    except (TypeError, ValueError):
                        expired_data["system_user_id"] = None
                raw_app_id = expired_data.get("developer_app_id")
                if raw_app_id in ("", None):
                    expired_data["developer_app_id"] = None
                else:
                    try:
                        expired_data["developer_app_id"] = int(raw_app_id)
                    except (TypeError, ValueError):
                        expired_data["developer_app_id"] = None
                return LoginSession(**expired_data)
        except ValueError:
            # 日期格式错误，视为过期
            logger.warning(f"会话 {login_id} 的 expires_at 格式错误")
            return None

        # 转换为 LoginSession 对象
        data["status"] = LoginStatus(data.get("status", LoginStatus.PENDING.value))
        raw_owner = data.get("system_user_id")
        if raw_owner in ("", None):
            data["system_user_id"] = None
        else:
            try:
                data["system_user_id"] = int(raw_owner)
            except (TypeError, ValueError):
                data["system_user_id"] = None
        raw_app_id = data.get("developer_app_id")
        if raw_app_id in ("", None):
            data["developer_app_id"] = None
        else:
            try:
                data["developer_app_id"] = int(raw_app_id)
            except (TypeError, ValueError):
                data["developer_app_id"] = None

        return LoginSession(**data)

    async def update_status(
        self,
        login_id: str,
        status: LoginStatus,
        **kwargs
    ) -> bool:
        """
        更新会话状态

        Args:
            login_id: 登录会话 ID
            status: 新状态
            **kwargs: 其他要更新的字段

        Returns:
            是否更新成功
        """
        r = await self._get_redis()
        key = self.SESSION_KEY_PREFIX + login_id

        # 检查会话是否存在
        if not await r.exists(key):
            return False

        # 更新状态
        await r.hset(key, "status", status.value)

        # 更新其他字段
        for field, value in kwargs.items():
            if value is not None:
                await r.hset(key, field, str(value))

        logger.info(f"更新登录会话状态: {login_id} -> {status.value}")
        return True

    async def delete_session(self, login_id: str) -> bool:
        """
        删除登录会话

        Args:
            login_id: 登录会话 ID

        Returns:
            是否删除成功
        """
        r = await self._get_redis()
        key = self.SESSION_KEY_PREFIX + login_id
        result = await r.delete(key)
        return result > 0

    # ==================== StringSession 存储 ====================

    async def save_string_session(
        self,
        login_id: str,
        string_session: str,
        tg_user_id: int,
        username: str,
        phone: str
    ) -> None:
        """
        保存加密的 StringSession 到登录会话

        Args:
            login_id: 登录会话 ID
            string_session: 加密后的 StringSession
            tg_user_id: Telegram 用户 ID
            username: 用户名
            phone: 手机号

        """
        # 更新登录会话
        await self.update_status(
            login_id,
            LoginStatus.CONFIRMED,
            tg_user_id=tg_user_id,
            username=username,
            phone=phone,
            confirmed_session_encrypted=string_session,
            error="",
            password_hint="",
            pending_session_encrypted="",
        )
        logger.info(f"保存确认后的登录会话: {login_id}, tg_user_id={tg_user_id}")

    async def update_qr_url(self, login_id: str, qr_url: str) -> bool:
        """
        更新二维码 URL

        Args:
            login_id: 登录会话 ID
            qr_url: TG 二维码登录 URL (tg://login?token=xxx)

        Returns:
            是否更新成功
        """
        r = await self._get_redis()
        key = self.SESSION_KEY_PREFIX + login_id
        exists = await r.hexists(key, "login_id")
        if not exists:
            logger.warning(f"尝试更新不存在的会话的 QR URL: {login_id}")
            return False
        await r.hset(key, "qr_url", qr_url)
        logger.info(f"更新 QR URL: {login_id}")
        return True

    async def update_bind_code(self, login_id: str, bind_code: str) -> bool:
        """
        更新绑定码

        Args:
            login_id: 登录会话 ID
            bind_code: 6 位数字绑定码

        Returns:
            是否更新成功
        """
        r = await self._get_redis()
        key = self.SESSION_KEY_PREFIX + login_id
        exists = await r.hexists(key, "login_id")
        if not exists:
            logger.warning(f"尝试更新不存在的会话的 bind_code: {login_id}")
            return False
        await r.hset(key, "bind_code", bind_code)
        logger.info(f"更新 bind_code: {login_id} -> {bind_code}")
        return True

    async def update_user_info(self, login_id: str, tg_user_id: str, username: str, phone: str) -> bool:
        """
        更新用户信息

        Args:
            login_id: 登录会话 ID
            tg_user_id: Telegram 用户 ID
            username: 用户名
            phone: 手机号

        Returns:
            是否更新成功
        """
        r = await self._get_redis()
        key = self.SESSION_KEY_PREFIX + login_id
        exists = await r.hexists(key, "login_id")
        if not exists:
            logger.warning(f"尝试更新不存在的会话的用户信息: {login_id}")
            return False

        await r.hset(key, mapping={
            "tg_user_id": tg_user_id,
            "username": username,
            "phone": phone
        })
        logger.info(f"更新用户信息: {login_id} -> {username}")
        return True

    async def create_system_bind_token(self, system_user_id: int) -> str:
        """Create one-time short token for linking Bot user to system account."""
        import secrets
        import string

        r = await self._get_redis()
        alphabet = string.ascii_letters + string.digits

        token = ""
        for _ in range(10):
            candidate = "".join(secrets.choice(alphabet) for _ in range(12))
            key = self.SYSTEM_BIND_KEY_PREFIX + candidate
            if not await r.exists(key):
                token = candidate
                await r.set(key, str(int(system_user_id)), ex=self.SYSTEM_BIND_TTL)
                break

        if not token:
            raise RuntimeError("生成 Bot 绑定凭证失败，请稍后重试")
        return token

    async def consume_system_bind_token(self, token: str) -> Optional[int]:
        """Consume one-time token and return system user id."""
        r = await self._get_redis()
        key = self.SYSTEM_BIND_KEY_PREFIX + str(token).strip()
        value = await r.get(key)
        if not value:
            return None
        await r.delete(key)
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    async def get_account_by_bind_code(self, bind_code: str) -> Optional[Dict[str, Any]]:
        """
        通过绑定码获取账号信息

        Args:
            bind_code: 6 位绑定码

        Returns:
            账号信息字典，如果不存在或已过期返回 None
        """
        r = await self._get_redis()
        key = self.BIND_KEY_PREFIX + bind_code

        data = await r.hgetall(key)

        if not data:
            return None

        # 转换类型
        data["tg_user_id"] = int(data.get("tg_user_id", 0))
        system_user_id = data.get("system_user_id")
        if system_user_id not in (None, ""):
            data["system_user_id"] = int(system_user_id)
        developer_app_id = data.get("developer_app_id")
        if developer_app_id not in (None, ""):
            data["developer_app_id"] = int(developer_app_id)
        return data

    async def consume_bind_code(self, bind_code: str) -> bool:
        """
        消费绑定码（绑定后删除）

        Args:
            bind_code: 6 位绑定码

        Returns:
            是否消费成功
        """
        r = await self._get_redis()
        key = self.BIND_KEY_PREFIX + bind_code
        result = await r.delete(key)
        return result > 0

    # ==================== 用户登录状态 ====================

    async def set_user_logged_in(self, user_id: int) -> None:
        """
        设置用户已登录

        Args:
            user_id: Telegram 用户 ID
        """
        r = await self._get_redis()
        key = self.USER_KEY_PREFIX + str(user_id)
        await r.set(key, "1")
        logger.info(f"用户已登录: {user_id}")

    async def is_user_logged_in(self, user_id: int) -> bool:
        """
        检查用户是否已登录

        Args:
            user_id: Telegram 用户 ID

        Returns:
            是否已登录
        """
        r = await self._get_redis()
        key = self.USER_KEY_PREFIX + str(user_id)
        return await r.exists(key) > 0

    # ==================== 清理 ====================

    async def cleanup_expired_sessions(self) -> int:
        """
        清理过期会话（Redis 会自动过期，这里主要用于日志）

        Returns:
            清理的数量
        """
        # Redis 会自动清理过期键，这里主要是记录日志
        r = await self._get_redis()

        # 扫描所有登录会话键
        count = 0
        async for key in r.scan_iter(match=self.SESSION_KEY_PREFIX + "*"):
            # 检查 TTL
            ttl = await r.ttl(key)
            if ttl == -1:  # 没有设置过期时间，异常情况
                await r.delete(key)
                count += 1

        if count > 0:
            logger.info(f"清理无过期时间的会话: {count} 个")

        return count


# 全局单例
_redis_login_manager: Optional[RedisLoginManager] = None


def get_redis_login_manager() -> RedisLoginManager:
    """获取全局 Redis 登录管理器实例"""
    global _redis_login_manager
    if _redis_login_manager is None:
        _redis_login_manager = RedisLoginManager()
    return _redis_login_manager
