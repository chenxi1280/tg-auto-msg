"""
应用配置
"""
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """应用配置类"""

    # Telegram 配置
    api_id: int = Field(alias="TG_API_ID", description="Telegram API ID")
    api_hash: str = Field(alias="TG_API_HASH", description="Telegram API Hash")
    bot_token: str = Field(alias="BOT_TOKEN", description="Bot Token")
    userbot_phone: Optional[str] = Field(None, alias="USERBOT_PHONE", description="Userbot 手机号")

    # 数据库配置
    database_url: str = Field(alias="DATABASE_URL", description="PostgreSQL 连接 URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL", description="Redis 连接 URL")

    # 安全配置
    encryption_key: Optional[str] = Field(None, alias="ENCRYPTION_KEY", description="数据加密密钥（Base64 编码）")
    jwt_secret_key: str = Field(default="your-secret-key-change-in-production", alias="JWT_SECRET_KEY", description="JWT 签名密钥")
    admin_api_token: str = Field(default="", alias="ADMIN_API_TOKEN", description="管理员后台 API 令牌")

    @property
    def secret_key(self) -> str:
        """获取 JWT 签名密钥"""
        return self.jwt_secret_key

    # 应用配置
    log_level: str = Field(default="INFO", alias="LOG_LEVEL", description="日志级别")
    timezone: str = Field(default="Asia/Shanghai", alias="TIMEZONE", description="时区")
    h5_base_url: str = Field(
        default="http://localhost:8000",
        alias="H5_BASE_URL",
        description="H5 控制台基础 URL"
    )

    # 调度配置
    worker_interval: int = Field(default=60, alias="WORKER_INTERVAL", description="Worker 扫描间隔（秒）")
    max_failure_count: int = Field(default=5, alias="MAX_FAILURE_COUNT", description="最大失败次数")
    scheduler_mode: str = Field(
        default="all",
        alias="SCHEDULER_MODE",
        description="调度模式: all/producer/consumer"
    )

    # 绑定安全配置
    bind_max_failures: int = Field(
        default=8,
        alias="BIND_MAX_FAILURES",
        description="/bind 最大连续失败次数"
    )
    bind_failure_window_seconds: int = Field(
        default=600,
        alias="BIND_FAILURE_WINDOW_SECONDS",
        description="/bind 失败计数窗口（秒）"
    )
    bind_lock_seconds: int = Field(
        default=900,
        alias="BIND_LOCK_SECONDS",
        description="/bind 触发限流后的锁定时长（秒）"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore"
    )


# 全局配置实例
settings = Settings()
