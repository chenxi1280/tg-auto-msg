"""
H5 控制台 FastAPI 服务
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends, Query, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from datetime import datetime
from typing import Optional, List
import hashlib
import hmac
import random
import string
from loguru import logger

from config.settings import settings
from database.session import init_database, get_async_session
from database.models import (
    ScheduledMessageTask, MediaType, TaskLog,
    Account, Resource, Proxy, HealthStatus
)
from sqlalchemy import select, delete
from bot.redis_login_manager import get_redis_login_manager, LoginStatus
from bot.account_manager import get_account_manager
from bot.resource_manager import get_resource_manager
from bot.proxy_pool import get_proxy_pool
from bot.client import bot_client, userbot_client, init_userbot, start_qr_login, is_userbot_ready, _wait_for_qr_login
from scheduler.worker import scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("🚀 启动 Telegram 定时消息推送管理系统")

    # 初始化数据库
    logger.info("初始化数据库...")
    await init_database()
    logger.info("✅ 数据库初始化完成")

    # 初始化 Userbot
    logger.info("初始化 Userbot...")
    userbot_logged_in = await init_userbot()
    if not userbot_logged_in:
        logger.warning("⚠️ Userbot 未登录，请通过 H5 页面扫码登录")
    logger.info("✅ Userbot 初始化完成")

    # 初始化调度器
    logger.info("初始化调度器...")
    await scheduler.init()
    logger.info("✅ 调度器初始化完成")

    # 启动调度器
    scheduler_task = asyncio.create_task(scheduler.start())
    logger.info("✅ 任务调度器已启动")

    # 启动 Bot
    logger.info("🤖 启动 Bot...")
    await bot_client.start(bot_token=settings.bot_token)
    bot_task = asyncio.create_task(bot_client.run_until_disconnected())
    logger.info("✅ Bot 已启动")
    logger.info("📱 H5 登录页面: http://localhost:8000/login")

    yield

    # 关闭时执行
    logger.info("清理资源...")
    await scheduler.stop()
    await bot_client.disconnect()
    await userbot_client.disconnect()
    logger.info("👋 程序已退出")


# 创建 FastAPI 应用（带生命周期管理）
app = FastAPI(
    title="Telegram 定时消息推送管理 API",
    lifespan=lifespan
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="h5/static"), name="static")

# 模板引擎
templates = Jinja2Templates(directory="h5/templates")

# ============ 辅助函数 ============

def verify_signature(user_id: int, task_id: str, timestamp: int, sign: str) -> bool:
    """验证签名"""
    params = f"user_id={user_id}&task_id={task_id}&timestamp={timestamp}"
    secret = "your-secret-key"  # 应从配置中读取

    expected_sign = hmac.new(
        secret.encode(),
        params.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(sign, expected_sign)


# ============ 页面路由（旧的模板页面，保留任务相关页面用于向后兼容）============

@app.get("/task/{task_id}", response_class=HTMLResponse)
async def task_detail(
    request: Request,
    task_id: str,
    user_id: int = Query(...),
    timestamp: int = Query(...),
    sign: str = Query(...)
):
    """任务详情页"""
    # 验证签名
    if not verify_signature(user_id, task_id, timestamp, sign):
        raise HTTPException(status_code=403, detail="签名验证失败")

    # 验证时间戳（5分钟内有效）
    now = int(datetime.now().timestamp())
    if abs(now - timestamp) > 300:
        raise HTTPException(status_code=403, detail="链接已过期")

    async with get_async_session() as session:
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

    return templates.TemplateResponse(
        "task_detail.html",
        {
            "request": request,
            "task": task,
            "user_id": user_id,
            "task_id": task_id,
            "timestamp": timestamp,
            "sign": sign
        }
    )


# ============ API 接口 ============

@app.get("/api/tasks")
async def get_tasks(user_id: Optional[int] = None):
    """获取任务列表"""
    async with get_async_session() as session:
        query = select(ScheduledMessageTask)
        if user_id:
            query = query.where(ScheduledMessageTask.user_id == user_id)
        query = query.order_by(ScheduledMessageTask.created_at.desc())

        result = await session.execute(query)
        tasks = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "task_id": t.task_id,
                    "title": t.title,
                    "enabled": t.enabled,
                    "repeat_interval_min": t.repeat_interval_min,
                    "day_start_hour": t.day_start_hour,
                    "day_end_hour": t.day_end_hour,
                    "start_at": t.start_at,
                    "end_at": t.end_at,
                    "media_type": t.media_type.value,
                    "delete_previous": t.delete_previous,
                    "pin_message": t.pin_message,
                    "next_run_at": t.next_run_at,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tasks
            ]
        }


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """获取单个任务详情"""
    async with get_async_session() as session:
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        return {
            "success": True,
            "data": {
                "task_id": task.task_id,
                "user_id": task.user_id,
                "chat_id": task.chat_id,
                "title": task.title,
                "enabled": task.enabled,
                "repeat_interval_min": task.repeat_interval_min,
                "day_start_hour": task.day_start_hour,
                "day_end_hour": task.day_end_hour,
                "start_at": task.start_at,
                "end_at": task.end_at,
                "text": task.text,
                "media_type": task.media_type.value,
                "media_file_id": task.media_file_id,
                "buttons": task.buttons,
                "delete_previous": task.delete_previous,
                "pin_message": task.pin_message,
                "last_sent_message_id": task.last_sent_message_id,
                "next_run_at": task.next_run_at,
                "failure_count": task.failure_count,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }
        }


@app.post("/api/tasks")
async def create_task(task_data: dict):
    """创建任务"""
    async with get_async_session() as session:
        task = ScheduledMessageTask(**task_data)
        session.add(task)
        await session.commit()
        await session.refresh(task)

        return {
            "success": True,
            "data": {"task_id": task.task_id}
        }


@app.put("/api/tasks/{task_id}")
async def update_task(task_id: str, task_data: dict):
    """更新任务"""
    async with get_async_session() as session:
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        # 更新字段
        for key, value in task_data.items():
            if hasattr(task, key) and value is not None:
                setattr(task, key, value)

        await session.commit()
        await session.refresh(task)

        return {"success": True}


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除任务"""
    async with get_async_session() as session:
        await session.execute(
            delete(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        await session.commit()

        return {"success": True}


@app.get("/api/tasks/{task_id}/logs")
async def get_task_logs(task_id: str, limit: int = 50):
    """获取任务日志"""
    async with get_async_session() as session:
        result = await session.execute(
            select(TaskLog)
            .where(TaskLog.task_id == task_id)
            .order_by(TaskLog.send_at.desc())
            .limit(limit)
        )
        logs = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": log.id,
                    "send_at": log.send_at.isoformat() if log.send_at else None,
                    "result": log.result,
                    "error_code": log.error_code,
                    "error_message": log.error_message,
                    "message_id": log.message_id,
                }
                for log in logs
            ]
        }


@app.post("/api/tasks/batch")
async def batch_update_tasks(task_ids: List[str], update_data: dict):
    """批量更新任务"""
    async with get_async_session() as session:
        for task_id in task_ids:
            result = await session.execute(
                select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
            )
            task = result.scalar_one_or_none()

            if task:
                for key, value in update_data.items():
                    if hasattr(task, key):
                        setattr(task, key, value)

        await session.commit()

        return {"success": True, "count": len(task_ids)}


# ============ 登录相关接口 ============

def generate_login_id() -> str:
    """生成随机登录 ID"""
    chars = string.ascii_letters + string.digits
    return 'login_' + ''.join(random.choices(chars, k=16))


@app.post("/api/login/create")
async def create_login_session(background_tasks: BackgroundTasks):
    """
    创建新的登录会话（使用 Redis 存储状态）

    返回登录会话 ID 和 qr_url，前端直接使用 qr_url 生成二维码
    """
    login_manager = get_redis_login_manager()

    # 创建登录会话
    login_id = generate_login_id()
    session = await login_manager.create_session(login_id)

    # 【关键修改】直接在这里创建 QR 登录并获取 URL
    qr_login = await userbot_client.qr_login()
    qr_url = qr_login.url

    # 保存到 Redis
    await login_manager.update_qr_url(login_id, qr_url)
    await login_manager.update_status(login_id, LoginStatus.PENDING)

    # 后台任务：等待扫码（使用 _wait_for_qr_login 而不是 start_qr_login）
    background_tasks.add_task(_wait_for_qr_login, login_id, qr_login)

    return {
        "success": True,
        "data": {
            "login_id": login_id,
            "qr_url": qr_url,
            "expires_at": session.expires_at
        }
    }


@app.get("/api/login/status")
async def get_login_status(login_id: str):
    """
    获取登录状态（从 Redis 查询）

    Args:
        login_id: 登录会话 ID

    Returns:
        登录状态信息，包含绑定码（如果已确认）
    """
    login_manager = get_redis_login_manager()
    session = await login_manager.get_session(login_id)

    if not session:
        return {
            "success": False,
            "status": "error",
            "error": "会话不存在"
        }

    response_data = {
        "status": session.status.value,
        "error": session.error,
        "qr_url": session.qr_url
    }

    # 如果已确认登录，返回绑定码和用户信息
    if session.status == LoginStatus.CONFIRMED:
        response_data.update({
            "bind_code": session.bind_code,
            "tg_user_id": session.tg_user_id,
            "username": session.username
        })

    return {
        "success": True,
        "data": response_data
    }


@app.get("/api/login/check")
async def check_login_status():
    """
    检查 Userbot 登录状态

    返回当前 Userbot 是否已登录
    """
    is_ready = is_userbot_ready()

    return {
        "success": True,
        "data": {
            "is_logged_in": is_ready
        }
    }


# ============ 账号管理接口 ============

@app.get("/api/accounts/")
async def get_accounts(user_id: int):
    """
    获取用户的所有账号

    Args:
        user_id: 用户 Telegram ID

    Returns:
        账号列表
    """
    account_manager = get_account_manager()
    accounts = await account_manager.get_accounts(user_id)

    return {
        "success": True,
        "data": [
            {
                "account_id": acc.account_id,
                "username": acc.username,
                "first_name": acc.first_name,
                "phone": acc.phone,
                "is_active": acc.is_active,
                "is_banned": acc.is_banned,
                "health_status": acc.health_status,
                "is_flooding": acc.is_flooding,
                "flood_until": acc.flood_until.isoformat() if acc.flood_until else None,
                "messages_sent": acc.messages_sent,
                "last_used_at": acc.last_used_at.isoformat() if acc.last_used_at else None,
                "created_at": acc.created_at.isoformat() if acc.created_at else None,
            }
            for acc in accounts
        ]
    }


@app.post("/api/accounts/{account_id}/sync")
async def sync_account_resources(account_id: str, background_tasks: BackgroundTasks):
    """
    同步账号的 Telegram 资源（Dialogs）

    Args:
        account_id: 账号 ID

    Returns:
        同步结果
    """
    resource_manager = get_resource_manager()

    # 在后台执行同步
    async def run_sync():
        try:
            result = await resource_manager.full_sync(account_id)
            return result
        except Exception as e:
            from loguru import logger
            logger.error(f"资源同步失败: {e}")
            return None

    # 启动后台任务
    import asyncio
    background_tasks.add_task(lambda: asyncio.create_task(run_sync()))

    return {
        "success": True,
        "message": "资源同步已启动，请稍后查看结果"
    }


@app.get("/api/accounts/{account_id}/resources")
async def get_account_resources(
    account_id: str,
    peer_type: Optional[str] = None,
    is_active: bool = True,
    search: Optional[str] = None
):
    """
    获取账号的资源列表

    Args:
        account_id: 账号 ID
        peer_type: 筛选类型（user/chat/supergroup/channel）
        is_active: 是否只返回活跃资源
        search: 搜索关键词（标题/用户名）

    Returns:
        资源列表
    """
    resource_manager = get_resource_manager()

    if search:
        # 搜索模式
        resources = await resource_manager.search_resources(account_id, search)
    else:
        # 普通列表模式
        resources = await resource_manager.get_resources(
            account_id,
            peer_type=peer_type,
            is_active=is_active
        )

    return {
        "success": True,
        "data": [
            {
                "resource_id": r.resource_id,
                "peer_id": r.peer_id,
                "peer_type": r.peer_type,
                "access_hash": r.access_hash,
                "title": r.title,
                "username": r.username,
                "description": r.description,
                "is_muted": r.is_muted,
                "is_verified": r.is_verified,
                "participants_count": r.participants_count,
                "is_active": r.is_active,
                "last_sync_at": r.last_sync_at.isoformat() if r.last_sync_at else None,
            }
            for r in resources
        ]
    }


@app.post("/api/accounts/{account_id}/disable")
async def disable_account(account_id: str):
    """
    禁用账号

    Args:
        account_id: 账号 ID

    Returns:
        操作结果
    """
    account_manager = get_account_manager()
    await account_manager.update_account(account_id, is_active=False)

    return {"success": True, "message": "账号已禁用"}


@app.post("/api/accounts/{account_id}/enable")
async def enable_account(account_id: str):
    """
    启用账号

    Args:
        account_id: 账号 ID

    Returns:
        操作结果
    """
    account_manager = get_account_manager()
    await account_manager.update_account(account_id, is_active=True)

    return {"success": True, "message": "账号已启用"}


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str):
    """
    删除账号

    Args:
        account_id: 账号 ID

    Returns:
        操作结果
    """
    account_manager = get_account_manager()
    await account_manager.delete_account(account_id)

    return {"success": True, "message": "账号已删除"}


# ============ 代理管理接口 ============

@app.get("/api/proxies/")
async def get_proxies():
    """
    获取所有代理

    Returns:
        代理列表
    """
    async with get_async_session() as session:
        result = await session.execute(
            select(Proxy).order_by(Proxy.created_at.desc())
        )
        proxies = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "proxy_id": p.proxy_id,
                    "proxy_type": p.proxy_type,
                    "host": p.host,
                    "port": p.port,
                    "username": p.username,
                    "is_active": p.is_active,
                    "is_healthy": p.is_healthy,
                    "response_time_ms": p.response_time_ms,
                    "usage_count": p.usage_count,
                    "assigned_account_id": p.assigned_account_id,
                    "last_check_at": p.last_check_at.isoformat() if p.last_check_at else None,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                }
                for p in proxies
            ]
        }


@app.post("/api/proxies/")
async def add_proxy(proxy_data: dict):
    """
    添加新代理

    Body:
        proxy_type: 代理类型（socks5/http）
        host: 主机地址
        port: 端口
        username: 用户名（可选）
        password: 密码（可选）

    Returns:
        创建的代理信息
    """
    proxy_pool = get_proxy_pool()

    proxy = await proxy_pool.add_proxy(
        proxy_type=proxy_data.get("proxy_type", "socks5"),
        host=proxy_data["host"],
        port=proxy_data["port"],
        username=proxy_data.get("username"),
        password=proxy_data.get("password")
    )

    return {
        "success": True,
        "data": {
            "proxy_id": proxy.proxy_id,
            "proxy_type": proxy.proxy_type,
            "host": proxy.host,
            "port": proxy.port
        }
    }


@app.post("/api/proxies/{proxy_id}/check")
async def check_proxy_health(proxy_id: int):
    """
    检查代理健康状态

    Args:
        proxy_id: 代理 ID

    Returns:
        健康检查结果
    """
    proxy_pool = get_proxy_pool()
    is_healthy, response_time = await proxy_pool.check_health(proxy_id)

    return {
        "success": True,
        "data": {
            "is_healthy": is_healthy,
            "response_time_ms": response_time
        }
    }


@app.delete("/api/proxies/{proxy_id}")
async def delete_proxy(proxy_id: int):
    """
    删除代理

    Args:
        proxy_id: 代理 ID

    Returns:
        操作结果
    """
    proxy_pool = get_proxy_pool()
    await proxy_pool.delete_proxy(proxy_id)

    return {"success": True, "message": "代理已删除"}


@app.post("/api/proxies/{proxy_id}/assign")
async def assign_proxy(proxy_id: int, account_id: str):
    """
    将代理分配给账号

    Args:
        proxy_id: 代理 ID
        account_id: 账号 ID

    Returns:
        操作结果
    """
    proxy_pool = get_proxy_pool()
    await proxy_pool.assign_proxy(account_id, proxy_id)

    return {"success": True, "message": "代理已分配"}


@app.post("/api/proxies/{proxy_id}/unassign")
async def unassign_proxy(proxy_id: int):
    """
    解绑代理

    Args:
        proxy_id: 代理 ID

    Returns:
        操作结果
    """
    proxy_pool = get_proxy_pool()
    await proxy_pool.unassign_proxy(proxy_id)

    return {"success": True, "message": "代理已解绑"}


# ============ 前端静态文件服务 ============

# 尝试挂载 Vue 前端构建产物
import os
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "h5-frontend", "dist")

if os.path.exists(frontend_dist):
    # 挂载前端静态资源目录
    static_dist = os.path.join(frontend_dist, "assets")
    if os.path.exists(static_dist):
        app.mount("/assets", StaticFiles(directory=static_dist), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def serve_frontend_root():
        """服务前端首页"""
        return FileResponse(os.path.join(frontend_dist, "index.html"))

    # 新 Vue SPA 页面路由
    @app.get("/login", include_in_schema=False)
    async def serve_login():
        """服务登录页"""
        return FileResponse(os.path.join(frontend_dist, "index.html"))

    @app.get("/accounts", include_in_schema=False)
    async def serve_accounts():
        """服务账号管理页"""
        return FileResponse(os.path.join(frontend_dist, "index.html"))

    @app.get("/resources", include_in_schema=False)
    async def serve_resources():
        """服务资源列表页"""
        return FileResponse(os.path.join(frontend_dist, "index.html"))

    @app.get("/proxies", include_in_schema=False)
    async def serve_proxies():
        """服务代理管理页"""
        return FileResponse(os.path.join(frontend_dist, "index.html"))

    @app.get("/tasks", include_in_schema=False)
    async def serve_tasks():
        """服务任务管理页"""
        return FileResponse(os.path.join(frontend_dist, "index.html"))

    print(f"✓ 前端静态文件已挂载: {frontend_dist}")
else:
    print(f"⚠ 前端构建产物不存在: {frontend_dist}")
    print(f"  提示: 运行 'cd h5-frontend && npm run build' 构建前端")
