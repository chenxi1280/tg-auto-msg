"""H5 控制台 FastAPI 应用装配。"""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from backend.bot.client import (
    bot_client,
    init_userbot,
    start_manager_bot,
    userbot_client,
)
from backend.config.settings import settings
from backend.database.session import init_database
from backend.scheduler.worker import scheduler
from backend.h5_backend.routers.auth import router as auth_router
from backend.h5_backend.routers.login import router as login_router
from backend.h5_backend.routers.accounts import router as accounts_router
from backend.h5_backend.routers.tasks import router as tasks_router
from backend.h5_backend.routers.proxies import router as proxies_router

# 注册 Bot 命令与回调处理器（导入即完成 handler 绑定）
import backend.bot.handlers.main  # noqa: F401

PROJECT_ROOT = Path(__file__).resolve().parents[2]


async def _run_manager_bot_forever():
    """持续维持 Manager Bot 连接，连接中断时自动重连。"""
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
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
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


app = FastAPI(title="Telegram 定时消息推送管理 API", lifespan=lifespan)

# API routers
app.include_router(auth_router)
app.include_router(login_router)
app.include_router(accounts_router)
app.include_router(tasks_router)
app.include_router(proxies_router)


# 统一 H5 前端：使用 Vue SPA 作为管理端唯一入口
frontend_dist = os.path.join(PROJECT_ROOT, "frontend", "h5", "dist")
frontend_index_file = os.path.join(frontend_dist, "index.html")

if os.path.exists(frontend_index_file):
    static_dist = os.path.join(frontend_dist, "assets")
    if os.path.exists(static_dist):
        app.mount("/assets", StaticFiles(directory=static_dist), name="frontend-assets")

    def serve_frontend_index() -> FileResponse:
        return FileResponse(frontend_index_file)

    @app.get("/", include_in_schema=False)
    async def serve_frontend_root():
        return serve_frontend_index()

    @app.get("/login", include_in_schema=False)
    @app.get("/register", include_in_schema=False)
    @app.get("/bind-tg", include_in_schema=False)
    @app.get("/accounts", include_in_schema=False)
    @app.get("/resources", include_in_schema=False)
    @app.get("/proxies", include_in_schema=False)
    @app.get("/tasks", include_in_schema=False)
    async def serve_frontend_routes():
        return serve_frontend_index()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend_spa_fallback(full_path: str):
        excluded_prefixes = ("api", "assets", "static", "docs", "redoc", "openapi.json")
        for prefix in excluded_prefixes:
            if full_path == prefix or full_path.startswith(f"{prefix}/"):
                raise HTTPException(status_code=404, detail="Not Found")
        return serve_frontend_index()

    print(f"✓ 前端静态文件已挂载: {frontend_dist}")
else:
    print(f"⚠ 前端构建产物不存在: {frontend_dist}")
    print("  提示: 运行 'cd frontend/h5 && npm run build' 构建前端")
