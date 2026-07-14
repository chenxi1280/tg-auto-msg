"""
应用配置
"""
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator

_VALID_SCHEDULER_MODES = {"all", "producer", "consumer"}
_DEFAULT_JWT_SECRET = "your-secret-key-change-in-production"
DEFAULT_SCHEDULER_TASK_TIMEOUT_SECONDS = 360


class Settings(BaseSettings):
    """应用配置类"""

    # Telegram 配置
    api_id: int = Field(alias="TG_API_ID", description="Telegram API ID")
    api_hash: str = Field(alias="TG_API_HASH", description="Telegram API Hash")
    bot_token: str = Field(alias="BOT_TOKEN", description="Bot Token")
    bot_username: Optional[str] = Field(
        None,
        alias="BOT_USERNAME",
        description="Manager Bot 用户名（不带 @），用于生成 deep link",
    )
    userbot_phone: Optional[str] = Field(None, alias="USERBOT_PHONE", description="Userbot 手机号")

    # 数据库配置
    database_url: str = Field(alias="DATABASE_URL", description="PostgreSQL 连接 URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL", description="Redis 连接 URL")

    # 安全配置
    encryption_key: Optional[str] = Field(None, alias="ENCRYPTION_KEY", description="数据加密密钥（Base64 编码）")
    encryption_key_fallbacks: str = Field(
        default="",
        alias="ENCRYPTION_KEY_FALLBACKS",
        description="历史数据加密密钥回退列表，多个 Base64 32 字节密钥用英文逗号分隔",
    )
    jwt_secret_key: str = Field(default=_DEFAULT_JWT_SECRET, alias="JWT_SECRET_KEY", description="JWT 签名密钥")
    admin_api_token: str = Field(default="", alias="ADMIN_API_TOKEN", description="管理员后台 API 令牌")
    admin_bootstrap_username: str = Field(default="", alias="ADMIN_BOOTSTRAP_USERNAME", description="启动时自动初始化的超管账号")
    admin_bootstrap_password: str = Field(default="", alias="ADMIN_BOOTSTRAP_PASSWORD", description="启动时自动初始化的超管密码")
    admin_bootstrap_display_name: str = Field(default="超级管理员", alias="ADMIN_BOOTSTRAP_DISPLAY_NAME", description="启动时自动初始化的超管显示名")

    @property
    def secret_key(self) -> str:
        """获取 JWT 签名密钥"""
        return self.jwt_secret_key

    # 应用配置
    app_env: str = Field(default="development", alias="APP_ENV", description="运行环境: development/staging/production")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL", description="日志级别")
    timezone: str = Field(default="Asia/Shanghai", alias="TIMEZONE", description="时区")
    province_code: str = Field(default="default", alias="PROVINCE_CODE", description="当前部署省份编码")
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
    scheduler_task_timeout_seconds: int = Field(
        default=DEFAULT_SCHEDULER_TASK_TIMEOUT_SECONDS,
        alias="SCHEDULER_TASK_TIMEOUT_SECONDS",
        description="单个调度任务最大执行秒数，防止一个任务卡死整个调度器"
    )
    scheduler_task_concurrency: int = Field(
        default=3,
        alias="SCHEDULER_TASK_CONCURRENCY",
        description="调度器单轮最多并发执行的任务数，避免慢任务串行阻塞所有到点任务"
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
    login_session_ttl_seconds: int = Field(
        default=900,
        alias="LOGIN_SESSION_TTL_SECONDS",
        description="登录/绑定会话默认有效期（秒）"
    )
    bind_start_cooldown_seconds: int = Field(
        default=120,
        alias="BIND_START_COOLDOWN_SECONDS",
        description="单个系统用户发起 TG 绑定的冷却时间（秒）"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore"
    )

    @model_validator(mode="after")
    def _validate_settings(self):
        app_env = str(self.app_env or "").strip().lower()
        if app_env in {"prod", "production"} and self.jwt_secret_key == _DEFAULT_JWT_SECRET:
            raise ValueError(
                "JWT_SECRET_KEY 使用了默认值，生产环境必须设置自定义密钥。"
                "请在 .env 中配置 JWT_SECRET_KEY=<随机字符串>"
            )
        scheduler_mode = str(self.scheduler_mode or "").strip().lower()
        if scheduler_mode not in _VALID_SCHEDULER_MODES:
            raise ValueError(
                f"SCHEDULER_MODE 必须是 {_VALID_SCHEDULER_MODES} 之一，"
                f"当前值: '{self.scheduler_mode}'"
            )
        self.scheduler_mode = scheduler_mode
        if self.max_failure_count < 1:
            raise ValueError(
                f"MAX_FAILURE_COUNT 必须 >= 1，当前值: {self.max_failure_count}"
            )
        if self.scheduler_task_timeout_seconds < 1:
            raise ValueError(
                "SCHEDULER_TASK_TIMEOUT_SECONDS 必须 >= 1，"
                f"当前值: {self.scheduler_task_timeout_seconds}"
            )
        if self.scheduler_task_concurrency < 1:
            raise ValueError(
                "SCHEDULER_TASK_CONCURRENCY 必须 >= 1，"
                f"当前值: {self.scheduler_task_concurrency}"
            )
        return self


# 全局配置实例
settings = Settings()
