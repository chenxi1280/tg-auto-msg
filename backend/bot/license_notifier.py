"""Authorization expiry reminders delivered by manager bot."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from loguru import logger
from telethon import Button
from telethon.errors import (
    ChatWriteForbiddenError,
    InputUserDeactivatedError,
    PeerIdInvalidError,
    UserIsBlockedError,
)

from backend.bot.client_runtime.manager import bot_client, ensure_manager_bot_ready
from backend.bot.handlers.core.user_link import load_latest_linked_tg_user_ids
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    AuthorizationNoticeLog,
)
from backend.h5_backend.services.licensing.service import list_due_slot_reminders
from backend.h5_backend.services.me.service import get_me_service
from backend.utils.url_validation import is_valid_button_url

NOTICE_DAYS = (7, 3, 1)


@dataclass
class LicenseReminderItem:
    """Pending authorization reminder payload."""

    authorization_id: str
    user_id: int
    tg_user_id: int
    days_before: int
    end_at: datetime
    account_id: Optional[str]
    account_name: Optional[str] = None


class LicenseSlotNotifier:
    """Background reminder task for expiring authorizations."""

    CHECK_INTERVAL_SECONDS = 3600

    def __init__(self) -> None:
        self.running = False

    @staticmethod
    def _classify_delivery_exception(exc: Exception) -> str:
        if isinstance(exc, UserIsBlockedError):
            return "blocked"
        if isinstance(exc, InputUserDeactivatedError):
            return "deactivated"
        if isinstance(exc, (PeerIdInvalidError, ChatWriteForbiddenError)):
            return "unreachable"
        return "failed"

    async def start(self) -> None:
        self.running = True
        logger.info("授权到期提醒任务已启动")
        while self.running:
            try:
                await self.scan_once()
            except Exception as exc:
                logger.exception(f"授权提醒扫描失败: {type(exc).__name__}: {exc!r}")
            await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self.running = False
        logger.info("授权到期提醒任务已停止")

    async def scan_once(self) -> int:
        now = datetime.now()
        reminder_items = await self._collect_due_reminders(now)
        if not reminder_items:
            return 0
        if not await ensure_manager_bot_ready():
            logger.warning("Manager Bot 当前未就绪，跳过本轮授权到期提醒发送")
            return 0

        me_service = get_me_service()
        purchase = await me_service.get_purchase_entry()
        sent_count = 0

        for item in reminder_items:
            try:
                text = (
                    "⏰ **自动发送授权即将到期**\n\n"
                    f"TG账号：{item.account_name or '未绑定'}\n"
                    f"剩余天数：{item.days_before}\n"
                    f"到期时间：{item.end_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                    "请提前续费，避免该 TG 账号的自动发送任务中断。"
                )
                buttons = None
                purchase_url = (purchase.get("url") or "").strip()
                if is_valid_button_url(purchase_url):
                    buttons = [[Button.url(purchase.get("button_text") or "立即购买", purchase_url)]]

                await bot_client.send_message(
                    item.tg_user_id,
                    text,
                    buttons=buttons,
                    parse_mode="markdown",
                )
                await self._record_notice(item)
                sent_count += 1
            except Exception as exc:
                error_type = self._classify_delivery_exception(exc)
                if error_type in {"blocked", "deactivated", "unreachable"}:
                    logger.warning(
                        "授权到期提醒跳过用户: user_id={}, tg_user_id={}, days_before={}, reason={}, error={}",
                        item.user_id,
                        item.tg_user_id,
                        item.days_before,
                        error_type,
                        exc,
                    )
                else:
                    logger.error(
                        "发送授权到期提醒失败: user_id={}, tg_user_id={}, days_before={}, error={}",
                        item.user_id,
                        item.tg_user_id,
                        item.days_before,
                        exc,
                    )

        if sent_count:
            logger.info("授权到期提醒发送完成: {} 条", sent_count)
        return sent_count

    async def _collect_due_reminders(self, now: datetime) -> list[LicenseReminderItem]:
        async with get_async_session() as session:
            user_to_tg = await load_latest_linked_tg_user_ids(session)

            if not user_to_tg:
                return []

            notice_items: list[LicenseReminderItem] = []
            rows = await list_due_slot_reminders(
                user_id_to_tg=user_to_tg,
                session=session,
                notice_days=NOTICE_DAYS,
            )
            for row in rows:
                notice_items.append(
                    LicenseReminderItem(
                        authorization_id=str(row["authorization_id"]),
                        user_id=int(row["user_id"]),
                        tg_user_id=int(row["tg_user_id"]),
                        days_before=int(row["days_before"]),
                        end_at=row["end_at"],
                        account_id=row.get("account_id"),
                        account_name=row.get("account_name"),
                    )
                )
            return notice_items

    async def _record_notice(self, item: LicenseReminderItem) -> None:
        async with get_async_session() as session:
            session.add(
                AuthorizationNoticeLog(
                    authorization_id=item.authorization_id,
                    user_id=item.user_id,
                    days_before=item.days_before,
                )
            )
            await session.commit()


license_slot_notifier = LicenseSlotNotifier()
