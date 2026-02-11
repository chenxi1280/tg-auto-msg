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
import os
import random
from datetime import datetime
from typing import Optional
import redis.asyncio as redis

from loguru import logger
from telethon.errors import FloodWaitError, PeerFloodError

from config.settings import settings
from database.session import get_async_session
from database.models import ScheduledMessageTask, TaskLog, MediaType
from bot.account_manager import get_account_manager
from bot.resource_manager import get_resource_manager
from bot.rate_limiter import get_rate_limiter
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
    URGENT_PRIORITY_THRESHOLD = 100

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
        await self._ensure_redis_connection()

        logger.info("增强型任务调度器初始化完成")

    async def _ensure_redis_connection(self):
        """确保 Redis 连接可用，不可用时自动重建。"""
        if self.redis_client is None:
            self.redis_client = redis.from_url(
                settings.redis_url,
                decode_responses=True
            )
        try:
            await self.redis_client.ping()
        except Exception as e:
            logger.warning(f"调度器 Redis 连接不可用，尝试重连: {e}")
            try:
                await self.redis_client.close()
            except Exception:
                pass
            self.redis_client = redis.from_url(
                settings.redis_url,
                decode_responses=True
            )
            await self.redis_client.ping()

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
                .order_by(
                    ScheduledMessageTask.priority.desc(),
                    ScheduledMessageTask.next_run_at.asc()
                )
                .limit(100)
            )

            result = await session.execute(query)
            tasks = result.scalars().all()

            # 加入 Redis 队列
            for task in tasks:
                # 计算带抖动的执行时间（优先使用 [delay_min_seconds, delay_max_seconds]）
                delay_min = max(0, int(getattr(task, "delay_min_seconds", 0) or 0))
                delay_max = max(delay_min, int(getattr(task, "delay_max_seconds", 0) or 0))

                if delay_max > 0:
                    upper = min(delay_max, self.JITTER_RANGE)
                    lower = min(delay_min, upper)
                    jitter = random.randint(lower, upper)
                else:
                    jitter_base = max(0, int(getattr(task, "jitter_seconds", 0) or 0))
                    jitter = random.randint(0, min(jitter_base, self.JITTER_RANGE))

                # 紧急任务插队：高优先级任务尽可能降低额外抖动
                if (task.priority or 0) >= self.URGENT_PRIORITY_THRESHOLD:
                    jitter = min(jitter, 3)

                # 权重感知：低权重账号额外增加随机延迟，降低风控风险
                if task.account_id:
                    account = await self._account_manager.get_account(task.account_id)
                    if account and account.weight < 100:
                        extra_max = min(120, (100 - account.weight) * 2)
                        jitter += random.randint(0, extra_max)

                execution_time = now + jitter

                # 队列成员格式：task_id；分数：执行时间戳
                # 关键策略：仅允许把已有任务“提前”，不允许“延后”，
                # 避免扫描时反复覆盖导致任务长期不触发。
                existing_score = await self.redis_client.zscore(self.TASK_QUEUE_KEY, task.task_id)
                if existing_score is None:
                    await self.redis_client.zadd(
                        self.TASK_QUEUE_KEY,
                        {task.task_id: execution_time}
                    )
                elif execution_time < int(existing_score):
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

                # 收集目标列表（兼容旧结构的单目标）
                target_specs = self._collect_task_targets(task)
                if not target_specs:
                    logger.warning(f"任务 {task_id} 没有目标 Peer ID")
                    await self._handle_task_failure(session, task, "缺少目标 Peer ID")
                    return

                # 获取执行账号
                if not account_id:
                    # 兼容旧数据：使用默认 Userbot
                    from bot.client import userbot_client
                    client = userbot_client
                    account_id_str = "default"
                else:
                    # 执行前检测代理健康，失效则自动替换
                    await self._account_manager.ensure_account_proxy(account_id)

                    # 新架构：使用 AccountManager
                    client = await self._account_manager.get_client(account_id)
                    account_id_str = account_id

                    if not client:
                        logger.error(f"无法获取账号客户端: {account_id}")
                        await self._handle_task_failure(session, task, "无法获取账号客户端")
                        return

                # 检查日期范围
                if task.start_at and now < task.start_at:
                    task.next_run_at = max(task.next_run_at or 0, task.start_at)
                    await session.commit()
                    logger.debug(f"任务 {task_id} 未到开始时间，next_run_at={task.next_run_at}")
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
                    last_message_id: Optional[int] = None
                    send_errors: list[str] = []
                    skip_delete_previous = len(target_specs) > 1

                    for spec in target_specs:
                        target_peer_id = int(spec["peer_id"])
                        target_peer_type = spec.get("peer_type")
                        target_access_hash = spec.get("access_hash")

                        try:
                            # 解析发送目标，优先使用资源表中的 peer_type/access_hash，避免误判为 PeerUser
                            send_target = await self._resolve_send_target(
                                client,
                                task,
                                target_peer_id,
                                target_peer_type=target_peer_type,
                                target_access_hash=target_access_hash
                            )

                            message_id = await self._send_with_protections(
                                client,
                                task,
                                send_target,
                                target_peer_id,
                                account_id_str,
                                skip_delete_previous=skip_delete_previous
                            )
                        except (FloodWaitError, PeerFloodError):
                            raise
                        except Exception as send_err:
                            send_errors.append(
                                f"peer={target_peer_id}: {type(send_err).__name__}: {send_err}"
                            )
                            logger.warning(
                                f"任务 {task_id} 发送目标失败: peer={target_peer_id}, "
                                f"error={type(send_err).__name__}: {send_err}"
                            )
                            continue

                        if message_id:
                            last_message_id = message_id
                        else:
                            send_errors.append(f"peer={target_peer_id}: send_message returned empty")

                    if last_message_id:
                        await self._handle_task_success(session, task, last_message_id, now)
                        if send_errors:
                            logger.warning(
                                f"任务 {task_id} 部分目标发送失败: {len(send_errors)} 个; "
                                f"错误示例: {send_errors[0]}"
                            )
                        logger.info(
                            f"任务 {task_id} 执行成功，目标数={len(target_specs)}，"
                            f"最后消息 ID: {last_message_id}"
                        )
                    else:
                        reason = send_errors[0] if send_errors else "发送失败"
                        await self._handle_task_failure(session, task, reason)

                except FloodWaitError as e:
                    if account_id_str == "default":
                        await self._handle_task_failure(session, task, f"FloodWait: {e.seconds}秒")
                        return

                    # FloodWait 错误处理
                    action = await self._circuit_breaker.handle_flood_wait(
                        account_id_str, e
                    )

                    if action == FloodWaitAction.BAN:
                        await self._handle_task_failure(session, task, f"FloodWait: {e.seconds}秒")

                        # 24h 以上：暂停该账号全部任务，避免持续触发风控
                        suspend_until = now + 24 * 3600
                        account = await self._account_manager.get_account(account_id_str)
                        if account and account.flood_until:
                            suspend_until = max(suspend_until, int(account.flood_until.timestamp()))
                        await self._suspend_account_tasks(
                            session,
                            account_id_str,
                            suspend_until,
                            reason=f"FloodWait({e.seconds}s)"
                        )
                    elif action == FloodWaitAction.SKIP:
                        # 跳过本次，稍后重试
                        await self._handle_task_failure(
                            session, task, f"FloodWait: {e.seconds}秒"
                        )

                except PeerFloodError:
                    # Telegram PeerFlood 风险：按账号级别熔断 24h
                    await self._handle_task_failure(session, task, "PeerFloodError")
                    if account_id_str != "default":
                        suspend_until_dt = await self._circuit_breaker.handle_peer_flood(account_id_str)
                        await self._suspend_account_tasks(
                            session,
                            account_id_str,
                            int(suspend_until_dt.timestamp()),
                            reason="PeerFloodError"
                        )

                except Exception as e:
                    logger.exception(f"执行任务 {task_id} 时出错: {type(e).__name__}: {e!r}")
                    await self._handle_task_failure(session, task, str(e))

        finally:
            # 清除处理标记
            await self.redis_client.delete(processing_key)

    def _collect_task_targets(self, task: ScheduledMessageTask) -> list[dict]:
        """从任务中提取目标列表，兼容新旧结构。"""
        targets: list[dict] = []

        raw_targets = getattr(task, "target_peers", None)
        if isinstance(raw_targets, list):
            for item in raw_targets:
                if not isinstance(item, dict):
                    continue
                try:
                    peer_id = int(item.get("peer_id"))
                except Exception:
                    continue
                peer_type = str(item.get("peer_type") or "").strip().lower()
                if peer_type not in {"user", "chat", "supergroup", "channel"}:
                    continue
                access_hash = item.get("access_hash")
                if access_hash not in (None, ""):
                    try:
                        access_hash = int(access_hash)
                    except Exception:
                        access_hash = None
                targets.append(
                    {
                        "peer_id": peer_id,
                        "peer_type": peer_type,
                        "access_hash": access_hash,
                    }
                )

        if not targets:
            target_peer_id = task.target_peer_id or task.chat_id
            if target_peer_id:
                fallback_peer_type = str(task.target_peer_type or "user").strip().lower()
                if fallback_peer_type not in {"user", "chat", "supergroup", "channel"}:
                    fallback_peer_type = "user"
                targets.append(
                    {
                        "peer_id": int(target_peer_id),
                        "peer_type": fallback_peer_type,
                        "access_hash": task.target_access_hash,
                    }
                )

        deduped: list[dict] = []
        seen = set()
        for target in targets:
            key = (target["peer_type"], target["peer_id"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(target)
        return deduped

    async def _resolve_send_target(
        self,
        client,
        task: ScheduledMessageTask,
        target_peer_id: int,
        target_peer_type: Optional[str] = None,
        target_access_hash: Optional[int] = None
    ):
        """
        解析可发送目标。
        优先使用资源表 InputPeer（含 access_hash），其次回退到 Telethon 输入实体，最后保留原始 peer_id。
        """
        peer_type = target_peer_type or task.target_peer_type
        access_hash = target_access_hash if target_access_hash is not None else task.target_access_hash

        if task.account_id and peer_type:
            try:
                input_peer = await self._resource_manager.get_input_peer(
                    account_id=task.account_id,
                    peer_id=target_peer_id,
                    peer_type=peer_type,
                    access_hash=access_hash
                )
                if input_peer is not None:
                    return input_peer
            except Exception as e:
                logger.warning(
                    f"任务 {task.task_id} 使用资源表解析目标失败，回退 get_input_entity: "
                    f"peer_id={target_peer_id}, peer_type={peer_type}, error={e}"
                )

        try:
            return await client.get_input_entity(target_peer_id)
        except Exception as e:
            logger.warning(f"任务 {task.task_id} get_input_entity 解析失败: peer_id={target_peer_id}, error={e}")

        # 兜底：从 dialogs 中回填实体（小群 Chat 常见缺 access_hash，但可直接使用 entity 发送）
        try:
            dialogs = await client.get_dialogs()
            for dialog in dialogs:
                entity = dialog.entity
                if getattr(entity, "id", None) == target_peer_id:
                    return entity
        except Exception as e:
            logger.warning(f"任务 {task.task_id} 从 dialogs 回填实体失败: peer_id={target_peer_id}, error={e}")

        # 最后回退为原始 peer_id；失败会在发送处记录明确错误
        return target_peer_id

    async def _send_with_protections(
        self,
        client,
        task: ScheduledMessageTask,
        send_target,
        lock_peer_id: int,
        account_id: str,
        skip_delete_previous: bool = False
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
        await rate_limiter.wait_for_slot(account_id, lock_peer_id)

        # 兼容旧数据：default userbot 不参与账号熔断器
        if account_id == "default":
            return await self._do_send_message(
                client,
                task,
                send_target,
                skip_delete_previous=skip_delete_previous
            )

        # 使用熔断器包装发送
        return await circuit_breaker.execute_with_circuit_breaker(
            account_id,
            self._do_send_message,
            client, task, send_target, skip_delete_previous
        )

    async def _do_send_message(
        self,
        client,
        task: ScheduledMessageTask,
        send_target,
        skip_delete_previous: bool = False
    ) -> Optional[int]:
        """
        实际发送消息

        Args:
            client: TelegramClient
            task: 任务对象
            send_target: 目标 Peer（InputPeer 或 peer_id）

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

        def _is_button_markup_error(error: Exception) -> bool:
            message = str(error).lower()
            keywords = (
                "button",
                "reply markup",
                "reply_markup",
                "keyboard",
                "inline",
                "url invalid",
                "bot"
            )
            return any(key in message for key in keywords)

        async def _send_with_buttons(send_buttons):
            # 发送消息
            if task.media_type != MediaType.NONE:
                if not task.media_file_id:
                    raise ValueError("媒体任务缺少 media_file_id")
                if os.path.isabs(task.media_file_id) and not os.path.exists(task.media_file_id):
                    raise FileNotFoundError(f"媒体文件不存在: {task.media_file_id}")

                # 带媒体的消息
                if task.media_type == MediaType.PHOTO:
                    return await client.send_file(
                        send_target,
                        file=task.media_file_id,
                        caption=text,
                        buttons=send_buttons,
                        parse_mode='html'
                    )
                if task.media_type == MediaType.VIDEO:
                    return await client.send_file(
                        send_target,
                        file=task.media_file_id,
                        caption=text,
                        buttons=send_buttons,
                        parse_mode='html'
                    )
                if task.media_type == MediaType.ANIMATION:
                    return await client.send_file(
                        send_target,
                        file=task.media_file_id,
                        caption=text,
                        buttons=send_buttons,
                        parse_mode='html'
                    )
                if task.media_type == MediaType.STICKER:
                    return await client.send_file(
                        send_target,
                        file=task.media_file_id,
                        buttons=send_buttons
                    )

                raise ValueError(f"不支持的媒体类型: {task.media_type}")

            # 纯文本消息
            return await client.send_message(
                send_target,
                text,
                buttons=send_buttons,
                parse_mode='html'
            )

        # 发送消息
        # 需要先删除上一条时，先尝试清理历史消息
        if (not skip_delete_previous) and task.delete_previous and task.last_sent_message_id:
            try:
                await client.delete_messages(send_target, [task.last_sent_message_id])
            except Exception as e:
                logger.warning(f"删除上一条消息失败 task={task.task_id}: {e}")

        try:
            msg = await _send_with_buttons(buttons)
        except Exception as e:
            if buttons and _is_button_markup_error(e):
                logger.warning(
                    f"任务 {task.task_id} 按钮发送失败，自动降级为无按钮消息: {e}"
                )
                msg = await _send_with_buttons(None)
            else:
                raise

        # 发送成功后按配置置顶
        if msg and task.pin_message:
            try:
                await client.pin_message(send_target, msg.id, notify=False)
            except Exception as e:
                logger.warning(f"置顶消息失败 task={task.task_id}: {e}")

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

        # 失败后推进下次运行时间，避免连续即时重试
        now = int(datetime.now().timestamp())
        retry_after = max(30, task.repeat_interval_min * 60)
        task.next_run_at = now + retry_after

        # 连续失败多次，自动禁用
        if task.failure_count >= settings.max_failure_count:
            task.enabled = False
            logger.warning(
                f"任务 {task.task_id} 连续失败 {task.failure_count} 次，"
                f"自动禁用"
            )

        await session.commit()

    async def _suspend_account_tasks(
        self,
        session,
        account_id: str,
        suspend_until: int,
        reason: str
    ):
        """暂停账号下全部启用任务到指定时间。"""
        from sqlalchemy import select

        result = await session.execute(
            select(ScheduledMessageTask).where(
                ScheduledMessageTask.account_id == account_id,
                ScheduledMessageTask.enabled == True
            )
        )
        tasks = result.scalars().all()

        for t in tasks:
            t.next_run_at = max(t.next_run_at or 0, suspend_until)

        await session.commit()
        logger.warning(
            f"账号 {account_id} 任务已暂停到 {suspend_until}，原因: {reason}，影响任务数: {len(tasks)}"
        )

    def _calculate_next_run(self, now: int, target_hour: int, interval_min: int) -> int:
        """计算下一次运行时间"""
        # 简化计算，直接加上间隔
        return now + interval_min * 60


# 全局调度器实例
scheduler = TaskScheduler()
