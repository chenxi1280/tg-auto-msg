"""Reauth-required account reminders."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import func, select
from telethon import Button
from telethon.errors import (
    ChatWriteForbiddenError,
    InputUserDeactivatedError,
    PeerIdInvalidError,
    UserIsBlockedError,
)

from backend.bot.account.reauth import is_reauth_required_account
from backend.bot.account.proxy_observation import SING_BOX_PROXY_REGIONS
from backend.bot.client_runtime.manager import bot_client, ensure_manager_bot_ready
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    Account,
    AppSetting,
    HealthStatus,
    ScheduledMessageTask,
    UserAuthorization,
)

REAUTH_NOTICE_KEY_PREFIX = "reauth_notice:"
REAUTH_REMINDER_REASONS = {"session_unauthorized"}
MAX_NOTICE_SENDS = 3


@dataclass(frozen=True)
class ReauthNoticeItem:
    account_id: str
    user_id: int
    tg_user_id: int
    account_label: str
    disabled_task_count: int
    authorization_end_at: Optional[datetime]
    reason: str


@dataclass(frozen=True)
class ReauthTransitionResult:
    account_id: str
    user_id: Optional[int]
    was_reauth_required: bool
    disabled_task_count: int
    authorization_end_at: Optional[datetime]
    notice_sent: bool


def _notice_key(account_id: str) -> str:
    return f"{REAUTH_NOTICE_KEY_PREFIX}{str(account_id)}"


def _today_key(now: Optional[datetime] = None) -> str:
    return (now or datetime.now()).date().isoformat()


def _empty_notice_state() -> dict[str, object]:
    return {
        "count": 0,
        "first_sent_date": None,
        "last_sent_date": None,
    }


def _parse_notice_state(value: str | None) -> dict[str, object]:
    raw = str(value or "").strip()
    state = _empty_notice_state()
    if not raw:
        return state

    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            try:
                state["count"] = max(0, int(parsed.get("count") or 0))
            except Exception:
                state["count"] = 0
            state["first_sent_date"] = parsed.get("first_sent_date") or None
            state["last_sent_date"] = parsed.get("last_sent_date") or None
            return state

    # Backward compatibility with the old value format: "YYYY-MM-DD".
    state["count"] = 1
    state["first_sent_date"] = raw
    state["last_sent_date"] = raw
    return state


def _serialize_notice_state(state: dict[str, object]) -> str:
    return json.dumps(
        {
            "count": int(state.get("count") or 0),
            "first_sent_date": state.get("first_sent_date") or None,
            "last_sent_date": state.get("last_sent_date") or None,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _notice_state_due(state: dict[str, object], *, now: datetime) -> bool:
    if int(state.get("count") or 0) >= MAX_NOTICE_SENDS:
        return False
    if str(state.get("last_sent_date") or "").strip() == _today_key(now):
        return False
    return True


def _format_account_label(account: Account) -> str:
    username = str(getattr(account, "username", "") or "").strip()
    if username:
        return username if username.startswith("@") else f"@{username}"
    phone = str(getattr(account, "phone", "") or "").strip()
    if phone:
        return phone
    return str(getattr(account, "account_id", "") or "当前账号")


def _format_end_at(end_at: Optional[datetime]) -> str:
    if end_at is None:
        return "-"
    return end_at.strftime("%Y-%m-%d %H:%M")


def _classify_delivery_exception(exc: Exception) -> str:
    if isinstance(exc, UserIsBlockedError):
        return "blocked"
    if isinstance(exc, InputUserDeactivatedError):
        return "deactivated"
    if isinstance(exc, (PeerIdInvalidError, ChatWriteForbiddenError)):
        return "unreachable"
    return "failed"


async def _load_active_authorization_end_at(session, account_id: str, now: datetime) -> Optional[datetime]:
    authorization = (
        await session.execute(
            select(UserAuthorization)
            .where(
                UserAuthorization.current_account_id == str(account_id),
                UserAuthorization.status == "active",
                UserAuthorization.end_at > now,
            )
            .order_by(UserAuthorization.end_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return authorization.end_at if authorization is not None else None


async def _load_latest_authorization_end_at(session, account_id: str) -> Optional[datetime]:
    authorization = (
        await session.execute(
            select(UserAuthorization)
            .where(UserAuthorization.current_account_id == str(account_id))
            .order_by(UserAuthorization.end_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return authorization.end_at if authorization is not None else None


async def _load_user_links(session) -> dict[int, int]:
    from backend.bot.handlers.core.user_link import load_latest_linked_tg_user_ids

    return await load_latest_linked_tg_user_ids(session)


async def _record_notice_sent(account_id: str, *, now: Optional[datetime] = None) -> None:
    sent_at = now or datetime.now()
    today = _today_key(sent_at)
    async with get_async_session() as session:
        row = await session.get(AppSetting, _notice_key(account_id))
        state = _parse_notice_state(row.value if row is not None else None)
        state["count"] = min(MAX_NOTICE_SENDS, int(state.get("count") or 0) + 1)
        state["first_sent_date"] = state.get("first_sent_date") or today
        state["last_sent_date"] = today
        value = _serialize_notice_state(state)
        if row is None:
            session.add(AppSetting(key=_notice_key(account_id), value=value))
        else:
            row.value = value
        await session.commit()


async def _send_reauth_notice(item: ReauthNoticeItem) -> bool:
    if not await ensure_manager_bot_ready():
        logger.warning("Manager Bot 当前未就绪，跳过账号重绑提醒发送: account_id={}", item.account_id)
        return False

    text = (
        "账号授权已失效\n\n"
        f"账号：{item.account_label}\n"
        f"相关任务：{item.disabled_task_count} 条\n"
        f"授权到期：{_format_end_at(item.authorization_end_at)}\n\n"
        "该账号已无法继续发送任务，需要重新绑定后才能继续使用。\n"
        "即使只掉线 1 次，也可能是 Telegram 风控触发。"
        "重新绑定前请确认主要账号日常登录区域与服务器/梯子/代理区域尽量一致且稳定，避免 Telegram 拦截新登录。"
    )
    try:
        region_buttons = [
            Button.inline(region.label, data=f"acc_proxy_select:{item.account_id}:{region.code}")
            for region in SING_BOX_PROXY_REGIONS
        ]
        await bot_client.send_message(
            int(item.tg_user_id),
            text,
            buttons=[
                region_buttons[:4],
                region_buttons[4:],
                [Button.inline("📱 重新绑定", data=f"acc_relogin:{item.account_id}")],
            ],
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        error_type = _classify_delivery_exception(exc)
        if error_type in {"blocked", "deactivated", "unreachable"}:
            logger.warning(
                "账号重绑提醒跳过用户: user_id={}, tg_user_id={}, account_id={}, reason={}, error={}",
                item.user_id,
                item.tg_user_id,
                item.account_id,
                error_type,
                exc,
            )
        else:
            logger.error(
                "发送账号重绑提醒失败: user_id={}, tg_user_id={}, account_id={}, error={}",
                item.user_id,
                item.tg_user_id,
                item.account_id,
                exc,
            )
        return False
    await _record_notice_sent(item.account_id)
    return True


async def mark_account_reauth_required(account_id: str, reason: str) -> Optional[ReauthTransitionResult]:
    """Mark an account as reauth-required and notify once.

    Tasks stay enabled. The scheduler skips them while the account requires
    reauth, then the proxy observation budget controls sends after re-login.
    """
    normalized_reason = str(reason or "").strip() or "unknown"
    now = datetime.now()
    notice_item: Optional[ReauthNoticeItem] = None

    async with get_async_session() as session:
        account = await session.get(Account, str(account_id))
        if account is None:
            return None

        was_reauth_required = is_reauth_required_account(account)
        account.health_status = HealthStatus.OFFLINE
        account.reauth_required = True
        account.reauth_reason = normalized_reason
        account.reauth_required_at = account.reauth_required_at or now

        enabled_tasks = (
            await session.execute(
                select(ScheduledMessageTask).where(
                    ScheduledMessageTask.account_id == str(account_id),
                    ScheduledMessageTask.enabled == True,
                )
            )
        ).scalars().all()
        authorization_end_at = await _load_active_authorization_end_at(session, str(account_id), now)
        disabled_task_count = len(enabled_tasks)

        user_links = await _load_user_links(session)
        tg_user_id = user_links.get(int(account.user_id))
        if not was_reauth_required and tg_user_id is not None:
            notice_item = ReauthNoticeItem(
                account_id=str(account.account_id),
                user_id=int(account.user_id),
                tg_user_id=int(tg_user_id),
                account_label=_format_account_label(account),
                disabled_task_count=disabled_task_count,
                authorization_end_at=authorization_end_at,
                reason=normalized_reason,
            )

        await session.commit()

    notice_sent = False
    if notice_item is not None:
        notice_sent = await _send_reauth_notice(notice_item)
    else:
        logger.info(
            "账号重绑即时提醒跳过: account_id={}, reason={}, already_reauth_or_unlinked={}",
            account_id,
            normalized_reason,
            True,
        )

    return ReauthTransitionResult(
        account_id=str(account_id),
        user_id=notice_item.user_id if notice_item is not None else None,
        was_reauth_required=was_reauth_required,
        disabled_task_count=disabled_task_count,
        authorization_end_at=authorization_end_at,
        notice_sent=notice_sent,
    )


async def notify_account_authorization_required(account_id: str, reason: str) -> bool:
    """Notify the bound system user that this account cannot send without authorization."""
    normalized_reason = str(reason or "").strip() or "authorization_required"
    now = datetime.now()
    notice_item: Optional[ReauthNoticeItem] = None

    async with get_async_session() as session:
        account = await session.get(Account, str(account_id))
        if account is None:
            return False

        notice_row = await session.get(AppSetting, _notice_key(str(account_id)))
        notice_state = _parse_notice_state(notice_row.value if notice_row is not None else None)
        if not _notice_state_due(notice_state, now=now):
            return False

        enabled_tasks = (
            await session.execute(
                select(ScheduledMessageTask).where(
                    ScheduledMessageTask.account_id == str(account_id),
                    ScheduledMessageTask.enabled == True,
                )
            )
        ).scalars().all()
        authorization_end_at = await _load_latest_authorization_end_at(session, str(account_id))
        user_links = await _load_user_links(session)
        tg_user_id = user_links.get(int(account.user_id))
        if tg_user_id is None:
            return False

        notice_item = ReauthNoticeItem(
            account_id=str(account.account_id),
            user_id=int(account.user_id),
            tg_user_id=int(tg_user_id),
            account_label=_format_account_label(account),
            disabled_task_count=len(enabled_tasks),
            authorization_end_at=authorization_end_at,
            reason=normalized_reason,
        )

    return await _send_reauth_notice(notice_item)


class ReauthReminderRuntime:
    """Background daily reminders for accounts waiting for rebind."""

    CHECK_INTERVAL_SECONDS = 3600

    def __init__(self) -> None:
        self.running = False

    async def start(self) -> None:
        self.running = True
        logger.info("账号重绑提醒任务已启动")
        while self.running:
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(f"账号重绑提醒扫描失败: {type(exc).__name__}: {exc!r}")
            await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self.running = False
        logger.info("账号重绑提醒任务已停止")

    async def scan_once(self) -> int:
        items = await self._collect_due_reminders()
        if not items:
            return 0
        if not await ensure_manager_bot_ready():
            logger.warning("Manager Bot 当前未就绪，跳过本轮账号重绑提醒发送")
            return 0

        sent = 0
        for item in items:
            if await _send_reauth_notice(item):
                sent += 1
        if sent:
            logger.info("账号重绑提醒发送完成: {} 条", sent)
        return sent

    async def _collect_due_reminders(self) -> list[ReauthNoticeItem]:
        now = datetime.now()
        async with get_async_session() as session:
            user_links = await _load_user_links(session)
            if not user_links:
                return []

            rows = (
                await session.execute(
                    select(Account, UserAuthorization.end_at)
                    .join(UserAuthorization, UserAuthorization.current_account_id == Account.account_id)
                    .where(
                        Account.is_active.is_(True),
                        Account.reauth_required.is_(True),
                        UserAuthorization.status == "active",
                        UserAuthorization.end_at > now,
                    )
                    .order_by(UserAuthorization.end_at.asc(), Account.updated_at.asc())
                )
            ).all()

            account_rows: dict[str, tuple[Account, Optional[datetime]]] = {}
            for account, authorization_end_at in rows:
                account_rows.setdefault(str(account.account_id), (account, authorization_end_at))

            notice_rows = (
                await session.execute(
                    select(AppSetting.key, AppSetting.value).where(
                        AppSetting.key.like(f"{REAUTH_NOTICE_KEY_PREFIX}%")
                    )
                )
            ).all()
            notice_values = {str(key): str(value or "") for key, value in notice_rows}

            notice_account_ids: list[str] = []
            for key, value in notice_values.items():
                if not key.startswith(REAUTH_NOTICE_KEY_PREFIX):
                    continue
                account_id = key[len(REAUTH_NOTICE_KEY_PREFIX):]
                notice_state = _parse_notice_state(value)
                if int(notice_state.get("count") or 0) <= 0:
                    continue
                if not _notice_state_due(notice_state, now=now):
                    continue
                if account_id not in account_rows and account_id not in notice_account_ids:
                    notice_account_ids.append(account_id)

            if notice_account_ids:
                notice_accounts = (
                    await session.execute(
                        select(Account, UserAuthorization.end_at)
                        .outerjoin(UserAuthorization, UserAuthorization.current_account_id == Account.account_id)
                        .where(
                            Account.account_id.in_(notice_account_ids),
                            Account.is_active.is_(True),
                        )
                        .order_by(Account.account_id.asc(), UserAuthorization.end_at.desc())
                    )
                ).all()
                for account, authorization_end_at in notice_accounts:
                    if (
                        not is_reauth_required_account(account)
                        and authorization_end_at is not None
                        and authorization_end_at > now
                    ):
                        continue
                    account_rows.setdefault(str(account.account_id), (account, authorization_end_at))

            account_ids = list(account_rows.keys())
            task_counts_by_account: dict[str, int] = {}
            if account_ids:
                task_count_rows = (
                    await session.execute(
                        select(
                            ScheduledMessageTask.account_id,
                            func.count(ScheduledMessageTask.task_id).label("task_count"),
                        )
                        .where(
                            ScheduledMessageTask.account_id.in_(account_ids),
                            ScheduledMessageTask.enabled == True,
                        )
                        .group_by(ScheduledMessageTask.account_id)
                    )
                ).all()
                task_counts_by_account = {
                    str(account_id): int(task_count or 0)
                    for account_id, task_count in task_count_rows
                }

            items: list[ReauthNoticeItem] = []
            seen_accounts: set[str] = set()
            for account_id, (account, authorization_end_at) in account_rows.items():
                account_id = str(account.account_id)
                if account_id in seen_accounts:
                    continue
                seen_accounts.add(account_id)

                tg_user_id = user_links.get(int(account.user_id))
                if tg_user_id is None:
                    continue

                notice_state = _parse_notice_state(notice_values.get(_notice_key(account_id), ""))
                if not _notice_state_due(notice_state, now=now):
                    continue

                items.append(
                    ReauthNoticeItem(
                        account_id=account_id,
                        user_id=int(account.user_id),
                        tg_user_id=int(tg_user_id),
                        account_label=_format_account_label(account),
                        disabled_task_count=task_counts_by_account.get(account_id, 0),
                        authorization_end_at=authorization_end_at,
                        reason=str(account.reauth_reason or "authorization_expired"),
                    )
                )
            return items


reauth_reminder_runtime = ReauthReminderRuntime()
