"""
数据库模型定义
"""
from datetime import datetime
from typing import Optional, List, Any
from enum import Enum
import uuid

from sqlalchemy import (
    Column, String, Integer, BigInteger, Boolean, DateTime, Text, Index,
    Enum as SQLEnum, JSON, func, ForeignKey, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Mapped, mapped_column, relationship

Base = declarative_base()


class MediaType(str, Enum):
    """媒体类型枚举"""
    NONE = "none"
    PHOTO = "photo"
    VIDEO = "video"
    STICKER = "sticker"
    ANIMATION = "animation"


class HealthStatus(str, Enum):
    """账号健康状态枚举"""
    ONLINE = "online"
    OFFLINE = "offline"
    BANNED = "banned"


class PeerType(str, Enum):
    """Peer 类型枚举"""
    USER = "user"
    CHAT = "chat"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class ProxyType(str, Enum):
    """代理类型枚举"""
    SOCKS5 = "socks5"
    HTTP = "http"
    MTPROTO = "mtproto"


class ScheduledMessageTask(Base):
    """定时消息任务表"""
    __tablename__ = "scheduled_message_tasks"

    # 主键
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 基础信息
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="归属用户 ID")
    account_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("accounts.account_id"), nullable=True, comment="执行账号 ID")
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="群组/频道 ID（兼容旧数据）")
    title: Mapped[str] = mapped_column(String(100), nullable=False, comment="显示名")

    # 目标 Peer 信息（新架构）
    target_peer_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="目标 Peer ID")
    target_peer_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="目标 Peer 类型")
    target_access_hash: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="目标 Access Hash")

    # 启用状态
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否启用")

    # 重复设置
    repeat_interval_min: Mapped[int] = mapped_column(Integer, nullable=False, comment="重复间隔（分钟）")
    jitter_seconds: Mapped[int] = mapped_column(Integer, default=0, comment="随机抖动秒数（0-300）")

    # 每日时段限制
    day_start_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="每日发送起始小时")
    day_end_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="每日发送结束小时")

    # 日期范围
    start_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="开始时间 Unix")
    end_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="终止时间 Unix")

    # 消息内容
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="HTML 文本（≤4096）")
    media_type: Mapped[str] = mapped_column(
        SQLEnum(MediaType), default=MediaType.NONE, comment="媒体类型"
    )
    media_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="Telegram file_id")
    buttons: Mapped[Optional[List[Any]]] = mapped_column(JSON, nullable=True, comment="二维按钮数组")

    # 执行设置
    delete_previous: Mapped[bool] = mapped_column(Boolean, default=True, comment="删除上一条")
    pin_message: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否置顶")

    # 运行状态
    last_sent_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="上次发送消息 ID")
    next_run_at: Mapped[Optional[int]] = mapped_column(BigInteger, index=True, nullable=True, comment="下次执行时间")
    failure_count: Mapped[int] = mapped_column(Integer, default=0, comment="失败次数")

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 索引
    __table_args__ = (
        Index("idx_user_chat", "user_id", "chat_id"),
        Index("idx_account_id", "account_id"),
        Index("idx_enabled_next_run", "enabled", "next_run_at"),
    )

    def __repr__(self) -> str:
        return f"<ScheduledMessageTask(id={self.task_id}, title={self.title}, enabled={self.enabled})>"


class TaskLog(Base):
    """任务执行日志表"""
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True, comment="任务 ID")
    send_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="发送时间")
    result: Mapped[str] = mapped_column(String(20), nullable=False, comment="执行结果: success/failed")
    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="错误代码")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="错误信息")
    message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="消息 ID")

    # 索引
    __table_args__ = (
        Index("idx_task_id_send_at", "task_id", "send_at"),
        Index("idx_send_at", "send_at"),
    )

    def __repr__(self) -> str:
        return f"<TaskLog(id={self.id}, task_id={self.task_id}, result={self.result})>"


class Proxy(Base):
    """代理池表"""
    __tablename__ = "proxies"

    proxy_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 代理配置
    proxy_type: Mapped[str] = mapped_column(String(10), nullable=False, comment="代理类型: socks5/http/mtproto")
    host: Mapped[str] = mapped_column(String(255), nullable=False, comment="代理主机")
    port: Mapped[int] = mapped_column(Integer, nullable=False, comment="代理端口")
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="代理认证用户名")
    password_encrypted: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="加密存储的密码")

    # 健康状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    is_healthy: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否健康")
    last_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最后检查时间")
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="响应时间（毫秒）")

    # 使用统计
    usage_count: Mapped[int] = mapped_column(Integer, default=0, comment="使用次数")
    assigned_account_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("accounts.account_id"), nullable=True, comment="分配给的账号")

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关系
    assigned_account: Mapped[Optional["Account"]] = relationship(
        "Account",
        foreign_keys=[assigned_account_id],
        uselist=False  # 一对一：一个代理只能分配给一个账号
    )

    # 索引和约束
    __table_args__ = (
        UniqueConstraint("proxy_type", "host", "port", name="unique_proxy"),
        Index("idx_proxies_is_active", "is_active", "is_healthy"),
        Index("idx_proxies_assigned", "assigned_account_id"),
    )

    def __repr__(self) -> str:
        return f"<Proxy(id={self.proxy_id}, type={self.proxy_type}, host={self.host}:{self.port})>"


class Account(Base):
    """Userbot 账号管理表"""
    __tablename__ = "accounts"

    # 主键
    account_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 用户信息
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="归属用户 UID（Telegram）")
    tg_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True, comment="登录后的 Telegram UID")
    username: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="Telegram 用户名")
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="名字")
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="手机号")

    # 登录凭证（加密存储）
    string_session_encrypted: Mapped[str] = mapped_column(Text, nullable=False, comment="AES-256-GCM 加密的 StringSession")
    bind_code: Mapped[Optional[str]] = mapped_column(String(6), unique=True, nullable=True, comment="6位绑定码")
    bind_code_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="绑定码过期时间")

    # 代理配置
    proxy_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("proxies.proxy_id"), nullable=True, comment="关联代理 ID")

    # 账号状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否被封禁")
    health_status: Mapped[str] = mapped_column(String(20), default=HealthStatus.ONLINE, comment="健康状态: online/offline/banned")

    # 风控状态
    is_flooding: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否触发 FloodWait")
    flood_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="FloodWait 解除时间")

    # 负载均衡
    weight: Mapped[int] = mapped_column(Integer, default=100, comment="权重（用于账号选择）")

    # 统计
    messages_sent: Mapped[int] = mapped_column(Integer, default=0, comment="已发送消息数")
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最后使用时间")

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关系
    proxy: Mapped[Optional["Proxy"]] = relationship(
        "Proxy",
        foreign_keys=[proxy_id]
    )
    resources: Mapped[List["Resource"]] = relationship("Resource", back_populates="account", cascade="all, delete-orphan")
    tasks: Mapped[List["ScheduledMessageTask"]] = relationship("ScheduledMessageTask", foreign_keys=[ScheduledMessageTask.account_id])

    # 索引
    __table_args__ = (
        Index("idx_accounts_user_id", "user_id"),
        Index("idx_accounts_health_status", "health_status"),
        Index("idx_accounts_bind_code", "bind_code"),
    )

    def __repr__(self) -> str:
        return f"<Account(id={self.account_id}, username={self.username}, health={self.health_status})>"


class Resource(Base):
    """Dialogs 资源表"""
    __tablename__ = "resources"

    # 主键
    resource_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 归属
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.account_id", ondelete="CASCADE"), nullable=False, comment="归属账号 ID")

    # Peer 信息
    peer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="群组/频道/用户 ID")
    peer_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="Peer 类型: user/chat/supergroup/channel")
    access_hash: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, comment="构造 InputPeer 必需")

    # 元数据
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="名称")
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="@username")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="描述（频道/超级群）")

    # 分类标记
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已静音")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已归档")
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否认证")
    is_scam: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否诈骗")

    # 成员数（群组/频道）
    participants_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="成员数")

    # 同步状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否活跃（未被删除/封禁）")
    last_sync_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="最后同步时间")

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关系
    account: Mapped["Account"] = relationship("Account", back_populates="resources")

    # 索引和约束
    __table_args__ = (
        UniqueConstraint("account_id", "peer_id", name="unique_account_peer"),
        Index("idx_resources_account_id", "account_id"),
        Index("idx_resources_peer_type", "peer_type"),
        Index("idx_resources_username", "username"),
        Index("idx_resources_is_active", "account_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Resource(id={self.resource_id}, type={self.peer_type}, title={self.title})>"


class AccountBindLog(Base):
    """账号绑定日志表"""
    __tablename__ = "account_bind_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.account_id"), nullable=True, comment="账号 ID")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="绑定用户 ID")
    bind_code: Mapped[Optional[str]] = mapped_column(String(6), nullable=True, comment="绑定码")
    bound_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="绑定时间")
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True, comment="IP 地址")

    # 索引
    __table_args__ = (
        Index("idx_bind_logs_user_id", "user_id"),
        Index("idx_bind_logs_bound_at", "bound_at"),
    )

    def __repr__(self) -> str:
        return f"<AccountBindLog(id={self.id}, user_id={self.user_id}, code={self.bind_code})>"