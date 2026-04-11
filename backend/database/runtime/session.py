"""数据库会话与 Schema 初始化管理。"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from loguru import logger
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config.core.settings import settings
from backend.database.runtime.migration_manager import (
    apply_pending_migrations,
    list_migration_history,
    rollback_migrations,
)
from backend.database.schema.models import Base


def _build_connect_args() -> dict:
    """
    构建 asyncpg 连接参数。
    未显式配置 ssl/sslmode 时，默认禁用 SSL 协商，避免部分内网 PG 实例握手异常。
    """
    connect_args = {"timeout": 30, "command_timeout": 30}
    try:
        url = make_url(settings.database_url)
        query_keys = {str(k).lower() for k in url.query.keys()}
        if "ssl" not in query_keys and "sslmode" not in query_keys:
            connect_args["ssl"] = False
    except Exception:
        pass
    return connect_args


engine = create_async_engine(
    settings.database_url,
    echo=settings.log_level == "DEBUG",
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600,
    connect_args=_build_connect_args(),
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

_schema_ready = False
_schema_lock: Optional[asyncio.Lock] = None

REQUIRED_TASK_COLUMNS = {
    "account_id",
    "target_peer_id",
    "target_peer_type",
    "target_access_hash",
    "target_peers",
    "trigger_mode",
    "shortcut_slot",
    "shortcut_label",
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


async def _validate_required_columns() -> None:
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'scheduled_message_tasks'
                """
            )
        )
        existing_columns = {row[0] for row in result}
        missing_columns = sorted(REQUIRED_TASK_COLUMNS - existing_columns)
        if missing_columns:
            raise RuntimeError(
                "scheduled_message_tasks 缺少关键列: " + ", ".join(missing_columns)
            )


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

        migration_result = await apply_pending_migrations(engine)
        if migration_result.get("applied", 0) > 0:
            logger.info(
                "SQL 迁移执行完成: total={}, applied={}, skipped={}",
                migration_result.get("total", 0),
                migration_result.get("applied", 0),
                migration_result.get("skipped", 0),
            )

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        await _validate_required_columns()
        _schema_ready = True


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """获取异步数据库会话。"""
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
    """初始化数据库（带重试）。"""
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
    """删除所有表（谨慎使用）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def get_migration_history(limit: int = 200):
    """查询迁移执行历史。"""
    return await list_migration_history(engine, limit=limit)


async def rollback_database_migrations(
    *,
    version: Optional[str] = None,
    steps: int = 1,
    dry_run: bool = False,
):
    """执行迁移回滚。"""
    return await rollback_migrations(
        engine,
        version=version,
        steps=steps,
        dry_run=dry_run,
    )
