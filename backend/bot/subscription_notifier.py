"""Subscription expiry reminders delivered by manager bot."""
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
    PricingPlan,
    SubscriptionNoticeLog,
    UserSubscription,
)
from backend.h5_backend.services.me.service import get_me_service

NOTICE_DAYS = (7, 3, 1)
USER_LINK_KEY_PREFIX = "tg_user_link:"


@dataclass
class SubscriptionReminderItem:
    """Pending subscription reminder payload."""

    subscription_id: int
    user_id: int
    tg_user_id: int
    days_before: int
    end_at: datetime
    plan_name: str


class SubscriptionNotifier:
    """Background reminder task for expiring subscriptions."""

    CHECK_INTERVAL_SECONDS = 3600

    def __init__(self) -> None:
        self.running = False

    async def start(self) -> None:
        self.running = True
        logger.info("订阅到期提醒任务已启动")
        while self.running:
            try:
                await self.scan_once()
            except Exception as exc:
                logger.exception(f"订阅提醒扫描失败: {type(exc).__name__}: {exc!r}")
            await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)

    async def stop(self) -> None:
        self.running = False
        logger.info("订阅到期提醒任务已停止")

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
                    "⏰ **订阅即将到期提醒**\n\n"
                    f"套餐：{item.plan_name}\n"
                    f"剩余天数：{item.days_before}\n"
                    f"到期时间：{item.end_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                    "请提前续费，避免账号功能中断。"
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
                    "发送订阅到期提醒失败: user_id={}, tg_user_id={}, days_before={}, error={}",
                    item.user_id,
                    item.tg_user_id,
                    item.days_before,
                    exc,
                )

        if sent_count:
            logger.info("订阅到期提醒发送完成: {} 条", sent_count)
        return sent_count

    async def _collect_due_reminders(self, now: datetime) -> list[SubscriptionReminderItem]:
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

            upper_bound = now + timedelta(days=max(NOTICE_DAYS) + 1)
            result = await session.execute(
                select(
                    UserSubscription.id,
                    UserSubscription.user_id,
                    UserSubscription.end_at,
                    PricingPlan.display_name,
                    UserSubscription.plan_code,
                )
                .outerjoin(PricingPlan, PricingPlan.plan_code == UserSubscription.plan_code)
                .where(
                    and_(
                        UserSubscription.status == "active",
                        UserSubscription.user_id.in_(list(user_to_tg.keys())),
                        UserSubscription.end_at > now,
                        UserSubscription.end_at <= upper_bound,
                    )
                )
            )
            rows = result.all()

            notice_items: list[SubscriptionReminderItem] = []
            for subscription_id, user_id, end_at, display_name, plan_code in rows:
                days_before = (end_at.date() - now.date()).days
                if days_before not in NOTICE_DAYS:
                    continue
                existed = await session.execute(
                    select(SubscriptionNoticeLog.id).where(
                        SubscriptionNoticeLog.subscription_id == int(subscription_id),
                        SubscriptionNoticeLog.days_before == int(days_before),
                    )
                )
                if existed.scalar_one_or_none() is not None:
                    continue
                tg_user_id = user_to_tg.get(int(user_id))
                if tg_user_id is None:
                    continue
                notice_items.append(
                    SubscriptionReminderItem(
                        subscription_id=int(subscription_id),
                        user_id=int(user_id),
                        tg_user_id=int(tg_user_id),
                        days_before=int(days_before),
                        end_at=end_at,
                        plan_name=display_name or plan_code or "未命名套餐",
                    )
                )
            return notice_items

    async def _record_notice(self, item: SubscriptionReminderItem) -> None:
        async with get_async_session() as session:
            session.add(
                SubscriptionNoticeLog(
                    subscription_id=item.subscription_id,
                    user_id=item.user_id,
                    days_before=item.days_before,
                )
            )
            await session.commit()


subscription_notifier = SubscriptionNotifier()
