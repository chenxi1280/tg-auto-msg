"""调度器 Worker：编排扫描、入队、执行与任务状态流转。"""
import asyncio
from datetime import datetime
from typing import Optional

import redis.asyncio as redis
from fastapi import HTTPException
from loguru import logger

from backend.bot.account.manager import get_account_manager
from backend.config.core.settings import settings
from backend.database.schema.models import ScheduledMessageTask
from backend.database.runtime.session import get_async_session
from backend.scheduler.core.queue_ops import (
    enqueue_due_tasks as _enqueue_due_tasks,
    ensure_redis_connection as _ensure_redis_connection,
    get_pending_tasks as _get_pending_tasks,
)
from backend.scheduler.core.task_runner import execute_task_once as _execute_task_once


class TaskScheduler:
    """
    增强型任务调度器

    改进：
    - 10 秒扫描间隔（更快响应）
    - 多账号负载均衡
    - Jitter 随机抖动（防风控）
    - 多级速率限制
    - 熔断自愈
    - 零宽字符去重
    """

    # Redis Key 前缀
    TASK_QUEUE_KEY = "queue:tasks:pending"      # 有序集合，按执行时间排序
    PROCESSING_QUEUE_KEY = "queue:tasks:processing"  # Hash，正在处理的任务

    # 配置
    SCAN_INTERVAL = 10  # 10 秒扫描间隔
    PROCESSING_TTL = 300
    JITTER_RANGE = 300  # 最大抖动 5 分钟（300秒）
    URGENT_PRIORITY_THRESHOLD = 100
    TELEGRAM_MEDIA_REF_PREFIX = "tgmsg://"

    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.running = False

        # 获取各模块实例
        self._account_manager = get_account_manager()

    async def init(self):
        """初始化"""
        # 初始化 Redis
        self.redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True
        )
        await self._ensure_redis_connection()
        await self._recover_runtime_state()

        logger.info("增强型任务调度器初始化完成")

    async def _ensure_redis_connection(self):
        """确保 Redis 连接可用，不可用时自动重建。"""
        try:
            self.redis_client = await _ensure_redis_connection(
                self.redis_client,
                settings.redis_url,
            )
        except Exception as e:
            logger.warning(f"调度器 Redis 连接不可用，尝试重连失败: {e}")
            raise

    async def _recover_runtime_state(self):
        """服务启动时恢复任务运行态，避免重启后任务卡死。"""
        now = int(datetime.now().timestamp())
        repaired_next_run = 0
        disabled_expired = 0
        cleared_processing = 0

        async with get_async_session() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(ScheduledMessageTask).where(ScheduledMessageTask.enabled == True)
            )
            tasks = result.scalars().all()

            for task in tasks:
                if task.end_at and now > int(task.end_at):
                    task.enabled = False
                    disabled_expired += 1
                    continue

                if task.next_run_at is None:
                    start_at_ts = int(task.start_at or 0)
                    task.next_run_at = max(now, start_at_ts) if start_at_ts > 0 else now
                    repaired_next_run += 1

            if repaired_next_run or disabled_expired:
                await session.commit()

        cursor = None
        pattern = f"{self.PROCESSING_QUEUE_KEY}:*"
        while True:
            cursor, keys = await self.redis_client.scan(cursor=cursor or 0, match=pattern, count=200)
            if keys:
                await self.redis_client.delete(*keys)
                cleared_processing += len(keys)
            if str(cursor) == "0":
                break

        await self._enqueue_tasks(now)
        logger.info(
            "调度器恢复完成: 修复 next_run_at={}, 禁用已过期任务={}, 清理处理中锁={}",
            repaired_next_run,
            disabled_expired,
            cleared_processing,
        )

    async def start(self):
        """启动调度器"""
        self.running = True
        mode = getattr(settings, "scheduler_mode", "all").lower()
        logger.info(f"任务调度器已启动（模式: {mode}, 扫描间隔: {self.SCAN_INTERVAL}秒）")

        while self.running:
            try:
                await self.tick(mode=mode)
                await asyncio.sleep(self.SCAN_INTERVAL)
            except Exception as e:
                logger.exception(f"调度器运行错误: {type(e).__name__}: {e!r}")
                await asyncio.sleep(self.SCAN_INTERVAL)

    async def stop(self):
        """停止调度器"""
        self.running = False
        logger.info("任务调度器已停止")

    async def tick(self, mode: str = "all"):
        """执行一次扫描和发送（支持 producer/consumer 分离模式）"""
        await self._ensure_redis_connection()
        now = int(datetime.now().timestamp())
        current_hour = datetime.now().hour

        logger.debug(f"执行调度扫描，当前时间: {datetime.now()}")

        if mode in ("all", "producer"):
            # 1. 从数据库获取待执行任务，加入 Redis 队列
            await self._enqueue_tasks(now)

        if mode not in ("all", "consumer"):
            return

        # 2. 从 Redis 队列获取需要执行的任务
        tasks_to_execute = await self._get_pending_tasks(now)

        if not tasks_to_execute:
            return

        logger.info(f"本次扫描待执行任务数: {len(tasks_to_execute)}")

        # 3. 并发执行任务（受速率限制控制）
        for task_data in tasks_to_execute:
            await self._execute_task_from_queue(task_data, now, current_hour)

    async def _enqueue_tasks(self, now: int):
        """
        从数据库获取待执行任务，加入 Redis 队列

        Args:
            now: 当前时间戳
        """
        await _enqueue_due_tasks(
            now=now,
            redis_client=self.redis_client,
            queue_key=self.TASK_QUEUE_KEY,
            account_manager=self._account_manager,
            jitter_range=self.JITTER_RANGE,
            urgent_priority_threshold=self.URGENT_PRIORITY_THRESHOLD,
        )

    async def _get_pending_tasks(self, now: int) -> list:
        """
        从 Redis 队列获取需要执行的任务

        Args:
            now: 当前时间戳

        Returns:
            待执行任务列表
        """
        return await _get_pending_tasks(
            now=now,
            redis_client=self.redis_client,
            queue_key=self.TASK_QUEUE_KEY,
            batch_size=50,
        )

    async def _execute_task_from_queue(
        self,
        task: ScheduledMessageTask,
        now: int,
        current_hour: int
    ):
        """
        执行单个任务

        Args:
            task: 任务对象
            now: 当前时间戳
            current_hour: 当前小时
        """
        task_id = task.task_id

        # 检查任务是否已在处理中
        processing_key = f"{self.PROCESSING_QUEUE_KEY}:{task_id}"
        is_processing = await self.redis_client.exists(processing_key)

        if is_processing:
            logger.debug(f"任务 {task_id} 正在处理中，跳过")
            return

        # 标记为处理中
        await self.redis_client.set(processing_key, "1", ex=self.PROCESSING_TTL)

        try:
            async with get_async_session() as session:
                from sqlalchemy import select

                # 重新获取任务（最新状态）
                result = await session.execute(
                    select(ScheduledMessageTask).where(
                        ScheduledMessageTask.task_id == task_id
                    )
                )
                task = result.scalar_one_or_none()

                if not task or not task.enabled:
                    logger.debug(f"任务 {task_id} 不存在或已禁用")
                    return
            try:
                summary = await _execute_task_once(
                    task_id,
                    trigger_source="scheduler",
                    advance_schedule=True,
                    respect_schedule_constraints=True,
                )
            except HTTPException as exc:
                logger.debug("任务 {} 跳过执行: {}", task_id, exc.detail)
                return
            if summary.status in {"success", "partial_success"}:
                logger.info(
                    "任务 {} 执行完成: status={}, success={}, failed={}",
                    task_id,
                    summary.status,
                    summary.success_count,
                    summary.failed_count,
                )
            elif summary.status == "failed":
                logger.warning("任务 {} 执行失败: {}", task_id, summary.error_summary or "未知错误")

        finally:
            # 清除处理标记
            await self.redis_client.delete(processing_key)

# 全局调度器实例
scheduler = TaskScheduler()
