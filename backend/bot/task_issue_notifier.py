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
from backend.database.schema.models import AppSetting, Account, Resource, ScheduledMessageTask, TaskTargetSendIssue

USER_LINK_KEY_PREFIX = "tg_user_link:"
_REAL_DATETIME = datetime


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
        all_issues = active_issues + resolved_issues
        account_labels = await self._load_account_labels(
            [issue.account_id for issue in all_issues if issue.account_id]
        )
        peer_labels = await self._load_peer_labels(all_issues)

        sent_count = 0
        sent_count += await self._send_active_issue_notifications(
            issues=active_issues,
            user_links=user_links,
            task_titles=task_titles,
            account_labels=account_labels,
            peer_labels=peer_labels,
            now=now,
        )
        sent_count += await self._send_recovery_notifications(
            issues=resolved_issues,
            user_links=user_links,
            task_titles=task_titles,
            account_labels=account_labels,
            peer_labels=peer_labels,
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

    async def _load_account_labels(self, account_ids: Iterable[str | None]) -> dict[str, str]:
        normalized_account_ids = sorted({str(account_id) for account_id in account_ids if account_id})
        if not normalized_account_ids:
            return {}

        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(Account.account_id, Account.username, Account.first_name, Account.phone).where(
                        Account.account_id.in_(normalized_account_ids)
                    )
                )
            ).all()

        labels: dict[str, str] = {}
        for account_id, username, first_name, phone in rows:
            label = self._format_account_label(
                username=str(username or "").strip(),
                first_name=str(first_name or "").strip(),
                phone=str(phone or "").strip(),
            )
            labels[str(account_id)] = label
        return labels

    async def _load_peer_labels(self, issues: list[TaskTargetSendIssue]) -> dict[tuple[str, int], str]:
        account_ids = sorted({str(issue.account_id) for issue in issues if issue.account_id})
        peer_ids = sorted({int(issue.peer_id) for issue in issues if issue.peer_id is not None})
        if not account_ids or not peer_ids:
            return {}

        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(Resource.account_id, Resource.peer_id, Resource.title, Resource.username).where(
                        Resource.account_id.in_(account_ids),
                        Resource.peer_id.in_(peer_ids),
                    )
                )
            ).all()

        labels: dict[tuple[str, int], str] = {}
        for account_id, peer_id, title, username in rows:
            label = str(title or "").strip()
            username_label = str(username or "").strip()
            if not label and username_label:
                label = username_label if username_label.startswith("@") else f"@{username_label}"
            if label:
                labels[(str(account_id), int(peer_id))] = label
        return labels

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
        account_labels: dict[str, str],
        peer_labels: dict[tuple[str, int], str],
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
                        account_label=self._resolve_account_label(account_id, account_labels),
                        peer_labels=peer_labels,
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
        account_labels: dict[str, str],
        peer_labels: dict[tuple[str, int], str],
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
                        account_label=self._resolve_account_label(account_id, account_labels),
                        peer_labels=peer_labels,
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
        account_label: str,
        peer_labels: dict[tuple[str, int], str],
        issues: list[TaskTargetSendIssue],
    ) -> str:
        lines = [
            "任务发送异常提醒",
            "",
            f"任务：{task_title}",
            f"执行账号：{account_label}",
            f"发现时间：{self._format_issue_time(issues, field_name='last_seen_at')}",
            f"本次异常目标：{len(issues)} 个",
            "",
        ]
        for issue in issues[:10]:
            peer_label = self._resolve_peer_label(issue, peer_labels)
            reason = self._format_issue_reason(issue)
            suffix = "（系统已暂停该目标）" if issue.auto_suspended else ""
            lines.append(f"- {peer_label}：{reason}{suffix}")
        if len(issues) > 10:
            lines.append(f"- 其余 {len(issues) - 10} 个目标请到任务详情查看")
        lines.extend(["", "系统已暂停无权限或无法访问的目标，其他目标会继续发送。", "同类重复问题 24 小时内不重复提醒。"])
        return "\n".join(lines)

    def _build_recovery_notice_text(
        self,
        *,
        task_title: str,
        account_label: str,
        peer_labels: dict[tuple[str, int], str],
        issues: list[TaskTargetSendIssue],
    ) -> str:
        lines = [
            "任务目标已恢复",
            "",
            f"任务：{task_title}",
            f"执行账号：{account_label}",
            f"恢复时间：{self._format_issue_time(issues, field_name='resolved_at')}",
            "以下目标已恢复发送：",
        ]
        for issue in issues[:10]:
            peer_label = self._resolve_peer_label(issue, peer_labels)
            lines.append(f"- {peer_label}")
        if len(issues) > 10:
            lines.append(f"- 其余 {len(issues) - 10} 个目标已恢复")
        return "\n".join(lines)

    @staticmethod
    def _format_account_label(*, username: str, first_name: str, phone: str) -> str:
        if username:
            return username if username.startswith("@") else f"@{username}"
        if first_name:
            return first_name
        if phone:
            return phone
        return "未同步名称的执行账号"

    @staticmethod
    def _resolve_account_label(account_id: str | None, account_labels: dict[str, str]) -> str:
        if not account_id:
            return "未绑定执行账号"
        return account_labels.get(str(account_id)) or "未同步名称的执行账号"

    @staticmethod
    def _peer_type_label(peer_type: str | None) -> str:
        normalized = str(peer_type or "").strip().lower()
        if normalized == "channel":
            return "频道"
        if normalized in {"chat", "supergroup"}:
            return "群聊"
        if normalized == "user":
            return "用户"
        return "目标"

    def _resolve_peer_label(
        self,
        issue: TaskTargetSendIssue,
        peer_labels: dict[tuple[str, int], str],
    ) -> str:
        issue_title = str(issue.peer_title or "").strip()
        if issue_title:
            return issue_title
        if issue.account_id:
            label = peer_labels.get((str(issue.account_id), int(issue.peer_id)))
            if label:
                return label
        return f"未同步名称的{self._peer_type_label(issue.peer_type)}（请到任务详情查看）"

    @staticmethod
    def _format_issue_time(issues: list[TaskTargetSendIssue], *, field_name: str) -> str:
        values = [
            value
            for value in (getattr(issue, field_name, None) for issue in issues)
            if isinstance(value, _REAL_DATETIME)
        ]
        if not values:
            return _REAL_DATETIME.now().strftime("%Y-%m-%d %H:%M")
        return max(values).strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _format_issue_reason(issue: TaskTargetSendIssue) -> str:
        error_type = str(issue.current_error_type or "").strip()
        if error_type == "UserBannedInChannelError":
            return "当前账号在这个群聊或频道里没有发送权限，可能被禁言、被移出，或被管理员限制发言。"
        if error_type == "ChannelPrivateError":
            return "当前账号无法访问这个群聊或频道，可能频道已设为私有、账号未加入，或已被移出。"
        message = str(issue.current_error_message or "").strip()
        for token in (
            "（UserBannedInChannelError）",
            "(UserBannedInChannelError)",
            "（ChannelPrivateError）",
            "(ChannelPrivateError)",
        ):
            message = message.replace(token, "")
        return message or "发送失败，系统会稍后再试。"

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
