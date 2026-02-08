"""
数据库会话管理
"""
from typing import AsyncGenerator
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from config.settings import settings
from database.models import Base


# 创建异步引擎（优化连接池配置以提高稳定性）
engine = create_async_engine(
    settings.database_url,
    echo=settings.log_level == "DEBUG",
    pool_pre_ping=True,          # 连接前检查可用性
    pool_size=5,                 # 减少池大小以提高稳定性
    max_overflow=10,             # 减少溢出连接数
    pool_recycle=3600,           # 1小时回收连接，防止长时间连接被服务器关闭
    connect_args={
        "timeout": 30,           # 连接超时设置为 30 秒
        "command_timeout": 30,   # 命令执行超时
    },
)

# 创建异步会话工厂
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    获取异步数据库会话

    Yields:
        AsyncSession: 数据库会话
    """
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_database() -> None:
    """
    删除所有表（谨慎使用！）
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
