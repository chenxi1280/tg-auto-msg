"""调度器 Worker：编排扫描、入队、执行与任务状态流转。"""
import asyncio
from datetime import datetime
from typing import Optional

import redis.asyncio as redis
from loguru import logger
from telethon.errors import FloodWaitError, PeerFloodError

from backend.bot.account.manager import get_account_manager
from backend.config.core.settings import settings
from backend.database.schema.models import ScheduledMessageTask
from backend.database.runtime.session import get_async_session
from backend.h5_backend.services.licensing.service import (
    disable_tasks_for_account_if_unlicensed,
    get_account_authorization_summary,
)
from backend.bot.circuit.breaker import get_circuit_breaker, FloodWaitAction
from backend.bot.resources.manager import get_resource_manager
from backend.scheduler.core.queue_ops import (
    enqueue_due_tasks as _enqueue_due_tasks,
    ensure_redis_connection as _ensure_redis_connection,
    get_pending_tasks as _get_pending_tasks,
)
from backend.scheduler.core.task_execution import (
    collect_task_targets as _collect_task_targets,
    count_configured_task_targets as _count_configured_task_targets,
    get_target_last_message_id as _get_target_last_message_id,
    resolve_send_target as _resolve_send_target,
    send_with_protections as _send_with_protections,
)
from backend.scheduler.core.task_issue_classifier import classify_task_send_error
from backend.scheduler.core.task_issue_state import (
    record_task_target_send_issue as _record_task_target_send_issue,
    resolve_task_target_send_issue as _resolve_task_target_send_issue,
    update_task_target_failure_metadata as _update_task_target_failure_metadata,
    update_task_target_success_metadata as _update_task_target_success_metadata,
)
from backend.scheduler.core.task_lifecycle import (
    check_time_limit as _check_time_limit,
    handle_task_failure as _handle_task_failure,
    handle_task_success as _handle_task_success,
    suspend_account_tasks as _suspend_account_tasks,
)


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
        self._resource_manager = get_resource_manager()
        self._circuit_breaker = get_circuit_breaker()

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

                if task.account_id:
                    auth_summary = await get_account_authorization_summary(task.account_id, session=session)
                    if not auth_summary.can_create_tasks:
                        disabled_count = await disable_tasks_for_account_if_unlicensed(
                            account_id=task.account_id,
                            session=session,
                        )
                        logger.warning(
                            "任务 {} 对应账号已无有效授权，已停用该账号下任务 {} 条",
                            task_id,
                            disabled_count,
                        )
                        return

                if task.next_run_at is None:
                    start_at_ts = int(task.start_at or 0)
                    task.next_run_at = max(now, start_at_ts) if start_at_ts > 0 else now
                    await session.commit()

                if task.next_run_at and task.next_run_at > now:
                    await self.redis_client.zadd(self.TASK_QUEUE_KEY, {task.task_id: int(task.next_run_at)})
                    logger.debug(
                        f"任务 {task_id} 队列中存在旧调度，已按数据库 next_run_at={task.next_run_at} 重新入队"
                    )
                    return

                # 检查账号（新架构）
                account_id = task.account_id

                # 收集目标列表（兼容旧结构的单目标）
                target_specs = _collect_task_targets(task)
                if not target_specs:
                    configured_target_count = _count_configured_task_targets(task)
                    if configured_target_count > 0:
                        task.next_run_at = now + task.repeat_interval_min * 60
                        await session.commit()
                        logger.info(
                            "任务 {} 当前没有可发送目标，已跳过本轮执行（全部目标可能已被系统暂停）",
                            task_id,
                        )
                    else:
                        logger.warning(f"任务 {task_id} 没有目标 Peer ID")
                        await _handle_task_failure(
                            session=session,
                            task=task,
                            error_message="缺少目标 Peer ID",
                            max_failure_count=settings.max_failure_count,
                        )
                    return

                # 获取执行账号
                if not account_id:
                    # 兼容旧数据：使用默认 Userbot
                    from backend.bot.client_runtime.manager import userbot_client
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
                        await _handle_task_failure(
                            session=session,
                            task=task,
                            error_message="无法获取账号客户端",
                            max_failure_count=settings.max_failure_count,
                        )
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
                allowed, next_run_at = _check_time_limit(task, current_hour, now)
                if not allowed:
                    if next_run_at is not None:
                        task.next_run_at = next_run_at
                        await session.commit()
                    return

                # 使用速率限制器和熔断器执行发送
                try:
                    last_message_id: Optional[int] = None
                    send_errors: list[str] = []
                    partial_failure_summaries: list[str] = []
                    target_message_ids: dict[tuple[str, int], int] = {}

                    for spec in target_specs:
                        target_peer_id = int(spec["peer_id"])
                        target_peer_type = spec.get("peer_type")
                        target_access_hash = spec.get("access_hash")
                        target_title = spec.get("title")
                        normalized_target_peer_type = str(
                            target_peer_type or task.target_peer_type or "user"
                        ).strip().lower()
                        target_label = target_title or f"{normalized_target_peer_type}:{target_peer_id}"
                        previous_message_id = _get_target_last_message_id(
                            task,
                            target_peer_id=target_peer_id,
                            target_peer_type=target_peer_type,
                        )

                        try:
                            # 解析发送目标，优先使用资源表中的 peer_type/access_hash，避免误判为 PeerUser
                            send_target = await _resolve_send_target(
                                client=client,
                                task=task,
                                target_peer_id=target_peer_id,
                                target_peer_type=target_peer_type,
                                target_access_hash=target_access_hash,
                                resource_manager=self._resource_manager,
                            )

                            message_id = await _send_with_protections(
                                client=client,
                                task=task,
                                send_target=send_target,
                                lock_peer_id=target_peer_id,
                                account_id=account_id_str,
                                previous_message_id=previous_message_id,
                                media_ref_prefix=self.TELEGRAM_MEDIA_REF_PREFIX,
                            )
                        except (FloodWaitError, PeerFloodError):
                            raise
                        except Exception as send_err:
                            classification = classify_task_send_error(send_err)
                            send_errors.append(
                                f"peer={target_peer_id}: {type(send_err).__name__}: {send_err}"
                            )
                            partial_failure_summaries.append(
                                f"{target_label}: {classification.user_message}"
                            )
                            await _record_task_target_send_issue(
                                session=session,
                                task=task,
                                peer_id=target_peer_id,
                                peer_type=normalized_target_peer_type,
                                peer_title=str(target_title).strip() if target_title else None,
                                classification=classification,
                            )
                            _update_task_target_failure_metadata(
                                task,
                                peer_id=target_peer_id,
                                peer_type=normalized_target_peer_type,
                                peer_title=str(target_title).strip() if target_title else None,
                                error_type=classification.error_type,
                                error_message=classification.user_message,
                                suspension_reason=classification.suspension_reason,
                            )
                            logger.warning(
                                f"任务 {task_id} 发送目标失败: peer={target_peer_id}, "
                                f"error={type(send_err).__name__}: {send_err}"
                            )
                            continue

                        if message_id:
                            await _resolve_task_target_send_issue(
                                session=session,
                                task=task,
                                peer_id=target_peer_id,
                                peer_type=normalized_target_peer_type,
                            )
                            _update_task_target_success_metadata(
                                task,
                                peer_id=target_peer_id,
                                peer_type=normalized_target_peer_type,
                            )
                            last_message_id = message_id
                            key = (normalized_target_peer_type, target_peer_id)
                            target_message_ids[key] = message_id
                        else:
                            send_errors.append(f"peer={target_peer_id}: send_message returned empty")
                            empty_result_error = RuntimeError("send_message returned empty")
                            classification = classify_task_send_error(empty_result_error)
                            partial_failure_summaries.append(
                                f"{target_label}: {classification.user_message}"
                            )
                            await _record_task_target_send_issue(
                                session=session,
                                task=task,
                                peer_id=target_peer_id,
                                peer_type=normalized_target_peer_type,
                                peer_title=str(target_title).strip() if target_title else None,
                                classification=classification,
                            )
                            _update_task_target_failure_metadata(
                                task,
                                peer_id=target_peer_id,
                                peer_type=normalized_target_peer_type,
                                peer_title=str(target_title).strip() if target_title else None,
                                error_type=classification.error_type,
                                error_message=classification.user_message,
                                suspension_reason=classification.suspension_reason,
                            )

                    if last_message_id:
                        partial_failure_summary = None
                        if send_errors:
                            partial_failure_summary = (
                                f"部分目标发送失败，共 {len(send_errors)} 个；"
                                f"示例：{partial_failure_summaries[0]}"
                            )
                        await _handle_task_success(
                            session=session,
                            task=task,
                            message_id=last_message_id,
                            target_message_ids=target_message_ids,
                            error_message=partial_failure_summary,
                            now=now,
                            account_manager=self._account_manager,
                        )
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
                        if partial_failure_summaries:
                            reason = (
                                f"目标发送全部失败，共 {len(send_errors)} 个；"
                                f"示例：{partial_failure_summaries[0]}"
                            )
                        await _handle_task_failure(
                            session=session,
                            task=task,
                            error_message=reason,
                            max_failure_count=settings.max_failure_count,
                        )

                except FloodWaitError as e:
                    if account_id_str == "default":
                        await _handle_task_failure(
                            session=session,
                            task=task,
                            error_message=f"FloodWait: {e.seconds}秒",
                            max_failure_count=settings.max_failure_count,
                        )
                        return

                    # FloodWait 错误处理
                    action = await self._circuit_breaker.handle_flood_wait(
                        account_id_str, e
                    )

                    if action == FloodWaitAction.BAN:
                        await _handle_task_failure(
                            session=session,
                            task=task,
                            error_message=f"FloodWait: {e.seconds}秒",
                            max_failure_count=settings.max_failure_count,
                        )

                        # 24h 以上：暂停该账号全部任务，避免持续触发风控
                        suspend_until = now + 24 * 3600
                        account = await self._account_manager.get_account(account_id_str)
                        if account and account.flood_until:
                            suspend_until = max(suspend_until, int(account.flood_until.timestamp()))
                        await _suspend_account_tasks(
                            session=session,
                            account_id=account_id_str,
                            suspend_until=suspend_until,
                            reason=f"FloodWait({e.seconds}s)",
                        )
                    elif action == FloodWaitAction.SKIP:
                        # 跳过本次，稍后重试
                        await _handle_task_failure(
                            session=session,
                            task=task,
                            error_message=f"FloodWait: {e.seconds}秒",
                            max_failure_count=settings.max_failure_count,
                        )

                except PeerFloodError:
                    # Telegram PeerFlood 风险：按账号级别熔断 24h
                    await _handle_task_failure(
                        session=session,
                        task=task,
                        error_message="PeerFloodError",
                        max_failure_count=settings.max_failure_count,
                    )
                    if account_id_str != "default":
                        suspend_until_dt = await self._circuit_breaker.handle_peer_flood(account_id_str)
                        await _suspend_account_tasks(
                            session=session,
                            account_id=account_id_str,
                            suspend_until=int(suspend_until_dt.timestamp()),
                            reason="PeerFloodError",
                        )

                except Exception as e:
                    logger.exception(f"执行任务 {task_id} 时出错: {type(e).__name__}: {e!r}")
                    await _handle_task_failure(
                        session=session,
                        task=task,
                        error_message=str(e),
                        max_failure_count=settings.max_failure_count,
                    )

        finally:
            # 清除处理标记
            await self.redis_client.delete(processing_key)

# 全局调度器实例
scheduler = TaskScheduler()
