"""Slot expiry reminders delivered by manager bot."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import and_, select
from telethon import Button

from backend.bot.client_runtime.manager import bot_client
from backend.bot.handlers.core.helpers import is_valid_button_url
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    AppSetting,
    SlotNoticeLog,
    UserLicenseSlot,
)
from backend.h5_backend.services.licensing.service import list_due_slot_reminders
from backend.h5_backend.services.me.service import get_me_service

NOTICE_DAYS = (7, 3, 1)
USER_LINK_KEY_PREFIX = "tg_user_link:"


@dataclass
class LicenseReminderItem:
    """Pending license-slot reminder payload."""

    slot_id: str
    user_id: int
    tg_user_id: int
    days_before: int
    end_at: datetime
    account_id: Optional[str]


class LicenseSlotNotifier:
    """Background reminder task for expiring license slots."""

    CHECK_INTERVAL_SECONDS = 3600

    def __init__(self) -> None:
        self.running = False

    async def start(self) -> None:
        self.running = True
        logger.info("套餐位到期提醒任务已启动")
        while self.running:
            try:
                await self.scan_once()
            except Exception as exc:
                logger.exception(f"套餐位提醒扫描失败: {type(exc).__name__}: {exc!r}")
            await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self.running = False
        logger.info("套餐位到期提醒任务已停止")

    async def scan_once(self) -> int:
        now = datetime.now()
        reminder_items = await self._collect_due_reminders(now)
        if not reminder_items:
            return 0

        me_service = get_me_service()
        purchase = await me_service.get_purchase_entry()
        sent_count = 0

        for item in reminder_items:
            try:
                text = (
                    "⏰ **自动发送套餐位即将到期**\n\n"
                    f"TG账号：{item.account_id or '待绑定'}\n"
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
                logger.error(
                    "发送套餐位到期提醒失败: user_id={}, tg_user_id={}, days_before={}, error={}",
                    item.user_id,
                    item.tg_user_id,
                    item.days_before,
                    exc,
                )

        if sent_count:
            logger.info("套餐位到期提醒发送完成: {} 条", sent_count)
        return sent_count

    async def _collect_due_reminders(self, now: datetime) -> list[LicenseReminderItem]:
        async with get_async_session() as session:
            user_link_rows = (
                await session.execute(
                    select(AppSetting.key, AppSetting.value).where(AppSetting.key.like(f"{USER_LINK_KEY_PREFIX}%"))
                )
            ).all()
            user_to_tg: dict[int, int] = {}
            for key, value in user_link_rows:
                try:
                    tg_user_id = int(str(key).split(USER_LINK_KEY_PREFIX, 1)[1])
                    user_id = int(str(value).strip())
                except Exception:
                    continue
                user_to_tg[user_id] = tg_user_id

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
                        slot_id=str(row["slot_id"]),
                        user_id=int(row["user_id"]),
                        tg_user_id=int(row["tg_user_id"]),
                        days_before=int(row["days_before"]),
                        end_at=row["end_at"],
                        account_id=row.get("account_id"),
                    )
                )
            return notice_items

    async def _record_notice(self, item: LicenseReminderItem) -> None:
        async with get_async_session() as session:
            session.add(
                SlotNoticeLog(
                    slot_id=item.slot_id,
                    user_id=item.user_id,
                    days_before=item.days_before,
                )
            )
            await session.commit()


license_slot_notifier = LicenseSlotNotifier()
