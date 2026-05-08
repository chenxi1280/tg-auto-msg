"""Settings-related operations extracted from AdminLicenseService."""
from __future__ import annotations

import re
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import func, select

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import AppSetting, TaskLog, ActivationCard, User, UserAuthorization, UserAuthorizationCard
from backend.config.core.settings import settings
from backend.utils.url_validation import is_valid_button_url, is_valid_purchase_button_url
from backend.h5_backend.services.shared.audit import append_audit_log, mask_actor_name

_NOTICE_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
DEFAULT_PURCHASE_URL = "https://t.me/"
DEFAULT_PURCHASE_BUTTON_TEXT = "联系 Telegram 购买"
DEFAULT_BOT_NOTICE_ENTRY_BUTTON_TEXT = "📢 公告栏"
PURCHASE_SETTING_KEYS = ["purchase_url", "purchase_button_text", "purchase_buttons"]


class SettingsService:
    """Purchase and bot-notice settings management."""

    @staticmethod
    def _extract_first_url(text: str) -> str:
        match = _NOTICE_URL_PATTERN.search(text or "")
        return match.group(0).strip() if match else ""

    @classmethod
    def _remove_first_url(cls, text: str) -> str:
        if not text:
            return ""
        return _NOTICE_URL_PATTERN.sub("", text, count=1).strip()

    @staticmethod
    def _is_valid_purchase_url(url: str) -> bool:
        return is_valid_purchase_button_url(url)

    @classmethod
    def _normalize_purchase_buttons(
        cls,
        raw_buttons: Optional[List[Dict[str, Any]]],
        *,
        legacy_url: str,
        legacy_button_text: str,
    ) -> List[Dict[str, str]]:
        buttons: List[Dict[str, str]] = []
        for index, item in enumerate((raw_buttons or [])[:2]):
            text = str(item.get("text") or item.get("button_text") or "").strip()
            url = str(item.get("url") or "").strip()
            if not text and not url:
                continue
            if not url:
                raise HTTPException(status_code=400, detail=f"购买按钮 {index + 1} 链接不能为空")
            if not cls._is_valid_purchase_url(url):
                raise HTTPException(status_code=400, detail=f"购买按钮 {index + 1} 链接格式无效，仅支持 Telegram 链接或公网 HTTP/HTTPS 商铺链接")
            buttons.append(
                {
                    "text": text or (DEFAULT_PURCHASE_BUTTON_TEXT if index == 0 else f"购买入口 {index + 1}"),
                    "url": url,
                }
            )

        if buttons:
            return buttons

        fallback_url = (legacy_url or DEFAULT_PURCHASE_URL).strip()
        fallback_text = (legacy_button_text or DEFAULT_PURCHASE_BUTTON_TEXT).strip()
        if not cls._is_valid_purchase_url(fallback_url):
            fallback_url = DEFAULT_PURCHASE_URL
        return [{"text": fallback_text or DEFAULT_PURCHASE_BUTTON_TEXT, "url": fallback_url}]

    @staticmethod
    def _load_purchase_buttons_json(raw_value: Optional[str]) -> Optional[List[Dict[str, Any]]]:
        if not raw_value:
            return None
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, list):
            return None
        return [item for item in parsed if isinstance(item, dict)]

    async def get_purchase_settings(self) -> Dict[str, Any]:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(AppSetting).where(AppSetting.key.in_(PURCHASE_SETTING_KEYS))
                )
            ).scalars().all()
            values = {row.key: row.value for row in rows}
            legacy_url = (values.get("purchase_url") or DEFAULT_PURCHASE_URL).strip()
            legacy_text = (values.get("purchase_button_text") or DEFAULT_PURCHASE_BUTTON_TEXT).strip()
            buttons = self._normalize_purchase_buttons(
                self._load_purchase_buttons_json(values.get("purchase_buttons")),
                legacy_url=legacy_url,
                legacy_button_text=legacy_text,
            )
            primary = buttons[0]
            return {
                "purchase_url": primary["url"],
                "purchase_button_text": primary["text"],
                "purchase_buttons": buttons,
            }

    async def get_bot_notice_settings(self) -> Dict[str, Any]:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(AppSetting).where(
                        AppSetting.key.in_(
                            [
                                "bot_notice_enabled",
                                "bot_notice_entry_button_text",
                                "bot_notice_message_text",
                                "bot_notice_target_url",
                                # 兼容旧版配置
                                "bot_notice_title",
                                "bot_notice_content",
                                "bot_notice_button_text",
                            ]
                        )
                    )
                )
            ).scalars().all()
            values = {row.key: row.value for row in rows}
            updated_at = None
            for row in rows:
                if row.updated_at and (updated_at is None or row.updated_at > updated_at):
                    updated_at = row.updated_at
            enabled_raw = (values.get("bot_notice_enabled") or "").strip().lower()
            message_text = (values.get("bot_notice_message_text") or "").strip()
            legacy_content = (values.get("bot_notice_content") or "").strip()
            if not message_text and legacy_content:
                message_text = self._remove_first_url(legacy_content) or legacy_content
            target_url = (values.get("bot_notice_target_url") or "").strip()
            if not target_url and legacy_content:
                target_url = self._extract_first_url(legacy_content)
            entry_button_text = (
                values.get("bot_notice_entry_button_text")
                or values.get("bot_notice_button_text")
                or DEFAULT_BOT_NOTICE_ENTRY_BUTTON_TEXT
            )
            return {
                "enabled": enabled_raw in {"1", "true", "yes", "on"},
                "entry_button_text": str(entry_button_text).strip() or DEFAULT_BOT_NOTICE_ENTRY_BUTTON_TEXT,
                "message_text": message_text,
                "target_url": target_url,
                "updated_at": updated_at.isoformat() if updated_at else None,
            }

    async def update_purchase_settings(
        self,
        *,
        purchase_url: str = "",
        purchase_button_text: str = "",
        purchase_buttons: Optional[List[Dict[str, Any]]] = None,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if purchase_buttons is None:
            url = (purchase_url or "").strip()
            if not url:
                raise HTTPException(status_code=400, detail="购买链接不能为空")
            if not self._is_valid_purchase_url(url):
                raise HTTPException(status_code=400, detail="购买链接格式无效，仅支持 Telegram 链接或公网 HTTP/HTTPS 商铺链接")
        buttons = self._normalize_purchase_buttons(
            purchase_buttons,
            legacy_url=purchase_url,
            legacy_button_text=purchase_button_text,
        )
        primary = buttons[0]
        buttons_json = json.dumps(buttons, ensure_ascii=False)

        async with get_async_session() as session:
            url_row = await session.get(AppSetting, "purchase_url")
            if not url_row:
                session.add(AppSetting(key="purchase_url", value=primary["url"]))
            else:
                url_row.value = primary["url"]

            text_row = await session.get(AppSetting, "purchase_button_text")
            if not text_row:
                session.add(AppSetting(key="purchase_button_text", value=primary["text"]))
            else:
                text_row.value = primary["text"]

            buttons_row = await session.get(AppSetting, "purchase_buttons")
            if not buttons_row:
                session.add(AppSetting(key="purchase_buttons", value=buttons_json))
            else:
                buttons_row.value = buttons_json

            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
                action="admin.update_purchase_settings",
                target_type="settings",
                target_id="purchase",
                detail={
                    "purchase_url": primary["url"],
                    "purchase_button_text": primary["text"],
                    "purchase_buttons": buttons,
                },
                ip_address=ip_address,
            )
            await session.commit()

        return {"purchase_url": primary["url"], "purchase_button_text": primary["text"], "purchase_buttons": buttons}

    async def update_bot_notice_settings(
        self,
        *,
        enabled: bool,
        entry_button_text: str,
        message_text: str,
        target_url: str,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_entry_button_text = (entry_button_text or "").strip() or DEFAULT_BOT_NOTICE_ENTRY_BUTTON_TEXT
        normalized_message_text = (message_text or "").strip()
        normalized_target_url = (target_url or "").strip()

        if enabled and not normalized_message_text:
            raise HTTPException(status_code=400, detail="启用公告时，公告正文不能为空")
        if normalized_target_url and not is_valid_button_url(normalized_target_url):
            raise HTTPException(status_code=400, detail="公告链接格式无效，请填写可公网访问的 http/https 链接")

        async with get_async_session() as session:
            values = {
                "bot_notice_enabled": "1" if enabled else "0",
                "bot_notice_entry_button_text": normalized_entry_button_text,
                "bot_notice_message_text": normalized_message_text,
                "bot_notice_target_url": normalized_target_url,
            }
            for key, value in values.items():
                row = await session.get(AppSetting, key)
                if row is None:
                    session.add(AppSetting(key=key, value=value))
                else:
                    row.value = value

            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
                action="admin.update_bot_notice_settings",
                target_type="settings",
                target_id="bot_notice",
                detail={
                    "enabled": enabled,
                    "entry_button_text": normalized_entry_button_text,
                    "message_length": len(normalized_message_text),
                    "target_url": normalized_target_url,
                },
                ip_address=ip_address,
            )
            await session.commit()
        from backend.bot.notice_manager import get_bot_notice_manager

        refresh_summary = await get_bot_notice_manager().refresh_all_linked_users()
        result = await self.get_bot_notice_settings()
        result["refresh_summary"] = refresh_summary
        return result

    async def get_today_system_stats(self) -> Dict[str, Any]:
        timezone_name = settings.timezone or "Asia/Shanghai"
        now = datetime.now(ZoneInfo(timezone_name))
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
        end_of_day = (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).replace(tzinfo=None)

        async with get_async_session() as session:
            sent_messages = int(
                (
                    await session.execute(
                        select(func.count(TaskLog.id)).where(
                            TaskLog.send_at >= start_of_day,
                            TaskLog.send_at < end_of_day,
                        )
                    )
                ).scalar_one()
                or 0
            )
            sent_success = int(
                (
                    await session.execute(
                        select(func.count(TaskLog.id)).where(
                            TaskLog.result == "success",
                            TaskLog.send_at >= start_of_day,
                            TaskLog.send_at < end_of_day,
                        )
                    )
                ).scalar_one()
                or 0
            )
            sent_failed = int(
                (
                    await session.execute(
                        select(func.count(TaskLog.id)).where(
                            TaskLog.result == "failed",
                            TaskLog.send_at >= start_of_day,
                            TaskLog.send_at < end_of_day,
                        )
                    )
                ).scalar_one()
                or 0
            )
            bound_cards = int(
                (
                    await session.execute(
                        select(func.count(ActivationCard.id)).where(
                            ActivationCard.is_used.is_(True),
                            ActivationCard.used_at.is_not(None),
                            ActivationCard.used_at >= start_of_day,
                            ActivationCard.used_at < end_of_day,
                        )
                    )
                ).scalar_one()
                or 0
            )
            new_users = int(
                (
                    await session.execute(
                        select(func.count(User.id)).where(
                            User.created_at >= start_of_day,
                            User.created_at < end_of_day,
                        )
                    )
                ).scalar_one()
                or 0
            )
            activations = int(
                (
                    await session.execute(
                        select(func.count(UserAuthorization.authorization_id)).where(
                            UserAuthorization.created_at >= start_of_day,
                            UserAuthorization.created_at < end_of_day,
                        )
                    )
                ).scalar_one()
                or 0
            )
            card_renewals = int(
                (
                    await session.execute(
                        select(func.count(UserAuthorizationCard.id)).where(
                            UserAuthorizationCard.applied_at >= start_of_day,
                            UserAuthorizationCard.applied_at < end_of_day,
                        )
                    )
                ).scalar_one()
                or 0
            )

        return {
            "date": now.date().isoformat(),
            "timezone": timezone_name,
            "today_sent_messages": sent_success,
            "today_bound_cards": bound_cards,
            "today_new_users": new_users,
            "today_activations": activations,
            "today_card_renewals": card_renewals,
            "today_sent_messages_total": sent_messages,
            "today_sent_success": sent_success,
            "today_sent_failed": sent_failed,
        }


_settings_service: SettingsService | None = None


def get_settings_service() -> SettingsService:
    global _settings_service
    if _settings_service is None:
        _settings_service = SettingsService()
    return _settings_service
