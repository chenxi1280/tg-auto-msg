"""
H5 控制台 FastAPI 服务
"""
import asyncio
import io
import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from datetime import datetime
from typing import Optional, List, Any, Dict
import random
import string
from loguru import logger
from telethon import TelegramClient
from telethon.sessions import StringSession

from backend.config.settings import settings
from backend.database.session import init_database, get_async_session
from backend.database.models import (
    ScheduledMessageTask, MediaType, TaskLog,
    Account, Resource, Proxy, HealthStatus, User
)
from sqlalchemy import select, delete, or_
from backend.bot.redis_login_manager import get_redis_login_manager, LoginStatus
from backend.bot.account_manager import get_account_manager
from backend.bot.resource_manager import get_resource_manager
from backend.bot.proxy_pool import get_proxy_pool
from backend.bot.client import (
    bot_client,
    userbot_client,
    init_userbot,
    is_userbot_ready,
    _wait_for_qr_login,
    start_manager_bot,
)

# 注册 Bot 命令与回调处理器（导入即完成 handler 绑定）
import backend.bot.handlers.main  # noqa: F401
from backend.scheduler.worker import scheduler
from backend.h5_backend.routers.auth import get_current_user


async def _run_manager_bot_forever():
    """
    持续维持 Manager Bot 连接，连接中断时自动重连。
    """
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

    # 关闭时执行
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


# 创建 FastAPI 应用（带生命周期管理）
app = FastAPI(
    title="Telegram 定时消息推送管理 API",
    lifespan=lifespan
)

# 注册认证路由
from backend.h5_backend.routers.auth import router as auth_router
app.include_router(auth_router)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_TASK_MEDIA_SIZE = 20 * 1024 * 1024  # 20MB
TELEGRAM_MEDIA_REF_PREFIX = "tgmsg://"


def _media_value(value: object) -> str:
    """兼容 Enum/字符串两种媒体类型表示，统一输出小写值。"""
    if isinstance(value, MediaType):
        return value.value
    return str(value or MediaType.NONE.value).lower()


def _normalize_media_type(raw_value: object) -> MediaType:
    """归一化媒体类型输入。"""
    if isinstance(raw_value, MediaType):
        return raw_value
    media_type = str(raw_value or MediaType.NONE.value).strip().lower()
    if media_type == "gif":
        media_type = MediaType.ANIMATION.value
    try:
        return MediaType(media_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"不支持的 media_type: {raw_value}")


def _normalize_target_peers(raw_value: Any) -> List[Dict[str, Any]]:
    """
    归一化多目标列表。
    每个元素格式：
    {
      "peer_id": int,
      "peer_type": "user|chat|supergroup|channel",
      "access_hash": int | None
    }
    """
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise HTTPException(status_code=400, detail="target_peers 必须是数组")

    normalized: List[Dict[str, Any]] = []
    allowed_types = {"user", "chat", "supergroup", "channel"}

    for idx, item in enumerate(raw_value):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"target_peers[{idx}] 必须是对象")

        raw_peer_id = item.get("peer_id", item.get("target_peer_id"))
        raw_peer_type = item.get("peer_type", item.get("target_peer_type"))
        raw_access_hash = item.get("access_hash", item.get("target_access_hash"))

        try:
            peer_id = int(raw_peer_id)
        except Exception:
            raise HTTPException(status_code=400, detail=f"target_peers[{idx}].peer_id 非法")

        peer_type = str(raw_peer_type or "").strip().lower()
        if peer_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"target_peers[{idx}].peer_type 非法，必须为 user/chat/supergroup/channel"
            )

        access_hash: Optional[int] = None
        if raw_access_hash not in (None, ""):
            try:
                access_hash = int(raw_access_hash)
            except Exception:
                raise HTTPException(status_code=400, detail=f"target_peers[{idx}].access_hash 非法")

        normalized.append(
            {
                "peer_id": peer_id,
                "peer_type": peer_type,
                "access_hash": access_hash,
            }
        )

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for peer in normalized:
        key = (peer["peer_type"], peer["peer_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(peer)

    return deduped


def _build_auto_delay_profile(priority: int, account: Optional[Account]) -> tuple[int, int, int]:
    """
    系统自动生成随机延迟参数（用户不可配置）：
    - delay_min_seconds
    - delay_max_seconds
    - jitter_seconds
    """
    weight = int(getattr(account, "weight", 100) or 100)

    if priority >= 100:
        min_range = (0, 5)
        max_range = (8, 20)
    elif weight < 50:
        min_range = (60, 120)
        max_range = (180, 300)
    elif weight < 100:
        min_range = (30, 60)
        max_range = (120, 240)
    else:
        min_range = (10, 30)
        max_range = (60, 180)

    delay_min = random.randint(*min_range)
    delay_max_low = max(delay_min + 1, max_range[0])
    delay_max = random.randint(delay_max_low, max_range[1])
    jitter_seconds = random.randint(0, min(delay_max, 300))
    return delay_min, delay_max, jitter_seconds


def _resolve_upload_media_type(upload: UploadFile) -> MediaType:
    content_type = (upload.content_type or "").lower()
    filename = (upload.filename or "").lower()

    if content_type.startswith("image/"):
        if content_type == "image/gif" or filename.endswith(".gif"):
            return MediaType.ANIMATION
        return MediaType.PHOTO
    if content_type.startswith("video/"):
        return MediaType.VIDEO
    if filename.endswith(".gif"):
        return MediaType.ANIMATION
    raise HTTPException(status_code=400, detail="仅支持图片/GIF/视频文件上传")


def _build_telegram_media_ref(account_id: str, message_id: int) -> str:
    """
    构建 Telegram 媒体引用字符串。
    格式：tgmsg://{account_id}/{message_id}
    """
    return f"{TELEGRAM_MEDIA_REF_PREFIX}{account_id}/{message_id}"


# ============ 任务管理接口 ============

async def check_task_permission(task_id: str, user_id: int) -> ScheduledMessageTask:
    """检查任务权限"""
    async with get_async_session() as session:
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        if task.user_id != user_id:
            raise HTTPException(status_code=404, detail="任务不存在")  # 隐蔽权限错误

        return task


@app.get("/api/tasks")
async def get_tasks(current_user: User = Depends(get_current_user)):
    """
    获取当前用户的任务列表
    """
    async with get_async_session() as session:
        query = select(ScheduledMessageTask).where(
            ScheduledMessageTask.user_id == current_user.id
        ).order_by(ScheduledMessageTask.created_at.desc())

        result = await session.execute(query)
        tasks = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "task_id": t.task_id,
                    "account_id": t.account_id,
                    "chat_id": t.chat_id,
                    "target_peer_id": t.target_peer_id,
                    "target_peer_type": t.target_peer_type,
                    "target_peers": t.target_peers or [],
                    "title": t.title,
                    "enabled": t.enabled,
                    "priority": t.priority,
                    "repeat_interval_min": t.repeat_interval_min,
                    "jitter_seconds": t.jitter_seconds,
                    "delay_min_seconds": t.delay_min_seconds,
                    "delay_max_seconds": t.delay_max_seconds,
                    "day_start_hour": t.day_start_hour,
                    "day_end_hour": t.day_end_hour,
                    "start_at": t.start_at,
                    "end_at": t.end_at,
                    "text": t.text,
                    "media_type": _media_value(t.media_type),
                    "delete_previous": t.delete_previous,
                    "pin_message": t.pin_message,
                    "next_run_at": t.next_run_at,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tasks
            ]
        }


@app.get("/api/tasks/{task_id}")
async def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    获取单个任务详情
    """
    task = await check_task_permission(task_id, current_user.id)

    return {
        "success": True,
        "data": {
            "task_id": task.task_id,
            "user_id": task.user_id,
            "account_id": task.account_id,
            "chat_id": task.chat_id,
            "target_peer_id": task.target_peer_id,
            "target_peer_type": task.target_peer_type,
            "target_access_hash": task.target_access_hash,
            "target_peers": task.target_peers or [],
            "title": task.title,
            "enabled": task.enabled,
            "priority": task.priority,
            "repeat_interval_min": task.repeat_interval_min,
            "jitter_seconds": task.jitter_seconds,
            "delay_min_seconds": task.delay_min_seconds,
            "delay_max_seconds": task.delay_max_seconds,
            "day_start_hour": task.day_start_hour,
            "day_end_hour": task.day_end_hour,
            "start_at": task.start_at,
            "end_at": task.end_at,
            "text": task.text,
            "media_type": _media_value(task.media_type),
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
async def create_task(
    task_data: dict,
    current_user: User = Depends(get_current_user)
):
    """
    创建任务
    """
    now_ts = int(datetime.now().timestamp())
    account: Optional[Account] = None

    # 强制关联到当前用户
    task_data["user_id"] = current_user.id

    # 检查关联的账号是否属于当前用户
    if "account_id" in task_data and task_data["account_id"]:
        account = await check_account_permission(task_data["account_id"], current_user.id)

    # 目标兼容处理：
    # - 新结构：target_peers（多目标）
    # - 兼容旧结构：target_peer_id/chat_id（单目标）
    target_peers = _normalize_target_peers(task_data.get("target_peers"))
    if not target_peers:
        raw_target_peer_id = task_data.get("target_peer_id") or task_data.get("chat_id")
        raw_target_peer_type = task_data.get("target_peer_type") or "user"
        raw_target_access_hash = task_data.get("target_access_hash")
        if not raw_target_peer_id:
            raise HTTPException(status_code=400, detail="缺少发送目标（target_peers/target_peer_id/chat_id）")
        try:
            peer_id = int(raw_target_peer_id)
        except Exception:
            raise HTTPException(status_code=400, detail="target_peer_id/chat_id 非法")
        peer_type = str(raw_target_peer_type or "").strip().lower() or "user"
        if peer_type not in {"user", "chat", "supergroup", "channel"}:
            raise HTTPException(status_code=400, detail="target_peer_type 非法")
        access_hash = None
        if raw_target_access_hash not in (None, ""):
            try:
                access_hash = int(raw_target_access_hash)
            except Exception:
                raise HTTPException(status_code=400, detail="target_access_hash 非法")
        target_peers = [{
            "peer_id": peer_id,
            "peer_type": peer_type,
            "access_hash": access_hash,
        }]

    primary_target = target_peers[0]
    task_data["target_peers"] = target_peers
    task_data["target_peer_id"] = primary_target["peer_id"]
    task_data["target_peer_type"] = primary_target["peer_type"]
    task_data["target_access_hash"] = primary_target.get("access_hash")
    task_data["chat_id"] = primary_target["peer_id"]

    repeat_interval_min = int(task_data.get("repeat_interval_min", 0) or 0)
    if repeat_interval_min <= 0:
        raise HTTPException(status_code=400, detail="repeat_interval_min 必须大于 0")

    priority = int(task_data.get("priority", 0) or 0)
    if priority < 0:
        raise HTTPException(status_code=400, detail="priority 不能小于 0")

    # 媒体类型与文件校验
    media_type = _normalize_media_type(task_data.get("media_type", MediaType.NONE.value))
    task_data["media_type"] = media_type.value
    media_file_id = task_data.get("media_file_id")
    if media_type == MediaType.NONE:
        task_data["media_file_id"] = None
    elif not media_file_id:
        raise HTTPException(status_code=400, detail="已选择媒体类型，请先上传媒体文件")

    # 产品约束：H5 不支持置顶/每日时段窗口，统一禁用
    task_data["pin_message"] = False
    task_data["day_start_hour"] = None
    task_data["day_end_hour"] = None

    # 系统自动生成三段随机延迟参数（不接受用户自定义）
    delay_min_seconds, delay_max_seconds, jitter_seconds = _build_auto_delay_profile(priority, account)
    task_data["delay_min_seconds"] = delay_min_seconds
    task_data["delay_max_seconds"] = delay_max_seconds
    task_data["jitter_seconds"] = jitter_seconds

    # 启用任务时，默认进入调度队列（若设置了未来 start_at，则以 start_at 为准）
    if task_data.get("enabled") and not task_data.get("next_run_at"):
        start_at_ts = int(task_data.get("start_at") or 0)
        task_data["next_run_at"] = max(now_ts, start_at_ts) if start_at_ts > 0 else now_ts

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
async def update_task(
    task_id: str,
    task_data: dict,
    current_user: User = Depends(get_current_user)
):
    """
    更新任务
    """
    # 检查权限
    task = await check_task_permission(task_id, current_user.id)
    now_ts = int(datetime.now().timestamp())
    was_enabled = task.enabled
    account: Optional[Account] = None

    # 如果更新了关联账号，检查账号权限
    if "account_id" in task_data and task_data["account_id"]:
        account = await check_account_permission(task_data["account_id"], current_user.id)
    elif task.account_id:
        account = await check_account_permission(task.account_id, current_user.id)

    if "repeat_interval_min" in task_data:
        repeat_interval_min = int(task_data.get("repeat_interval_min") or 0)
        if repeat_interval_min <= 0:
            raise HTTPException(status_code=400, detail="repeat_interval_min 必须大于 0")
    if "priority" in task_data:
        priority = int(task_data.get("priority") or 0)
        if priority < 0:
            raise HTTPException(status_code=400, detail="priority 不能小于 0")

    # 目标兼容处理：
    # - 显式传入 target_peers 时，以其为准
    # - 否则若传入单目标字段，则转换为 target_peers
    # - 都未传则保留原有目标
    incoming_target_peers = "target_peers" in task_data
    incoming_single_target = any(
        key in task_data for key in ("target_peer_id", "target_peer_type", "target_access_hash", "chat_id")
    )

    target_peers: List[Dict[str, Any]]
    if incoming_target_peers:
        target_peers = _normalize_target_peers(task_data.get("target_peers"))
        if not target_peers:
            raise HTTPException(status_code=400, detail="target_peers 不能为空")
    elif incoming_single_target:
        raw_target_peer_id = task_data.get("target_peer_id", task_data.get("chat_id", task.target_peer_id or task.chat_id))
        raw_target_peer_type = task_data.get("target_peer_type", task.target_peer_type or "user")
        raw_target_access_hash = task_data.get("target_access_hash", task.target_access_hash)
        if not raw_target_peer_id:
            raise HTTPException(status_code=400, detail="缺少发送目标")
        try:
            peer_id = int(raw_target_peer_id)
        except Exception:
            raise HTTPException(status_code=400, detail="target_peer_id/chat_id 非法")
        peer_type = str(raw_target_peer_type or "").strip().lower() or "user"
        if peer_type not in {"user", "chat", "supergroup", "channel"}:
            raise HTTPException(status_code=400, detail="target_peer_type 非法")
        access_hash = None
        if raw_target_access_hash not in (None, ""):
            try:
                access_hash = int(raw_target_access_hash)
            except Exception:
                raise HTTPException(status_code=400, detail="target_access_hash 非法")
        target_peers = [{
            "peer_id": peer_id,
            "peer_type": peer_type,
            "access_hash": access_hash,
        }]
    else:
        target_peers = _normalize_target_peers(task.target_peers)
        if not target_peers:
            fallback_peer_id = task.target_peer_id or task.chat_id
            if fallback_peer_id:
                target_peers = [{
                    "peer_id": int(fallback_peer_id),
                    "peer_type": str(task.target_peer_type or "user"),
                    "access_hash": task.target_access_hash,
                }]

    if target_peers:
        primary_target = target_peers[0]
        task_data["target_peers"] = target_peers
        task_data["target_peer_id"] = primary_target["peer_id"]
        task_data["target_peer_type"] = primary_target["peer_type"]
        task_data["target_access_hash"] = primary_target.get("access_hash")
        task_data["chat_id"] = primary_target["peer_id"]

    # 媒体类型与文件校验（允许清空媒体）
    if "media_type" in task_data or "media_file_id" in task_data:
        media_type = _normalize_media_type(task_data.get("media_type", task.media_type))
        media_file_id = task_data.get("media_file_id", task.media_file_id)
        task_data["media_type"] = media_type.value
        if media_type == MediaType.NONE:
            task_data["media_file_id"] = None
        elif not media_file_id:
            raise HTTPException(status_code=400, detail="已选择媒体类型，请先上传媒体文件")

    # 产品约束：H5 不支持置顶/每日时段窗口，更新时强制禁用
    task_data["pin_message"] = False
    task_data["day_start_hour"] = None
    task_data["day_end_hour"] = None

    # 系统自动生成三段随机延迟参数（不接受用户自定义）
    next_priority = int(task_data.get("priority", task.priority) or 0)
    delay_min_seconds, delay_max_seconds, jitter_seconds = _build_auto_delay_profile(next_priority, account)
    task_data["delay_min_seconds"] = delay_min_seconds
    task_data["delay_max_seconds"] = delay_max_seconds
    task_data["jitter_seconds"] = jitter_seconds

    async with get_async_session() as session:
        # 重新绑定到 session
        task = await session.merge(task)

        nullable_fields = {
            "media_file_id",
            "day_start_hour",
            "day_end_hour",
            "start_at",
            "end_at",
            "text",
            "buttons",
            "target_access_hash",
        }

        # 更新字段
        for key, value in task_data.items():
            if hasattr(task, key):
                # 禁止修改 user_id
                if key == "user_id":
                    continue
                if value is None and key not in nullable_fields:
                    continue
                setattr(task, key, value)

        # 目标兼容处理
        if task.target_peer_id and not task.chat_id:
            task.chat_id = task.target_peer_id

        # 启用任务时确保 next_run_at 有值
        if task.enabled and (not was_enabled or task.next_run_at is None):
            start_at_ts = int(task.start_at or 0)
            task.next_run_at = max(now_ts, start_at_ts) if start_at_ts > 0 else now_ts
            # 从禁用态恢复时重置失败计数，避免刚启用就再次被自动禁用
            if not was_enabled:
                task.failure_count = 0

        await session.commit()
        await session.refresh(task)

        return {"success": True}


@app.post("/api/tasks/upload-media")
async def upload_task_media(
    account_id: str = Form(...),
    media: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """
    上传任务媒体到 Telegram（账号收藏夹），返回可持久引用的 media_file_id。
    """
    await check_account_permission(account_id, current_user.id)

    if not media.filename:
        raise HTTPException(status_code=400, detail="媒体文件名为空")

    media_type = _resolve_upload_media_type(media)
    filename = media.filename
    account_manager = get_account_manager()
    client = await account_manager.get_client(account_id)
    if not client:
        raise HTTPException(status_code=400, detail="账号客户端不可用，请重新登录该账号")

    total_size = 0
    raw_data = bytearray()
    try:
        while True:
            chunk = await media.read(1024 * 1024)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > MAX_TASK_MEDIA_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"媒体文件过大，最大支持 {MAX_TASK_MEDIA_SIZE // (1024 * 1024)}MB"
                )
            raw_data.extend(chunk)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=f"读取媒体文件失败: {e}")
    finally:
        await media.close()

    if total_size <= 0:
        raise HTTPException(status_code=400, detail="媒体文件为空")

    file_buffer = io.BytesIO(bytes(raw_data))
    file_buffer.name = filename

    try:
        # 将媒体保存到执行账号的 Telegram 收藏夹，后续发送时通过消息引用复用。
        sent_msg = await client.send_file(
            "me",
            file=file_buffer,
            caption=f"[task-media] {filename}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上传到 Telegram 失败: {e}")

    media_ref = _build_telegram_media_ref(account_id, int(sent_msg.id))

    return {
        "success": True,
        "data": {
            "media_type": media_type.value,
            "media_file_id": media_ref,
            "filename": filename,
            "size": total_size,
            "storage": "telegram",
        }
    }


@app.delete("/api/tasks/{task_id}")
async def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    删除任务
    """
    # 检查权限（check_task_permission 已经做了查询）
    await check_task_permission(task_id, current_user.id)

    async with get_async_session() as session:
        await session.execute(
            delete(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        await session.commit()

        return {"success": True}


@app.get("/api/tasks/{task_id}/logs")
async def get_task_logs(
    task_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """
    获取任务日志
    """
    # 检查权限
    await check_task_permission(task_id, current_user.id)

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
async def batch_update_tasks(
    task_ids: List[str],
    update_data: dict,
    current_user: User = Depends(get_current_user)
):
    """
    批量更新任务
    """
    async with get_async_session() as session:
        count = 0
        now_ts = int(datetime.now().timestamp())
        for task_id in task_ids:
            # 检查每个任务的权限
            result = await session.execute(
                select(ScheduledMessageTask).where(
                    ScheduledMessageTask.task_id == task_id,
                    ScheduledMessageTask.user_id == current_user.id
                )
            )
            task = result.scalar_one_or_none()

            if task:
                for key, value in update_data.items():
                    if hasattr(task, key) and key not in {"user_id", "task_id"}:
                        setattr(task, key, value)

                if task.enabled and task.next_run_at is None:
                    start_at_ts = int(task.start_at or 0)
                    task.next_run_at = max(now_ts, start_at_ts) if start_at_ts > 0 else now_ts
                count += 1

        if count > 0:
            await session.commit()

        return {"success": True, "count": count}


# ============ 登录相关接口 ============

def generate_login_id() -> str:
    """生成随机登录 ID"""
    chars = string.ascii_letters + string.digits
    return 'login_' + ''.join(random.choices(chars, k=16))


@app.post("/api/login/create")
async def create_login_session(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    创建新的登录会话（使用 Redis 存储状态）

    返回登录会话 ID 和 qr_url，前端直接使用 qr_url 生成二维码
    """
    login_manager = get_redis_login_manager()

    # 创建登录会话
    login_id = generate_login_id()
    session = await login_manager.create_session(login_id)
    await login_manager.update_status(login_id, LoginStatus.PENDING, system_user_id=current_user.id)

    # 使用临时会话客户端生成二维码，避免覆盖全局 userbot 会话，支持多账号绑定
    login_client = TelegramClient(
        StringSession(),
        api_id=settings.api_id,
        api_hash=settings.api_hash,
    )
    await login_client.connect()
    qr_login = await login_client.qr_login()
    qr_url = qr_login.url

    # 保存到 Redis
    await login_manager.update_qr_url(login_id, qr_url)
    await login_manager.update_status(login_id, LoginStatus.PENDING)

    # 后台任务：等待扫码
    background_tasks.add_task(_wait_for_qr_login, login_id, qr_login, login_client)

    return {
        "success": True,
        "data": {
            "login_id": login_id,
            "qr_url": qr_url,
            "expires_at": session.expires_at
        }
    }


@app.get("/api/login/status")
async def get_login_status(
    login_id: str,
    current_user: User = Depends(get_current_user)
):
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

    # 登录会话归属校验：防止跨用户轮询/窃取绑定态
    owner_user_id = session.system_user_id
    if owner_user_id is not None:
        try:
            owner_user_id = int(owner_user_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=404, detail="会话不存在")
        if owner_user_id != current_user.id:
            raise HTTPException(status_code=404, detail="会话不存在")

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
async def check_login_status(current_user: User = Depends(get_current_user)):
    """
    检查 Userbot 登录状态

    返回当前 Userbot 是否已登录
    """
    is_ready = await is_userbot_ready()

    return {
        "success": True,
        "data": {
            "is_logged_in": is_ready
        }
    }


@app.post("/api/login/bind")
async def bind_account(request: Request, current_user: User = Depends(get_current_user)):
    """
    绑定 Telegram 账号到当前系统用户

    Args:
        request: 请求对象，包含 bind_code
        current_user: 当前登录的系统用户
    """
    data = await request.json()
    bind_code = data.get("bind_code")

    if not bind_code:
        raise HTTPException(status_code=400, detail="缺少绑定码")

    login_manager = get_redis_login_manager()
    bind_data = await login_manager.get_account_by_bind_code(bind_code)
    if not bind_data:
        raise HTTPException(status_code=400, detail="绑定失败：绑定码无效或已过期")

    owner_user_id = bind_data.get("system_user_id")
    if owner_user_id is not None and int(owner_user_id) != current_user.id:
        raise HTTPException(status_code=403, detail="该绑定码不属于当前系统用户")

    account_manager = get_account_manager()

    # 绑定账号
    account = await account_manager.bind_account(
        user_id=current_user.id,
        bind_code=bind_code,
        ip_address=request.client.host
    )

    if not account:
        raise HTTPException(status_code=400, detail="绑定失败：绑定码无效或账号已绑定")

    return {
        "success": True,
        "message": "绑定成功",
        "data": {
            "account_id": account.account_id,
            "username": account.username
        }
    }


@app.get("/api/login/get-token")
async def get_existing_token():
    """
    [已弃用] 获取已登录 userbot 的 token
    保留此接口为了兼容性，但不再使用
    """
    return JSONResponse(
        {"success": False, "error": "接口已弃用，请使用系统登录"},
        status_code=410
    )


# ============ 账号管理接口 ============

async def check_account_permission(account_id: str, user_id: int) -> Account:
    """检查账号权限"""
    account_manager = get_account_manager()
    account = await account_manager.get_account(account_id)
    if not account or account.user_id != user_id:
        raise HTTPException(status_code=404, detail="账号不存在")
    return account


async def check_proxy_permission(proxy_id: int, user_id: int) -> Proxy:
    """检查代理权限（已分配代理必须属于当前用户账号）。"""
    proxy_pool = get_proxy_pool()
    proxy = await proxy_pool.get_proxy(proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="代理不存在")

    if proxy.assigned_account_id:
        # 若代理已绑定账号，则要求该账号属于当前用户
        await check_account_permission(proxy.assigned_account_id, user_id)

    return proxy


@app.get("/api/accounts/")
async def get_accounts(current_user: User = Depends(get_current_user)):
    """
    获取当前用户的所有账号
    """
    account_manager = get_account_manager()
    # 获取所有状态的账号（包括禁用的）
    accounts = await account_manager.get_accounts(current_user.id, is_active=False)
    now = datetime.now()

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
                "bind_code": (
                    acc.bind_code
                    if acc.bind_code and acc.bind_code_expires_at and acc.bind_code_expires_at > now
                    else None
                ),
                "bind_code_expires_at": (
                    acc.bind_code_expires_at.isoformat()
                    if acc.bind_code and acc.bind_code_expires_at and acc.bind_code_expires_at > now
                    else None
                ),
            }
            for acc in accounts
        ]
    }


@app.post("/api/accounts/{account_id}/sync")
async def sync_account_resources(
    account_id: str,
    background_tasks: BackgroundTasks,
    wait: bool = False,
    current_user: User = Depends(get_current_user)
):
    """
    同步账号的 Telegram 资源
    """
    # 检查权限
    await check_account_permission(account_id, current_user.id)

    resource_manager = get_resource_manager()

    if wait:
        result = await resource_manager.full_sync(account_id)
        if result.error:
            raise HTTPException(status_code=400, detail=f"资源同步失败: {result.error}")
        if result.synced == 0 and result.failed > 0:
            raise HTTPException(status_code=400, detail=f"资源同步失败: 全部 {result.failed} 项同步失败")

        message = "资源同步完成"
        if result.failed > 0:
            message = f"资源同步部分成功：失败 {result.failed} 条"

        return {
            "success": True,
            "message": message,
            "data": {
                "synced": result.synced,
                "new": result.new,
                "updated": result.updated,
                "deleted": result.deleted,
                "failed": result.failed,
                "error": result.error or None,
            },
        }

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
    background_tasks.add_task(run_sync)

    return {
        "success": True,
        "message": "资源同步已启动，请稍后查看结果"
    }


@app.post("/api/accounts/{account_id}/bind-code")
async def refresh_account_bind_code(
    account_id: str,
    refresh: bool = True,
    current_user: User = Depends(get_current_user)
):
    """
    获取或刷新账号绑定码（用于 /bind 快捷操作）。
    """
    await check_account_permission(account_id, current_user.id)

    account_manager = get_account_manager()
    try:
        issued = await account_manager.issue_bind_code(account_id, refresh=refresh)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not issued:
        raise HTTPException(status_code=404, detail="账号不存在")

    expires_at = issued["expires_at"]
    ttl_seconds = issued.get("ttl_seconds")
    if ttl_seconds is None and expires_at:
        ttl_seconds = max(0, int((expires_at - datetime.now()).total_seconds()))

    return {
        "success": True,
        "data": {
            "bind_code": issued["bind_code"],
            "expires_at": expires_at.isoformat() if expires_at else None,
            "ttl_seconds": ttl_seconds,
        },
    }


@app.get("/api/accounts/{account_id}/resources")
async def get_account_resources(
    account_id: str,
    peer_type: Optional[str] = None,
    is_active: bool = True,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """
    获取账号的资源列表
    """
    # 检查权限
    await check_account_permission(account_id, current_user.id)

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
                "title": (
                    (r.title or "").strip()
                    or (f"@{r.username}" if r.username else f"{r.peer_type}:{r.peer_id}")
                ),
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
async def disable_account(
    account_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    禁用账号
    """
    # 检查权限
    await check_account_permission(account_id, current_user.id)

    account_manager = get_account_manager()
    await account_manager.update_account(account_id, is_active=False)

    return {"success": True, "message": "账号已禁用"}


@app.post("/api/accounts/{account_id}/enable")
async def enable_account(
    account_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    启用账号
    """
    # 检查权限
    await check_account_permission(account_id, current_user.id)

    account_manager = get_account_manager()
    await account_manager.update_account(account_id, is_active=True)

    return {"success": True, "message": "账号已启用"}


@app.delete("/api/accounts/{account_id}")
async def delete_account(
    account_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    删除账号
    """
    # 检查权限
    await check_account_permission(account_id, current_user.id)

    account_manager = get_account_manager()
    try:
        await account_manager.delete_account(account_id)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"success": True, "message": "账号已删除"}


# ============ 代理管理接口 ============

@app.get("/api/proxies/")
async def get_proxies(current_user: User = Depends(get_current_user)):
    """
    获取所有代理

    Returns:
        代理列表
    """
    async with get_async_session() as session:
        owned_accounts_result = await session.execute(
            select(Account.account_id).where(Account.user_id == current_user.id)
        )
        owned_account_ids = [row[0] for row in owned_accounts_result.all()]

        query = select(Proxy)
        if owned_account_ids:
            query = query.where(
                or_(
                    Proxy.assigned_account_id.is_(None),
                    Proxy.assigned_account_id.in_(owned_account_ids)
                )
            )
        else:
            query = query.where(Proxy.assigned_account_id.is_(None))

        result = await session.execute(query.order_by(Proxy.created_at.desc()))
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
async def add_proxy(proxy_data: dict, current_user: User = Depends(get_current_user)):
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
async def check_proxy_health(proxy_id: int, current_user: User = Depends(get_current_user)):
    """
    检查代理健康状态

    Args:
        proxy_id: 代理 ID

    Returns:
        健康检查结果
    """
    await check_proxy_permission(proxy_id, current_user.id)
    proxy_pool = get_proxy_pool()
    status = await proxy_pool.check_health(proxy_id)

    return {
        "success": True,
        "data": {
            "is_healthy": status.is_healthy,
            "response_time_ms": status.response_time_ms,
            "error": status.error or None
        }
    }


@app.delete("/api/proxies/{proxy_id}")
async def delete_proxy(proxy_id: int, current_user: User = Depends(get_current_user)):
    """
    删除代理

    Args:
        proxy_id: 代理 ID

    Returns:
        操作结果
    """
    await check_proxy_permission(proxy_id, current_user.id)
    proxy_pool = get_proxy_pool()
    deleted = await proxy_pool.delete_proxy(proxy_id)
    if not deleted:
        raise HTTPException(status_code=400, detail="代理删除失败（可能已分配到账号）")

    return {"success": True, "message": "代理已删除"}


@app.post("/api/proxies/{proxy_id}/assign")
async def assign_proxy(
    proxy_id: int,
    account_id: str,
    current_user: User = Depends(get_current_user)
):
    """
    将代理分配给账号

    Args:
        proxy_id: 代理 ID
        account_id: 账号 ID

    Returns:
        操作结果
    """
    await check_account_permission(account_id, current_user.id)

    proxy_pool = get_proxy_pool()
    proxy = await proxy_pool.get_proxy(proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="代理不存在")

    # 若代理已被占用，要求其归属当前用户（避免越权）
    if proxy.assigned_account_id and proxy.assigned_account_id != account_id:
        await check_account_permission(proxy.assigned_account_id, current_user.id)

    assigned = await proxy_pool.assign_proxy(account_id, proxy_id)
    if not assigned:
        raise HTTPException(status_code=400, detail="代理分配失败（可能已被占用或账号不存在）")

    return {"success": True, "message": "代理已分配"}


@app.post("/api/proxies/{proxy_id}/unassign")
async def unassign_proxy(
    proxy_id: int,
    current_user: User = Depends(get_current_user)
):
    """
    解绑代理

    Args:
        proxy_id: 代理 ID

    Returns:
        操作结果
    """
    proxy = await check_proxy_permission(proxy_id, current_user.id)
    proxy_pool = get_proxy_pool()
    if not proxy.assigned_account_id:
        raise HTTPException(status_code=400, detail="代理未分配账号")

    unassigned = await proxy_pool.unassign_proxy(proxy.assigned_account_id)
    if not unassigned:
        raise HTTPException(status_code=400, detail="代理解绑失败")

    return {"success": True, "message": "代理已解绑"}


# ============ 前端静态文件服务 ============

# 统一 H5 前端：使用 Vue SPA 作为管理端唯一入口
frontend_dist = os.path.join(PROJECT_ROOT, "frontend", "h5", "dist")
frontend_index_file = os.path.join(frontend_dist, "index.html")

if os.path.exists(frontend_index_file):
    # 挂载前端静态资源目录
    static_dist = os.path.join(frontend_dist, "assets")
    if os.path.exists(static_dist):
        app.mount("/assets", StaticFiles(directory=static_dist), name="frontend-assets")

    def serve_frontend_index() -> FileResponse:
        """返回统一前端入口文件"""
        return FileResponse(frontend_index_file)

    @app.get("/", include_in_schema=False)
    async def serve_frontend_root():
        return serve_frontend_index()

    # 关键 SPA 路由（避免刷新直达时 404）
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
        """
        SPA fallback:
        非 API/静态资源路径统一返回 index.html，确保只有一个 H5 管理前端入口。
        """
        excluded_prefixes = ("api", "assets", "static", "docs", "redoc", "openapi.json")
        for prefix in excluded_prefixes:
            if full_path == prefix or full_path.startswith(f"{prefix}/"):
                raise HTTPException(status_code=404, detail="Not Found")
        return serve_frontend_index()

    print(f"✓ 前端静态文件已挂载: {frontend_dist}")
else:
    print(f"⚠ 前端构建产物不存在: {frontend_dist}")
    print(f"  提示: 运行 'cd frontend/h5 && npm run build' 构建前端")
