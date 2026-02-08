"""
调度器 Worker：定时扫描并发送消息（增强版）

新功能：
- 10秒扫描间隔（可配置）
- 多账号支持
- Jitter 随机抖动
- 速率限制
- 熔断器
- 零宽字符去重
- 任务分片到 Redis 队列
"""
import asyncio
import random
from datetime import datetime
from typing import Optional
import redis.asyncio as redis

from loguru import logger
from telethon.errors import FloodWaitError, RPCError

from config.settings import settings
from database.session import get_async_session
from database.models import ScheduledMessageTask, TaskLog, MediaType
from bot.account_manager import get_account_manager, AccountSelectionStrategy
from bot.resource_manager import get_resource_manager
from bot.rate_limiter import get_rate_limiter, acquire_locks_and_send
from bot.circuit_breaker import get_circuit_breaker, FloodWaitAction
from bot.keyboards import build_inline_buttons


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
    JITTER_RANGE = 300  # 最大抖动 5 分钟（300秒）

    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.running = False

        # 获取各模块实例
        self._account_manager = get_account_manager()
        self._resource_manager = get_resource_manager()
        self._rate_limiter = get_rate_limiter()
        self._circuit_breaker = get_circuit_breaker()

    async def init(self):
        """初始化"""
        # 初始化 Redis
        self.redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True
        )

        logger.info("增强型任务调度器初始化完成")

    async def start(self):
        """启动调度器"""
        self.running = True
        logger.info(f"任务调度器已启动（扫描间隔: {self.SCAN_INTERVAL}秒）")

        while self.running:
            try:
                await self.tick()
                await asyncio.sleep(self.SCAN_INTERVAL)
            except Exception as e:
                logger.error(f"调度器运行错误: {e}")
                await asyncio.sleep(self.SCAN_INTERVAL)

    async def stop(self):
        """停止调度器"""
        self.running = False
        logger.info("任务调度器已停止")

    async def tick(self):
        """执行一次扫描和发送"""
        now = int(datetime.now().timestamp())
        current_hour = datetime.now().hour

        logger.debug(f"执行调度扫描，当前时间: {datetime.now()}")

        # 1. 从数据库获取待执行任务，加入 Redis 队列
        await self._enqueue_tasks(now)

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
        async with get_async_session() as session:
            from sqlalchemy import select

            # 查询需要执行的任务
            query = (
                select(ScheduledMessageTask)
                .where(
                    ScheduledMessageTask.enabled == True,
                    ScheduledMessageTask.next_run_at.isnot(None),
                    ScheduledMessageTask.next_run_at <= now
                )
                .limit(100)
            )

            result = await session.execute(query)
            tasks = result.scalars().all()

            # 加入 Redis 队列
            for task in tasks:
                # 计算带抖动的执行时间
                jitter = random.randint(0, min(task.jitter_seconds, self.JITTER_RANGE))
                execution_time = now + jitter

                # 队列成员格式：task_id
                # 分数：执行时间戳
                await self.redis_client.zadd(
                    self.TASK_QUEUE_KEY,
                    {task.task_id: execution_time}
                )

                logger.debug(
                    f"任务 {task.task_id} 加入队列，"
                    f"抖动: {jitter}秒，执行时间: {execution_time}"
                )

    async def _get_pending_tasks(self, now: int) -> list:
        """
        从 Redis 队列获取需要执行的任务

        Args:
            now: 当前时间戳

        Returns:
            待执行任务列表
        """
        # 获取执行时间 <= now 的任务
        task_ids = await self.redis_client.zrangebyscore(
            self.TASK_QUEUE_KEY,
            min=0,
            max=now,
            start=0,
            num=50
        )

        if not task_ids:
            return []

        # 从队列中移除（避免重复执行）
        if task_ids:
            await self.redis_client.zrem(self.TASK_QUEUE_KEY, *task_ids)

        # 获取任务详情
        tasks = []
        async with get_async_session() as session:
            from sqlalchemy import select

            for task_id in task_ids:
                result = await session.execute(
                    select(ScheduledMessageTask).where(
                        ScheduledMessageTask.task_id == task_id
                    )
                )
                task = result.scalar_one_or_none()
                if task and task.enabled:
                    tasks.append(task)

        return tasks

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
        await self.redis_client.set(processing_key, "1", ex=300)

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

                # 检查账号（新架构）
                account_id = task.account_id
                chat_id = task.chat_id  # 兼容旧数据

                # 确定目标 Peer ID
                target_peer_id = task.target_peer_id or chat_id
                if not target_peer_id:
                    logger.warning(f"任务 {task_id} 没有目标 Peer ID")
                    return

                # 获取执行账号
                if not account_id:
                    # 兼容旧数据：使用默认 Userbot
                    from bot.client import userbot_client
                    client = userbot_client
                    account_id_str = "default"
                else:
                    # 新架构：使用 AccountManager
                    client = await self._account_manager.get_client(account_id)
                    account_id_str = account_id

                    if not client:
                        logger.error(f"无法获取账号客户端: {account_id}")
                        await self._handle_task_failure(session, task, "无法获取账号客户端")
                        return

                # 检查日期范围
                if task.start_at and now < task.start_at:
                    logger.debug(f"任务 {task_id} 未到开始时间")
                    return

                if task.end_at and now > task.end_at:
                    task.enabled = False
                    await session.commit()
                    logger.info(f"任务 {task_id} 已超过结束时间，自动禁用")
                    return

                # 检查时段限制
                if not self._check_time_limit(task, current_hour, now, session):
                    return

                # 使用速率限制器和熔断器执行发送
                try:
                    message_id = await self._send_with_protections(
                        client, task, target_peer_id, account_id_str
                    )

                    if message_id:
                        # 成功
                        await self._handle_task_success(session, task, message_id, now)
                        logger.info(f"任务 {task_id} 执行成功，消息 ID: {message_id}")
                    else:
                        # 失败
                        await self._handle_task_failure(session, task, "发送失败")

                except FloodWaitError as e:
                    # FloodWait 错误处理
                    action = await self._circuit_breaker.handle_flood_wait(
                        account_id_str, e
                    )

                    if action == FloodWaitAction.BAN:
                        # 账号被封禁，禁用任务
                        task.enabled = False
                        await session.commit()
                    elif action == FloodWaitAction.SKIP:
                        # 跳过本次，稍后重试
                        await self._handle_task_failure(
                            session, task, f"FloodWait: {e.seconds}秒"
                        )

                except Exception as e:
                    logger.error(f"执行任务 {task_id} 时出错: {e}")
                    await self._handle_task_failure(session, task, str(e))

        finally:
            # 清除处理标记
            await self.redis_client.delete(processing_key)

    async def _send_with_protections(
        self,
        client,
        task: ScheduledMessageTask,
        target_peer_id: int,
        account_id: str
    ) -> Optional[int]:
        """
        使用速率限制和熔断器发送消息

        Args:
            client: TelegramClient
            task: 任务对象
            target_peer_id: 目标 Peer ID
            account_id: 账号 ID

        Returns:
            消息 ID
        """
        # 获取速率限制器
        rate_limiter = get_rate_limiter()
        circuit_breaker = get_circuit_breaker()

        # 获取发送锁（速率限制）
        await rate_limiter.wait_for_slot(account_id, target_peer_id)

        # 使用熔断器包装发送
        return await circuit_breaker.execute_with_circuit_breaker(
            account_id,
            self._do_send_message,
            client, task, target_peer_id
        )

    async def _do_send_message(
        self,
        client,
        task: ScheduledMessageTask,
        target_peer_id: int
    ) -> Optional[int]:
        """
        实际发送消息

        Args:
            client: TelegramClient
            task: 任务对象
            target_peer_id: 目标 Peer ID

        Returns:
            消息 ID
        """
        # 添加零宽字符（去重）
        text = task.text
        if text:
            rate_limiter = get_rate_limiter()
            text = rate_limiter.add_invisible_variation(text)

        # 构建按钮
        buttons = build_inline_buttons(task.buttons)

        # 发送消息
        if task.media_type != MediaType.NONE:
            # 带媒体的消息
            if task.media_type == MediaType.PHOTO:
                msg = await client.send_file(
                    target_peer_id,
                    file=task.media_file_id,
                    caption=text,
                    buttons=buttons,
                    parse_mode='html'
                )
            elif task.media_type == MediaType.VIDEO:
                msg = await client.send_file(
                    target_peer_id,
                    file=task.media_file_id,
                    caption=text,
                    buttons=buttons,
                    parse_mode='html'
                )
            elif task.media_type == MediaType.ANIMATION:
                msg = await client.send_file(
                    target_peer_id,
                    file=task.media_file_id,
                    caption=text,
                    buttons=buttons,
                    parse_mode='html'
                )
            elif task.media_type == MediaType.STICKER:
                msg = await client.send_file(
                    target_peer_id,
                    file=task.media_file_id,
                    buttons=buttons
                )
            else:
                logger.error(f"不支持的媒体类型: {task.media_type}")
                return None
        else:
            # 纯文本消息
            msg = await client.send_message(
                target_peer_id,
                text,
                buttons=buttons,
                parse_mode='html'
            )

        return msg.id if msg else None

    def _check_time_limit(
        self,
        task: ScheduledMessageTask,
        current_hour: int,
        now: int,
        session
    ) -> bool:
        """
        检查时段限制

        Returns:
            是否在允许的时段内
        """
        if task.day_start_hour is None or task.day_end_hour is None:
            return True

        in_time_range = False

        if task.day_start_hour <= task.day_end_hour:
            # 正常时段：[start, end)
            in_time_range = task.day_start_hour <= current_hour < task.day_end_hour
        else:
            # 跨天时段：[start, 24) ∪ [0, end)
            in_time_range = current_hour >= task.day_start_hour or current_hour < task.day_end_hour

        if not in_time_range:
            logger.debug(f"任务 {task.task_id} 不在时段内，跳过")
            # 计算下一次运行时间
            next_hour = task.day_start_hour if current_hour >= task.day_end_hour else current_hour
            next_run = self._calculate_next_run(now, next_hour, task.repeat_interval_min)
            task.next_run_at = next_run
            return False

        return True

    async def _handle_task_success(
        self,
        session,
        task: ScheduledMessageTask,
        message_id: int,
        now: int
    ):
        """处理任务成功"""
        # 记录成功日志
        log = TaskLog(
            task_id=task.task_id,
            result="success",
            message_id=message_id
        )
        session.add(log)

        # 更新任务状态
        task.last_sent_message_id = message_id
        task.failure_count = 0
        task.next_run_at = now + task.repeat_interval_min * 60

        # 更新账号统计
        if task.account_id:
            await self._account_manager.increment_messages_sent(task.account_id)

        await session.commit()

    async def _handle_task_failure(
        self,
        session,
        task: ScheduledMessageTask,
        error_message: str
    ):
        """处理任务失败"""
        # 记录失败日志
        log = TaskLog(
            task_id=task.task_id,
            result="failed",
            error_message=error_message
        )
        session.add(log)

        # 增加失败计数
        task.failure_count += 1

        # 连续失败多次，自动禁用
        if task.failure_count >= settings.max_failure_count:
            task.enabled = False
            logger.warning(
                f"任务 {task.task_id} 连续失败 {task.failure_count} 次，"
                f"自动禁用"
            )

        await session.commit()

    def _calculate_next_run(self, now: int, target_hour: int, interval_min: int) -> int:
        """计算下一次运行时间"""
        # 简化计算，直接加上间隔
        return now + interval_min * 60


# 全局调度器实例
scheduler = TaskScheduler()
