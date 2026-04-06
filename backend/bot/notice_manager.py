"""Managed bot notice card delivery and refresh."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from telethon.errors import MessageNotModifiedError

from backend.bot.client_runtime.manager import bot_client
from backend.bot.handlers.core.helpers import is_valid_button_url
from backend.bot.handlers.core.user_link import USER_LINK_KEY_PREFIX
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import AppSetting
from backend.h5_backend.services.me.service import get_me_service

NOTICE_MESSAGE_KEY_PREFIX = "tg_notice_msg:"


def _notice_message_key(tg_user_id: int) -> str:
    return f"{NOTICE_MESSAGE_KEY_PREFIX}{int(tg_user_id)}"


class BotNoticeManager:
    """Manage one persisted notice message per Telegram user."""

    @staticmethod
    def _build_notice_version(*, enabled: bool, message_text: str, target_url: str) -> str:
        payload = f"{1 if enabled else 0}\n{message_text.strip()}\n{target_url.strip()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _render_notice_text(*, message_text: str, target_url: str) -> str:
        message_text = (message_text or "").strip()
        target_url = (target_url or "").strip()
        if message_text and target_url:
            return f"{message_text}\n\n{target_url}"
        return message_text or target_url

    async def get_notice_entry(self) -> dict[str, Any]:
        raw = await get_me_service().get_public_notice_entry()
        enabled = bool(raw.get("enabled"))
        entry_button_text = str(raw.get("entry_button_text") or "📢 公告栏").strip() or "📢 公告栏"
        message_text = str(raw.get("message_text") or "").strip()
        target_url = str(raw.get("target_url") or "").strip()
        return {
            "enabled": enabled,
            "entry_button_text": entry_button_text,
            "message_text": message_text,
            "target_url": target_url,
            "updated_at": raw.get("updated_at"),
            "notice_version": self._build_notice_version(
                enabled=enabled,
                message_text=message_text,
                target_url=target_url,
            ),
            "is_ready": enabled and bool(message_text) and is_valid_button_url(target_url),
        }

    async def _load_notice_state(self, tg_user_id: int) -> Optional[dict[str, Any]]:
        async with get_async_session() as session:
            row = await session.get(AppSetting, _notice_message_key(tg_user_id))
            if row is None or not (row.value or "").strip():
                return None
            try:
                data = json.loads(row.value)
            except Exception:
                logger.warning("公告状态解析失败，已忽略: tg_user_id={}", tg_user_id)
                return None
            if not isinstance(data, dict):
                return None
            return data

    async def _save_notice_state(
        self,
        tg_user_id: int,
        *,
        chat_id: int,
        message_id: int,
        notice_version: str,
    ) -> None:
        payload = json.dumps(
            {
                "chat_id": int(chat_id),
                "message_id": int(message_id),
                "notice_version": str(notice_version),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        async with get_async_session() as session:
            key = _notice_message_key(tg_user_id)
            row = await session.get(AppSetting, key)
            if row is None:
                session.add(AppSetting(key=key, value=payload))
            else:
                row.value = payload
            await session.commit()

    async def _clear_notice_state(self, tg_user_id: int) -> Optional[dict[str, Any]]:
        async with get_async_session() as session:
            key = _notice_message_key(tg_user_id)
            row = await session.get(AppSetting, key)
            if row is None:
                return None
            try:
                data = json.loads(row.value) if (row.value or "").strip() else None
            except Exception:
                data = None
            await session.delete(row)
            await session.commit()
            return data if isinstance(data, dict) else None

    async def _delete_notice_message(self, tg_user_id: int, state: Optional[dict[str, Any]]) -> None:
        if not state:
            return
        message_id = state.get("message_id")
        if not message_id:
            return
        try:
            await bot_client.delete_messages(int(tg_user_id), [int(message_id)])
        except Exception:
            pass

    async def _message_exists(self, tg_user_id: int, message_id: int) -> bool:
        try:
            message = await bot_client.get_messages(int(tg_user_id), ids=int(message_id))
        except Exception:
            return False
        if message is None:
            return False
        if isinstance(message, list):
            return any(item is not None for item in message)
        return getattr(message, "id", None) is not None

    async def clear_notice_for_user(self, tg_user_id: int) -> dict[str, Any]:
        state = await self._clear_notice_state(tg_user_id)
        await self._delete_notice_message(tg_user_id, state)
        return {"status": "cleared", "tg_user_id": int(tg_user_id)}

    async def _send_notice_message(self, tg_user_id: int, *, message_text: str, target_url: str):
        text = self._render_notice_text(message_text=message_text, target_url=target_url)
        try:
            return await bot_client.send_message(
                int(tg_user_id),
                text,
                parse_mode="html",
                link_preview=True,
            )
        except Exception as exc:
            logger.warning("公告消息按 HTML 发送失败，回退纯文本: tg_user_id={}, error={}", tg_user_id, type(exc).__name__)
            return await bot_client.send_message(
                int(tg_user_id),
                text,
                parse_mode=None,
                link_preview=True,
            )

    async def _edit_notice_message(
        self,
        tg_user_id: int,
        *,
        message_id: int,
        message_text: str,
        target_url: str,
    ) -> bool:
        text = self._render_notice_text(message_text=message_text, target_url=target_url)
        try:
            await bot_client.edit_message(
                int(tg_user_id),
                int(message_id),
                text=text,
                parse_mode="html",
                link_preview=True,
            )
            return True
        except MessageNotModifiedError:
            return True
        except Exception as exc:
            logger.warning(
                "公告消息按 HTML 编辑失败: tg_user_id={}, message_id={}, error={}",
                tg_user_id,
                message_id,
                type(exc).__name__,
            )
        try:
            await bot_client.edit_message(
                int(tg_user_id),
                int(message_id),
                text=text,
                parse_mode=None,
                link_preview=True,
            )
            return True
        except MessageNotModifiedError:
            return True
        except Exception:
            return False

    async def ensure_notice_for_user(
        self,
        tg_user_id: int,
        *,
        force_repost: bool = False,
    ) -> dict[str, Any]:
        entry = await self.get_notice_entry()
        state = await self._load_notice_state(tg_user_id)

        if not entry["is_ready"]:
            await self.clear_notice_for_user(tg_user_id)
            return {"status": "disabled", "tg_user_id": int(tg_user_id)}

        old_message_id = None
        if state:
            try:
                old_message_id = int(state.get("message_id") or 0) or None
            except Exception:
                old_message_id = None

        if force_repost:
            message = await self._send_notice_message(
                tg_user_id,
                message_text=entry["message_text"],
                target_url=entry["target_url"],
            )
            await self._save_notice_state(
                tg_user_id,
                chat_id=int(tg_user_id),
                message_id=int(message.id),
                notice_version=str(entry["notice_version"]),
            )
            if old_message_id and old_message_id != int(message.id):
                await self._delete_notice_message(
                    tg_user_id,
                    {"message_id": old_message_id},
                )
            return {
                "status": "reposted",
                "tg_user_id": int(tg_user_id),
                "message_id": int(message.id),
                "notice_version": str(entry["notice_version"]),
            }

        if old_message_id and str(state.get("notice_version") or "") == str(entry["notice_version"]):
            if not await self._message_exists(int(tg_user_id), int(old_message_id)):
                old_message_id = None
            else:
                return {
                    "status": "noop",
                    "tg_user_id": int(tg_user_id),
                    "message_id": old_message_id,
                    "notice_version": str(entry["notice_version"]),
                }

        if old_message_id:
            edited = await self._edit_notice_message(
                tg_user_id,
                message_id=old_message_id,
                message_text=entry["message_text"],
                target_url=entry["target_url"],
            )
            if edited:
                await self._save_notice_state(
                    tg_user_id,
                    chat_id=int(tg_user_id),
                    message_id=old_message_id,
                    notice_version=str(entry["notice_version"]),
                )
                return {
                    "status": "edited",
                    "tg_user_id": int(tg_user_id),
                    "message_id": old_message_id,
                    "notice_version": str(entry["notice_version"]),
                }

        message = await self._send_notice_message(
            tg_user_id,
            message_text=entry["message_text"],
            target_url=entry["target_url"],
        )
        await self._save_notice_state(
            tg_user_id,
            chat_id=int(tg_user_id),
            message_id=int(message.id),
            notice_version=str(entry["notice_version"]),
        )
        if old_message_id and old_message_id != int(message.id):
            await self._delete_notice_message(
                tg_user_id,
                {"message_id": old_message_id},
            )
        return {
            "status": "sent",
            "tg_user_id": int(tg_user_id),
            "message_id": int(message.id),
            "notice_version": str(entry["notice_version"]),
        }

    async def refresh_all_linked_users(self) -> dict[str, Any]:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(AppSetting.key).where(AppSetting.key.like(f"{USER_LINK_KEY_PREFIX}%"))
                )
            ).all()
        tg_user_ids: list[int] = []
        for (key,) in rows:
            try:
                tg_user_ids.append(int(str(key).split(USER_LINK_KEY_PREFIX, 1)[1]))
            except Exception:
                continue
        tg_user_ids = sorted(set(tg_user_ids))

        summary = {
            "total_users": len(tg_user_ids),
            "updated": 0,
            "failed": 0,
            "results": [],
        }
        for tg_user_id in tg_user_ids:
            try:
                result = await self.ensure_notice_for_user(tg_user_id, force_repost=False)
                summary["results"].append(result)
                if result.get("status") != "noop":
                    summary["updated"] += 1
            except Exception as exc:
                logger.exception("批量刷新公告失败: tg_user_id={}, error={}", tg_user_id, type(exc).__name__)
                summary["failed"] += 1
                summary["results"].append(
                    {
                        "status": "failed",
                        "tg_user_id": int(tg_user_id),
                        "error": type(exc).__name__,
                    }
                )
        logger.info(
            "Bot 公告批量刷新完成: total_users={}, updated={}, failed={}",
            summary["total_users"],
            summary["updated"],
            summary["failed"],
        )
        return summary


_bot_notice_manager: Optional[BotNoticeManager] = None


def get_bot_notice_manager() -> BotNoticeManager:
    global _bot_notice_manager
    if _bot_notice_manager is None:
        _bot_notice_manager = BotNoticeManager()
    return _bot_notice_manager
