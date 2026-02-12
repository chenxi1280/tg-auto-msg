"""Application lifespan management for H5 backend."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from backend.bot.client_runtime.manager import (
    bot_client,
    init_userbot,
    start_manager_bot,
    userbot_client,
)
from backend.config.core.settings import settings
from backend.database.runtime.session import init_database
from backend.scheduler.core.worker import scheduler

# Register Bot command/callback handlers (import side effect)
import backend.bot.handlers.core.main  # noqa: F401


async def _run_manager_bot_forever() -> None:
    """Keep manager bot connected and auto-reconnect on disconnect."""
    while True:
        try:
            await bot_client.run_until_disconnected()
            logger.warning("Manager Bot 连接已断开，3 秒后尝试重连")
        except asyncio.CancelledError:
            logger.info("Manager Bot 监听任务已取消")
            raise
        except Exception as e:
            logger.exception(f"Manager Bot 运行异常: {type(e).__name__}: {e!r}")

        await asyncio.sleep(3)
        try:
            bot_me = await start_manager_bot(settings.bot_token)
            await bot_client.set_receive_updates(True)
            logger.info(f"Manager Bot 重连成功: @{bot_me.username} (id={bot_me.id})")
        except Exception as e:
            logger.warning(f"Manager Bot 重连失败，将继续重试: {e}")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """FastAPI lifespan context."""
    logger.info("🚀 启动 Telegram 定时消息推送管理系统")

    logger.info("初始化数据库...")
    await init_database()
    logger.info("✅ 数据库初始化完成")

    logger.info("初始化 Userbot...")
    userbot_logged_in = await init_userbot()
    if not userbot_logged_in:
        logger.warning("⚠️ Userbot 未登录，请通过 H5 页面扫码登录")
    logger.info("✅ Userbot 初始化完成")

    logger.info("初始化调度器...")
    await scheduler.init()
    logger.info("✅ 调度器初始化完成")

    asyncio.create_task(scheduler.start())
    logger.info("✅ 任务调度器已启动")

    logger.info("🤖 启动 Bot...")
    expected_bot_id = str(settings.bot_token).split(":", 1)[0] if settings.bot_token else "unknown"
    logger.info(f"BOT_TOKEN 对应的 bot_id: {expected_bot_id}")

    try:
        bot_me = await start_manager_bot(settings.bot_token)
        await bot_client.set_receive_updates(True)
        logger.info(f"✅ Manager Bot 在线: @{bot_me.username} (id={bot_me.id})")
    except Exception as e:
        logger.warning(f"读取 Bot 身份信息失败: {e}")

    bot_task = asyncio.create_task(_run_manager_bot_forever())
    logger.info("✅ Bot 已启动")
    logger.info("📱 H5 登录页面: http://localhost:8000/login")

    yield

    logger.info("清理资源...")
    await scheduler.stop()
    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass

    await bot_client.disconnect()
    await userbot_client.disconnect()
    logger.info("👋 程序已退出")
