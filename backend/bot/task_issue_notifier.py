"""Aggregated manager-bot reminders for task target send issues."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable

from loguru import logger
from sqlalchemy import and_, or_, select

from backend.bot.client_runtime.manager import bot_client, ensure_manager_bot_ready
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import AppSetting, ScheduledMessageTask, TaskTargetSendIssue

USER_LINK_KEY_PREFIX = "tg_user_link:"


class TaskIssueNotifier:
    """Background notifier for aggregated task target send issues."""

    CHECK_INTERVAL_SECONDS = 300
    MUTE_HOURS = 24
    RECENT_WINDOW_MINUTES = 10

    def __init__(self) -> None:
        self.running = False

    async def start(self) -> None:
        self.running = True
        logger.info("任务发送异常提醒任务已启动")
        while self.running:
            try:
                await self.scan_once()
            except Exception as exc:
                logger.exception(f"任务发送异常提醒扫描失败: {type(exc).__name__}: {exc!r}")
            await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self.running = False
        logger.info("任务发送异常提醒任务已停止")

    async def scan_once(self) -> int:
        now = datetime.now()
        active_issues = await self._list_pending_active_issues(now)
        resolved_issues = await self._list_pending_recovery_issues()
        if not active_issues and not resolved_issues:
            return 0
        if not await ensure_manager_bot_ready():
            logger.warning("Manager Bot 当前未就绪，跳过本轮任务异常提醒发送")
            return 0

        user_links = await self._load_user_links()
        task_titles = await self._load_task_titles(
            [issue.task_id for issue in active_issues] + [issue.task_id for issue in resolved_issues]
        )

        sent_count = 0
        sent_count += await self._send_active_issue_notifications(
            issues=active_issues,
            user_links=user_links,
            task_titles=task_titles,
            now=now,
        )
        sent_count += await self._send_recovery_notifications(
            issues=resolved_issues,
            user_links=user_links,
            task_titles=task_titles,
            now=now,
        )
        return sent_count

    async def _load_user_links(self) -> dict[int, int]:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(AppSetting.key, AppSetting.value).where(
                        AppSetting.key.like(f"{USER_LINK_KEY_PREFIX}%")
                    )
                )
            ).all()

        user_links: dict[int, int] = {}
        for key, value in rows:
            try:
                tg_user_id = int(str(key).split(USER_LINK_KEY_PREFIX, 1)[1])
                user_id = int(str(value).strip())
            except Exception:
                continue
            user_links[user_id] = tg_user_id
        return user_links

    async def _load_task_titles(self, task_ids: Iterable[str]) -> dict[str, str]:
        normalized_task_ids = sorted({str(task_id) for task_id in task_ids if task_id})
        if not normalized_task_ids:
            return {}

        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(ScheduledMessageTask.task_id, ScheduledMessageTask.title).where(
                        ScheduledMessageTask.task_id.in_(normalized_task_ids)
                    )
                )
            ).all()

        return {str(task_id): str(title or "").strip() for task_id, title in rows}

    async def _list_pending_active_issues(self, now: datetime) -> list[TaskTargetSendIssue]:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(TaskTargetSendIssue)
                    .where(TaskTargetSendIssue.status == "active")
                    .order_by(
                        TaskTargetSendIssue.user_id.asc(),
                        TaskTargetSendIssue.task_id.asc(),
                        TaskTargetSendIssue.account_id.asc(),
                        TaskTargetSendIssue.first_seen_at.asc(),
                    )
                )
            ).scalars().all()
        return [row for row in rows if self._is_active_issue_ready(row, now)]

    async def _list_pending_recovery_issues(self) -> list[TaskTargetSendIssue]:
        now = datetime.now()
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(TaskTargetSendIssue)
                    .where(TaskTargetSendIssue.status == "resolved")
                    .order_by(
                        TaskTargetSendIssue.user_id.asc(),
                        TaskTargetSendIssue.task_id.asc(),
                        TaskTargetSendIssue.account_id.asc(),
                        TaskTargetSendIssue.resolved_at.asc(),
                    )
                )
            ).scalars().all()
        return [row for row in rows if self._is_recovery_issue_ready(row, now)]

    def _is_active_issue_ready(self, issue: TaskTargetSendIssue, now: datetime) -> bool:
        recent_cutoff = now - timedelta(minutes=self.RECENT_WINDOW_MINUTES)
        last_seen_at = getattr(issue, "last_seen_at", None)
        if last_seen_at is None or last_seen_at < recent_cutoff:
            return False
        last_notified_at = getattr(issue, "last_notified_at", None)
        if last_notified_at is None:
            return True
        muted_until = getattr(issue, "muted_until", None)
        return muted_until is not None and muted_until <= now

    def _is_recovery_issue_ready(self, issue: TaskTargetSendIssue, now: datetime) -> bool:
        if getattr(issue, "recovered_notified_at", None) is not None:
            return False
        resolved_at = getattr(issue, "resolved_at", None)
        if resolved_at is None:
            return False
        recent_cutoff = now - timedelta(minutes=self.RECENT_WINDOW_MINUTES)
        return resolved_at >= recent_cutoff

    async def _send_active_issue_notifications(
        self,
        *,
        issues: list[TaskTargetSendIssue],
        user_links: dict[int, int],
        task_titles: dict[str, str],
        now: datetime,
    ) -> int:
        grouped = self._group_issues(issues)
        sent = 0
        for group_key, group_issues in grouped.items():
            user_id, task_id, account_id = group_key
            tg_user_id = user_links.get(int(user_id))
            if tg_user_id is None:
                logger.info(
                    "跳过任务发送异常提醒，用户尚未建立 Bot 绑定: user_id={}, task_id={}",
                    user_id,
                    task_id,
                )
                continue

            try:
                await bot_client.send_message(
                    tg_user_id,
                    self._build_active_notice_text(
                        task_title=task_titles.get(str(task_id)) or str(task_id),
                        account_id=account_id,
                        issues=group_issues,
                    ),
                )
                await self._mark_active_notified(group_issues, now)
                sent += 1
            except Exception as exc:
                logger.error(
                    "发送任务发送异常提醒失败: user_id={}, tg_user_id={}, task_id={}, error={}",
                    user_id,
                    tg_user_id,
                    task_id,
                    exc,
                )
        return sent

    async def _send_recovery_notifications(
        self,
        *,
        issues: list[TaskTargetSendIssue],
        user_links: dict[int, int],
        task_titles: dict[str, str],
        now: datetime,
    ) -> int:
        grouped = self._group_issues(issues)
        sent = 0
        for group_key, group_issues in grouped.items():
            user_id, task_id, account_id = group_key
            tg_user_id = user_links.get(int(user_id))
            if tg_user_id is None:
                continue

            try:
                await bot_client.send_message(
                    tg_user_id,
                    self._build_recovery_notice_text(
                        task_title=task_titles.get(str(task_id)) or str(task_id),
                        account_id=account_id,
                        issues=group_issues,
                    ),
                )
                await self._mark_recovery_notified(group_issues, now)
                sent += 1
            except Exception as exc:
                logger.error(
                    "发送任务恢复提醒失败: user_id={}, tg_user_id={}, task_id={}, error={}",
                    user_id,
                    tg_user_id,
                    task_id,
                    exc,
                )
        return sent

    def _group_issues(
        self,
        issues: list[TaskTargetSendIssue],
    ) -> dict[tuple[int, str, str | None], list[TaskTargetSendIssue]]:
        grouped: dict[tuple[int, str, str | None], list[TaskTargetSendIssue]] = defaultdict(list)
        for issue in issues:
            grouped[(int(issue.user_id), str(issue.task_id), str(issue.account_id) if issue.account_id else None)].append(issue)
        return grouped

    def _build_active_notice_text(
        self,
        *,
        task_title: str,
        account_id: str | None,
        issues: list[TaskTargetSendIssue],
    ) -> str:
        lines = [
            "任务发送异常提醒",
            "",
            f"任务：{task_title}",
            f"执行账号：{account_id or '未绑定'}",
            f"本次新增异常目标：{len(issues)} 个",
            "",
        ]
        for issue in issues[:10]:
            peer_label = str(issue.peer_title or "").strip() or f"{issue.peer_type}:{issue.peer_id}"
            suffix = "（系统已暂停该目标）" if issue.auto_suspended else ""
            lines.append(f"- {peer_label}：{issue.current_error_message}{suffix}")
        if len(issues) > 10:
            lines.append(f"- 其余 {len(issues) - 10} 个目标请到任务详情查看")
        lines.extend(["", "同类重复问题 24 小时内静默。"])
        return "\n".join(lines)

    def _build_recovery_notice_text(
        self,
        *,
        task_title: str,
        account_id: str | None,
        issues: list[TaskTargetSendIssue],
    ) -> str:
        lines = [
            "任务目标已恢复",
            "",
            f"任务：{task_title}",
            f"执行账号：{account_id or '未绑定'}",
            "以下目标已恢复发送：",
        ]
        for issue in issues[:10]:
            peer_label = str(issue.peer_title or "").strip() or f"{issue.peer_type}:{issue.peer_id}"
            lines.append(f"- {peer_label}")
        if len(issues) > 10:
            lines.append(f"- 其余 {len(issues) - 10} 个目标已恢复")
        return "\n".join(lines)

    async def _mark_active_notified(self, issues: list[TaskTargetSendIssue], now: datetime) -> None:
        muted_until = now + timedelta(hours=self.MUTE_HOURS)
        issue_ids = [int(issue.id) for issue in issues]
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(TaskTargetSendIssue).where(TaskTargetSendIssue.id.in_(issue_ids))
                )
            ).scalars().all()
            for row in rows:
                row.last_notified_at = now
                row.muted_until = muted_until

    async def _mark_recovery_notified(self, issues: list[TaskTargetSendIssue], now: datetime) -> None:
        issue_ids = [int(issue.id) for issue in issues]
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(TaskTargetSendIssue).where(TaskTargetSendIssue.id.in_(issue_ids))
                )
            ).scalars().all()
            for row in rows:
                row.recovered_notified_at = now


task_issue_notifier = TaskIssueNotifier()
