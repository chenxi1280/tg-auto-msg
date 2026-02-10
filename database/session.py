"""
数据库会话管理
"""
import asyncio
from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager
from loguru import logger
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from config.settings import settings
from database.models import Base


def _build_connect_args() -> dict:
    """
    构建 asyncpg 连接参数。
    未显式配置 ssl/sslmode 时，默认禁用 SSL 协商，避免部分内网 PG 实例握手异常。
    """
    connect_args = {
        "timeout": 30,
        "command_timeout": 30,
    }
    try:
        url = make_url(settings.database_url)
        query_keys = {str(k).lower() for k in url.query.keys()}
        if "ssl" not in query_keys and "sslmode" not in query_keys:
            connect_args["ssl"] = False
    except Exception:
        # URL 解析失败时保持默认参数，交由 SQLAlchemy 抛出原始错误
        pass
    return connect_args


# 创建异步引擎（优化连接池配置以提高稳定性）
engine = create_async_engine(
    settings.database_url,
    echo=settings.log_level == "DEBUG",
    pool_pre_ping=True,          # 连接前检查可用性
    pool_size=5,                 # 减少池大小以提高稳定性
    max_overflow=10,             # 减少溢出连接数
    pool_recycle=3600,           # 1小时回收连接，防止长时间连接被服务器关闭
    connect_args=_build_connect_args(),
)

# 创建异步会话工厂
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# 进程内 schema 就绪状态（避免每次请求都跑迁移）
_schema_ready = False
_schema_lock: Optional[asyncio.Lock] = None

MIGRATION_SQL = [
    # accounts 绑定码字段（兼容旧库）
    """
    ALTER TABLE IF EXISTS accounts
    ADD COLUMN IF NOT EXISTS bind_code VARCHAR(6)
    """,
    """
    ALTER TABLE IF EXISTS accounts
    ADD COLUMN IF NOT EXISTS bind_code_expires_at TIMESTAMP
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_accounts_bind_code
    ON accounts(bind_code)
    """,

    # scheduled_message_tasks 新架构字段
    """
    ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS account_id VARCHAR(36)
    """,
    """
    ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS target_peer_id BIGINT
    """,
    """
    ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS target_peer_type VARCHAR(20)
    """,
    """
    ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS target_access_hash BIGINT
    """,
    """
    ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS priority INTEGER DEFAULT 0
    """,
    """
    ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS delay_min_seconds INTEGER DEFAULT 0
    """,
    """
    ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS delay_max_seconds INTEGER DEFAULT 0
    """,
    """
    ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS jitter_seconds INTEGER DEFAULT 0
    """,
    """
    ALTER TABLE IF EXISTS scheduled_message_tasks
    ADD COLUMN IF NOT EXISTS next_run_at BIGINT
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_account_id
    ON scheduled_message_tasks(account_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_enabled_next_run
    ON scheduled_message_tasks(enabled, next_run_at)
    """,
]

REQUIRED_TASK_COLUMNS = {
    "account_id",
    "target_peer_id",
    "target_peer_type",
    "target_access_hash",
    "priority",
    "delay_min_seconds",
    "delay_max_seconds",
    "jitter_seconds",
    "next_run_at",
}


def _get_schema_lock() -> asyncio.Lock:
    global _schema_lock
    if _schema_lock is None:
        _schema_lock = asyncio.Lock()
    return _schema_lock


async def ensure_database_schema(force: bool = False) -> None:
    """
    确保数据库 schema 与当前模型兼容。

    - 启动时调用（init_database）
    - 请求/调度首次使用会话时兜底调用（get_async_session）
    """
    global _schema_ready

    if _schema_ready and not force:
        return

    async with _get_schema_lock():
        if _schema_ready and not force:
            return

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

            for stmt in MIGRATION_SQL:
                await conn.execute(text(stmt))

            # 迁移后做一次关键列校验，避免运行时才触发 UndefinedColumnError
            result = await conn.execute(text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'scheduled_message_tasks'
                """
            ))
            existing_columns = {row[0] for row in result}
            missing_columns = sorted(REQUIRED_TASK_COLUMNS - existing_columns)
            if missing_columns:
                raise RuntimeError(
                    "scheduled_message_tasks 缺少关键列: "
                    + ", ".join(missing_columns)
                )

        _schema_ready = True


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    获取异步数据库会话

    Yields:
        AsyncSession: 数据库会话
    """
    # 兜底：即使没有触发 FastAPI lifespan，也会在首次会话前自动补齐 schema
    await ensure_database_schema()

    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_database() -> None:
    """
    初始化数据库（创建表）
    """
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            await ensure_database_schema(force=True)
            return
        except Exception as e:
            if attempt >= max_retries:
                logger.error(f"数据库初始化失败（已重试 {max_retries} 次）: {e}")
                raise
            delay = attempt * 2
            logger.warning(
                f"数据库初始化失败（第 {attempt}/{max_retries} 次）: {e}，{delay}s 后重试"
            )
            await asyncio.sleep(delay)


async def drop_database() -> None:
    """
    删除所有表（谨慎使用！）
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
