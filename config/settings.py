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

    # 应用配置
    log_level: str = Field(default="INFO", alias="LOG_LEVEL", description="日志级别")
    timezone: str = Field(default="Asia/Shanghai", alias="TIMEZONE", description="时区")

    # 调度配置
    worker_interval: int = Field(default=60, alias="WORKER_INTERVAL", description="Worker 扫描间隔（秒）")
    max_failure_count: int = Field(default=5, alias="MAX_FAILURE_COUNT", description="最大失败次数")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore"
    )


# 全局配置实例
settings = Settings()
