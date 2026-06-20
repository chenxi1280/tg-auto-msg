"""Telegram developer app credential management, health checks and assignment."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any, Dict, List, Iterable, Sequence

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import and_, func, select
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.help import GetConfigRequest

from backend.config.core.settings import settings
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    Account,
    AdminAuditLog,
    AppSetting,
    DeveloperAppHealthStatus,
    HealthStatus,
    TelegramDeveloperApp,
)
from backend.utils.security.crypto import decrypt_proxy_password, encrypt_proxy_password

DEFAULT_APP_SETTING_KEY = "default_developer_app_id"
USER_APP_SETTING_PREFIX = "user_dev_app:"
ASSIGNMENT_MODE_SETTING_KEY = "developer_app_assignment_mode"
ASSIGNMENT_CURSOR_SETTING_KEY = "developer_app_assignment_cursor"
ALERT_TG_USER_IDS_SETTING_KEY = "developer_app_alert_tg_user_ids"
DEFAULT_ASSIGNMENT_MODE = "round_robin"
DEFAULT_SELECTION_WEIGHT = 100
HEALTH_CHECK_TIMEOUT_SECONDS = 20
HEALTH_FAILURE_THRESHOLD = 2
DEVELOPER_APP_UNHEALTHY_REASON = "developer_app_unhealthy"
ASSIGNMENT_CONTEXT_NEW = "new_account_initial_assign"
ASSIGNMENT_CONTEXT_EXISTING_REASSIGN = "existing_account_reassign"


@dataclass
class DeveloperAppCredentials:
    """Resolved Telegram API credentials."""

    app_id: Optional[int]
    api_id: int
    api_hash: str
    credentials_version: int
    source: str


@dataclass
class DeveloperAppHealthCheckResult:
    """Health-check result for one developer app."""

    app_id: int
    app_name: str
    previous_status: str
    probe_status: str
    current_status: str
    checked_at: datetime
    latency_ms: Optional[int]
    error: Optional[str]
    migrated_account_ids: List[str]
    stalled_account_ids: List[str]
    notified_recipients: List[int]
    probe_ok: bool
    status_changed: bool
    migration_executed: bool
    probe_failed_without_downgrade: bool
    recovered_account_ids: List[str] = field(default_factory=list)
    unrecovered_account_ids: List[str] = field(default_factory=list)


def _user_app_key(user_id: int) -> str:
    return f"{USER_APP_SETTING_PREFIX}{int(user_id)}"


class DeveloperAppService:
    """Service for multi-developer Telegram app credential pool."""

    @staticmethod
    def _snapshot_app(row: TelegramDeveloperApp) -> Dict[str, Any]:
        return {
            "id": int(row.id),
            "app_name": row.app_name,
            "api_id": int(row.api_id),
            "is_active": bool(row.is_active),
            "max_accounts": int(row.max_accounts or 0),
            "selection_weight": int(row.selection_weight or DEFAULT_SELECTION_WEIGHT),
            "health_status": row.health_status or DeveloperAppHealthStatus.HEALTHY.value,
            "last_health_check_at": row.last_health_check_at.isoformat() if row.last_health_check_at else None,
            "last_health_error": row.last_health_error,
            "last_health_latency_ms": row.last_health_latency_ms,
            "health_fail_count": int(row.health_fail_count or 0),
            "credentials_version": int(row.credentials_version or 1),
            "last_rotated_at": row.last_rotated_at.isoformat() if row.last_rotated_at else None,
            "notes": row.notes,
        }

    @staticmethod
    def _env_credentials_or_error() -> DeveloperAppCredentials:
        if not settings.api_id or not settings.api_hash:
            raise HTTPException(status_code=503, detail="未配置可用的 Telegram 开发者凭证")
        return DeveloperAppCredentials(
            app_id=None,
            api_id=int(settings.api_id),
            api_hash=str(settings.api_hash),
            credentials_version=0,
            source="env",
        )

    @staticmethod
    def _normalize_assignment_mode(raw_mode: Optional[str]) -> str:
        mode = (raw_mode or "").strip().lower()
        if mode not in {"round_robin", "weight"}:
            return DEFAULT_ASSIGNMENT_MODE
        return mode

    @staticmethod
    def _normalize_alert_tg_user_ids(raw_value: Optional[str]) -> tuple[str, List[int]]:
        normalized_ids: List[int] = []
        for chunk in str(raw_value or "").replace("\n", ",").split(","):
            value = chunk.strip()
            if not value:
                continue
            try:
                user_id = int(value)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"管理员通知 TG 用户 ID 无效: {value}") from exc
            if user_id > 0 and user_id not in normalized_ids:
                normalized_ids.append(user_id)
        serialized = ",".join(str(item) for item in normalized_ids)
        return serialized, normalized_ids

    @staticmethod
    def _is_row_healthy(row: TelegramDeveloperApp) -> bool:
        return bool(row.is_active) and (row.health_status or "") == DeveloperAppHealthStatus.HEALTHY.value

    @staticmethod
    def _decrypt_stored_api_hash(row: TelegramDeveloperApp) -> str:
        return decrypt_proxy_password(row.api_hash_encrypted)

    @staticmethod
    def _resolve_health_transition(
        *,
        previous_status: str,
        probe_status: str,
        next_fail_count: int,
        is_manual_check: bool,
    ) -> tuple[str, bool]:
        """Convert one probe result into a persisted health status."""
        normalized_previous = previous_status or DeveloperAppHealthStatus.HEALTHY.value
        if probe_status in {
            DeveloperAppHealthStatus.HEALTHY.value,
            DeveloperAppHealthStatus.DISABLED.value,
        }:
            return probe_status, False

        if normalized_previous == DeveloperAppHealthStatus.UNHEALTHY.value:
            return DeveloperAppHealthStatus.UNHEALTHY.value, False

        should_downgrade = int(next_fail_count) >= HEALTH_FAILURE_THRESHOLD
        if is_manual_check and not should_downgrade:
            return normalized_previous, True
        if should_downgrade:
            return DeveloperAppHealthStatus.UNHEALTHY.value, False
        return normalized_previous, True

    @staticmethod
    def _log_assignment_result(
        *,
        assignment_reason: str,
        assignment_context: str,
        user_id: int,
        account_id: Optional[str],
        selected_app_id: Optional[int],
        previous_app_id: Optional[int],
        assignment_mode: str,
        candidate_app_ids: Sequence[int],
        round_robin_cursor_before: Optional[int],
        round_robin_cursor_after: Optional[int],
    ) -> None:
        logger.info(
            "developer app assignment resolved: context={}, reason={}, user_id={}, account_id={}, selected_app_id={}, previous_app_id={}, assignment_mode={}, candidate_app_ids={}, round_robin_cursor_before={}, round_robin_cursor_after={}",
            assignment_context,
            assignment_reason,
            int(user_id),
            account_id,
            selected_app_id,
            previous_app_id,
            assignment_mode,
            list(candidate_app_ids),
            round_robin_cursor_before,
            round_robin_cursor_after,
        )

    @staticmethod
    def _log_manual_health_check(
        *,
        app_id: int,
        app_name: str,
        probe_status: str,
        current_status: str,
        health_fail_count: int,
        probe_failed_without_downgrade: bool,
        migration_executed: bool,
        migrated_count: int,
        stalled_count: int,
        last_health_error: Optional[str],
        actor: str,
        ip_address: Optional[str],
    ) -> None:
        log_fn = logger.info
        if probe_failed_without_downgrade or migration_executed or current_status == DeveloperAppHealthStatus.UNHEALTHY.value:
            log_fn = logger.warning
        log_fn(
            "developer app manual check: app_id={}, app_name={}, probe_status={}, current_status={}, health_fail_count={}, probe_failed_without_downgrade={}, migration_executed={}, migrated_count={}, stalled_count={}, last_health_error={}, actor={}, ip_address={}",
            int(app_id),
            app_name,
            probe_status,
            current_status,
            int(health_fail_count),
            bool(probe_failed_without_downgrade),
            bool(migration_executed),
            int(migrated_count),
            int(stalled_count),
            last_health_error,
            actor,
            ip_address,
        )

    async def _ensure_core_settings(self, session: Any) -> None:
        defaults = {
            DEFAULT_APP_SETTING_KEY: "",
            ASSIGNMENT_MODE_SETTING_KEY: DEFAULT_ASSIGNMENT_MODE,
            ASSIGNMENT_CURSOR_SETTING_KEY: "",
            ALERT_TG_USER_IDS_SETTING_KEY: "",
        }
        for key, value in defaults.items():
            row = await session.get(AppSetting, key)
            if row is None:
                session.add(AppSetting(key=key, value=value))

    async def _get_assignment_mode(self, session: Any) -> str:
        row = await session.get(AppSetting, ASSIGNMENT_MODE_SETTING_KEY)
        if row is None:
            await self._ensure_core_settings(session)
            return DEFAULT_ASSIGNMENT_MODE
        return self._normalize_assignment_mode(row.value)

    async def _set_assignment_mode(self, session: Any, mode: str) -> str:
        normalized = self._normalize_assignment_mode(mode)
        row = await session.get(AppSetting, ASSIGNMENT_MODE_SETTING_KEY)
        if row is None:
            session.add(AppSetting(key=ASSIGNMENT_MODE_SETTING_KEY, value=normalized))
        else:
            row.value = normalized
        return normalized

    async def _get_round_robin_cursor(self, session: Any) -> Optional[int]:
        row = await session.get(AppSetting, ASSIGNMENT_CURSOR_SETTING_KEY)
        if row is None:
            return None
        value = (row.value or "").strip()
        if not value:
            return None
        try:
            return int(value)
        except Exception:
            return None

    async def _set_round_robin_cursor(self, session: Any, app_id: Optional[int]) -> None:
        row = await session.get(AppSetting, ASSIGNMENT_CURSOR_SETTING_KEY)
        value = str(int(app_id)) if app_id is not None else ""
        if row is None:
            session.add(AppSetting(key=ASSIGNMENT_CURSOR_SETTING_KEY, value=value))
        else:
            row.value = value

    async def _get_alert_tg_user_ids_raw(self, session: Any) -> str:
        row = await session.get(AppSetting, ALERT_TG_USER_IDS_SETTING_KEY)
        if row is None:
            await self._ensure_core_settings(session)
            return ""
        return (row.value or "").strip()

    async def _set_alert_tg_user_ids_raw(self, session: Any, raw_value: str) -> List[int]:
        serialized, ids = self._normalize_alert_tg_user_ids(raw_value)
        row = await session.get(AppSetting, ALERT_TG_USER_IDS_SETTING_KEY)
        if row is None:
            session.add(AppSetting(key=ALERT_TG_USER_IDS_SETTING_KEY, value=serialized))
        else:
            row.value = serialized
        return ids

    async def get_assignment_settings(self) -> Dict[str, Any]:
        async with get_async_session() as session:
            await self._ensure_core_settings(session)
            mode = await self._get_assignment_mode(session)
            raw_alert_ids = await self._get_alert_tg_user_ids_raw(session)
            _, alert_ids = self._normalize_alert_tg_user_ids(raw_alert_ids)
            default_app_id = await self.get_default_app_id(session)
            default_app_name: Optional[str] = None
            default_app_active = False
            if default_app_id is not None:
                app_row = await session.get(TelegramDeveloperApp, int(default_app_id))
                if app_row is not None:
                    default_app_name = app_row.app_name
                    default_app_active = bool(app_row.is_active)
            return {
                "assignment_mode": mode,
                "alert_tg_user_ids": alert_ids,
                "alert_tg_user_ids_text": raw_alert_ids,
                "default_developer_app_id": default_app_id,
                "default_developer_app_name": default_app_name,
                "default_developer_app_active": default_app_active,
            }

    async def update_assignment_settings(
        self,
        *,
        assignment_mode: str,
        alert_tg_user_ids: str,
    ) -> Dict[str, Any]:
        async with get_async_session() as session:
            await self._ensure_core_settings(session)
            old_mode = await self._get_assignment_mode(session)
            old_alert_raw = await self._get_alert_tg_user_ids_raw(session)
            new_mode = await self._set_assignment_mode(session, assignment_mode)
            alert_ids = await self._set_alert_tg_user_ids_raw(session, alert_tg_user_ids)
            await session.commit()
            return {
                "old_assignment_mode": old_mode,
                "new_assignment_mode": new_mode,
                "old_alert_tg_user_ids_text": old_alert_raw,
                "new_alert_tg_user_ids_text": ",".join(str(item) for item in alert_ids),
                "alert_tg_user_ids": alert_ids,
            }

    async def get_alert_recipient_ids(self) -> List[int]:
        async with get_async_session() as session:
            raw_value = await self._get_alert_tg_user_ids_raw(session)
        _, ids = self._normalize_alert_tg_user_ids(raw_value)
        return ids

    async def _account_usage_map(
        self,
        session: Any,
        *,
        exclude_account_id: Optional[str] = None,
    ) -> Dict[int, int]:
        stmt = select(Account.developer_app_id, func.count(Account.account_id)).where(Account.developer_app_id.is_not(None))
        if exclude_account_id:
            stmt = stmt.where(Account.account_id != str(exclude_account_id))
        stmt = stmt.group_by(Account.developer_app_id)
        rows = (await session.execute(stmt)).all()
        return {int(row[0]): int(row[1]) for row in rows if row[0] is not None}

    async def _is_capacity_available(
        self,
        session: Any,
        app_id: int,
        *,
        exclude_account_id: Optional[str] = None,
    ) -> bool:
        app = await session.get(TelegramDeveloperApp, int(app_id))
        if not app or not app.is_active:
            return False
        if not self._is_row_healthy(app):
            return False
        if int(app.max_accounts or 0) <= 0:
            return True

        query = select(func.count(Account.account_id)).where(Account.developer_app_id == int(app_id))
        if exclude_account_id:
            query = query.where(Account.account_id != str(exclude_account_id))
        usage = int((await session.execute(query)).scalar() or 0)
        return usage < int(app.max_accounts)

    async def _list_assignable_candidates(
        self,
        session: Any,
        *,
        exclude_account_id: Optional[str] = None,
        disallowed_app_ids: Optional[Iterable[int]] = None,
    ) -> List[Dict[str, Any]]:
        blocked = {int(item) for item in (disallowed_app_ids or [])}
        usage_map = await self._account_usage_map(session, exclude_account_id=exclude_account_id)
        rows = (
            await session.execute(
                select(TelegramDeveloperApp)
                .where(TelegramDeveloperApp.is_active.is_(True))
                .order_by(TelegramDeveloperApp.id.asc())
            )
        ).scalars().all()
        candidates: List[Dict[str, Any]] = []
        for row in rows:
            if int(row.id) in blocked:
                continue
            if not self._is_row_healthy(row):
                continue
            usage = int(usage_map.get(int(row.id), 0))
            if int(row.max_accounts or 0) > 0 and usage >= int(row.max_accounts or 0):
                continue
            candidates.append({
                "row": row,
                "usage": usage,
                "weight": int(row.selection_weight or DEFAULT_SELECTION_WEIGHT),
            })
        return candidates

    async def _pick_weight_candidate(self, candidates: Sequence[Dict[str, Any]]) -> Optional[int]:
        if not candidates:
            return None
        picked = sorted(
            candidates,
            key=lambda item: (
                -int(item["weight"]),
                int(item["usage"]),
                int(item["row"].id),
            ),
        )[0]
        return int(picked["row"].id)

    async def _pick_round_robin_candidate(
        self,
        session: Any,
        candidates: Sequence[Dict[str, Any]],
    ) -> tuple[Optional[int], Optional[int], Optional[int]]:
        if not candidates:
            return None, None, None
        candidate_ids = sorted(int(item["row"].id) for item in candidates)
        cursor_before = await self._get_round_robin_cursor(session)
        if cursor_before is None:
            selected = candidate_ids[0]
        elif cursor_before not in candidate_ids:
            fallback = await self._pick_weight_candidate(candidates)
            selected = int(fallback) if fallback is not None else candidate_ids[0]
        else:
            selected = next((app_id for app_id in candidate_ids if app_id > cursor_before), candidate_ids[0])
        await self._set_round_robin_cursor(session, selected)
        return selected, cursor_before, selected

    async def _resolve_assignable_app_id_with_session(
        self,
        session: Any,
        *,
        user_id: int,
        preferred_app_id: Optional[int] = None,
        exclude_account_id: Optional[str] = None,
        disallowed_app_ids: Optional[Iterable[int]] = None,
        assignment_context: str = ASSIGNMENT_CONTEXT_NEW,
        existing_app_id: Optional[int] = None,
    ) -> Optional[int]:
        blocked = {int(item) for item in (disallowed_app_ids or [])}
        assignment_mode = await self._get_assignment_mode(session)

        async def _candidate_available(app_id: Optional[int]) -> Optional[int]:
            if app_id is None:
                return None
            if int(app_id) in blocked:
                return None
            if await self._is_capacity_available(session, int(app_id), exclude_account_id=exclude_account_id):
                return int(app_id)
            return None

        candidates = await self._list_assignable_candidates(
            session,
            exclude_account_id=exclude_account_id,
            disallowed_app_ids=blocked,
        )
        candidate_app_ids = [int(item["row"].id) for item in candidates]
        cursor_before: Optional[int] = None
        cursor_after: Optional[int] = None

        chosen = await _candidate_available(preferred_app_id)
        if chosen is not None:
            self._log_assignment_result(
                assignment_reason="user_preferred",
                assignment_context=assignment_context,
                user_id=int(user_id),
                account_id=str(exclude_account_id) if exclude_account_id else None,
                selected_app_id=int(chosen),
                previous_app_id=int(existing_app_id) if existing_app_id is not None else None,
                assignment_mode=assignment_mode,
                candidate_app_ids=candidate_app_ids,
                round_robin_cursor_before=None,
                round_robin_cursor_after=None,
            )
            return chosen

        user_preferred = await self.get_user_preferred_app_id(session, int(user_id))
        chosen = await _candidate_available(user_preferred)
        if chosen is not None:
            self._log_assignment_result(
                assignment_reason="user_preferred",
                assignment_context=assignment_context,
                user_id=int(user_id),
                account_id=str(exclude_account_id) if exclude_account_id else None,
                selected_app_id=int(chosen),
                previous_app_id=int(existing_app_id) if existing_app_id is not None else None,
                assignment_mode=assignment_mode,
                candidate_app_ids=candidate_app_ids,
                round_robin_cursor_before=None,
                round_robin_cursor_after=None,
            )
            return chosen

        if candidates:
            if assignment_mode == "weight":
                chosen = await self._pick_weight_candidate(candidates)
            else:
                chosen, cursor_before, cursor_after = await self._pick_round_robin_candidate(session, candidates)
                if chosen is None:
                    chosen = await self._pick_weight_candidate(candidates)
            if chosen is not None:
                self._log_assignment_result(
                    assignment_reason="weight" if assignment_mode == "weight" else "round_robin",
                    assignment_context=assignment_context,
                    user_id=int(user_id),
                    account_id=str(exclude_account_id) if exclude_account_id else None,
                    selected_app_id=int(chosen),
                    previous_app_id=int(existing_app_id) if existing_app_id is not None else None,
                    assignment_mode=assignment_mode,
                    candidate_app_ids=candidate_app_ids,
                    round_robin_cursor_before=cursor_before,
                    round_robin_cursor_after=cursor_after,
                )
                return int(chosen)

        if assignment_context == ASSIGNMENT_CONTEXT_EXISTING_REASSIGN:
            chosen = await _candidate_available(existing_app_id)
            if chosen is not None:
                self._log_assignment_result(
                    assignment_reason="existing_account_fallback",
                    assignment_context=assignment_context,
                    user_id=int(user_id),
                    account_id=str(exclude_account_id) if exclude_account_id else None,
                    selected_app_id=int(chosen),
                    previous_app_id=int(existing_app_id) if existing_app_id is not None else None,
                    assignment_mode=assignment_mode,
                    candidate_app_ids=candidate_app_ids,
                    round_robin_cursor_before=None,
                    round_robin_cursor_after=None,
                )
                return chosen

        default_app_id = await self.get_default_app_id(session)
        chosen = await _candidate_available(default_app_id)
        if chosen is not None:
            self._log_assignment_result(
                assignment_reason="default_fallback",
                assignment_context=assignment_context,
                user_id=int(user_id),
                account_id=str(exclude_account_id) if exclude_account_id else None,
                selected_app_id=int(chosen),
                previous_app_id=int(existing_app_id) if existing_app_id is not None else None,
                assignment_mode=assignment_mode,
                candidate_app_ids=candidate_app_ids,
                round_robin_cursor_before=None,
                round_robin_cursor_after=None,
            )
            return chosen

        active_count = int(
            (await session.execute(
                select(func.count(TelegramDeveloperApp.id)).where(TelegramDeveloperApp.is_active.is_(True))
            )).scalar()
            or 0
        )
        if active_count > 0:
            raise HTTPException(status_code=409, detail="当前没有健康且有容量的开发者应用，请联系管理员检查凭证池")
        return None

    async def resolve_assignable_app_id(
        self,
        *,
        user_id: int,
        preferred_app_id: Optional[int] = None,
        exclude_account_id: Optional[str] = None,
        disallowed_app_ids: Optional[Iterable[int]] = None,
        assignment_context: str = ASSIGNMENT_CONTEXT_NEW,
        existing_app_id: Optional[int] = None,
    ) -> Optional[int]:
        async with get_async_session() as session:
            return await self._resolve_assignable_app_id_with_session(
                session,
                user_id=int(user_id),
                preferred_app_id=preferred_app_id,
                exclude_account_id=exclude_account_id,
                disallowed_app_ids=disallowed_app_ids,
                assignment_context=assignment_context,
                existing_app_id=existing_app_id,
            )

    async def ensure_env_default_app(self) -> Optional[int]:
        if not settings.api_id or not settings.api_hash:
            return None

        encrypted_hash = encrypt_proxy_password(settings.api_hash)

        async with get_async_session() as session:
            await self._ensure_core_settings(session)
            result = await session.execute(
                select(TelegramDeveloperApp).where(TelegramDeveloperApp.api_id == int(settings.api_id)).limit(1)
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = TelegramDeveloperApp(
                    app_name="env-default",
                    api_id=int(settings.api_id),
                    api_hash_encrypted=encrypted_hash,
                    is_active=True,
                    max_accounts=0,
                    selection_weight=DEFAULT_SELECTION_WEIGHT,
                    health_status=DeveloperAppHealthStatus.HEALTHY.value,
                    health_fail_count=0,
                    credentials_version=1,
                    notes="自动从环境变量初始化",
                )
                session.add(row)
                await session.flush()
            else:
                try:
                    current_hash = self._decrypt_stored_api_hash(row)
                except Exception as exc:
                    logger.warning(
                        "developer_app_hash_decrypt_failed: app_id={}, app_name={}, context=ensure_env_default_app, error={}",
                        row.id,
                        row.app_name,
                        exc,
                    )
                else:
                    if current_hash != str(settings.api_hash):
                        logger.warning(
                            "env_default_hash_mismatch_detected: app_id={}, app_name={}, context=ensure_env_default_app",
                            row.id,
                            row.app_name,
                        )
                row.selection_weight = int(row.selection_weight or DEFAULT_SELECTION_WEIGHT)
                row.health_status = (
                    DeveloperAppHealthStatus.HEALTHY.value if row.is_active else DeveloperAppHealthStatus.DISABLED.value
                )
                if not row.is_active:
                    row.is_active = True
                    row.health_status = DeveloperAppHealthStatus.HEALTHY.value

            default_row = await session.get(AppSetting, DEFAULT_APP_SETTING_KEY)
            if default_row is None:
                session.add(AppSetting(key=DEFAULT_APP_SETTING_KEY, value=str(row.id)))
            elif not (default_row.value or "").strip():
                default_row.value = str(row.id)

            await session.commit()
            return int(row.id)

    async def get_default_app_id(self, session: Any) -> Optional[int]:
        setting = await session.get(AppSetting, DEFAULT_APP_SETTING_KEY)
        if setting and (setting.value or "").strip():
            try:
                app_id = int(setting.value.strip())
                row = await session.get(TelegramDeveloperApp, app_id)
                if row and row.is_active:
                    return app_id
            except Exception:
                pass

        result = await session.execute(
            select(TelegramDeveloperApp.id)
            .where(TelegramDeveloperApp.is_active.is_(True))
            .order_by(TelegramDeveloperApp.id.asc())
            .limit(1)
        )
        candidate = result.scalar_one_or_none()
        if candidate is None:
            return None

        if setting is None:
            session.add(AppSetting(key=DEFAULT_APP_SETTING_KEY, value=str(candidate)))
        else:
            setting.value = str(candidate)
        return int(candidate)

    async def get_user_preferred_app_id(self, session: Any, user_id: int) -> Optional[int]:
        row = await session.get(AppSetting, _user_app_key(user_id))
        if not row:
            return None
        value = (row.value or "").strip()
        if not value:
            return None
        try:
            app_id = int(value)
        except Exception:
            return None
        app = await session.get(TelegramDeveloperApp, app_id)
        if not app or not app.is_active:
            return None
        return app_id

    async def set_user_preferred_app_id(self, user_id: int, app_id: Optional[int]) -> Dict[str, Optional[int]]:
        async with get_async_session() as session:
            key = _user_app_key(user_id)
            row = await session.get(AppSetting, key)
            old_app_id: Optional[int] = None
            if row and (row.value or "").strip():
                try:
                    old_app_id = int((row.value or "").strip())
                except Exception:
                    old_app_id = None
            if app_id is None:
                if row is not None:
                    await session.delete(row)
                await session.commit()
                return {"old_app_id": old_app_id, "new_app_id": None}

            app = await session.get(TelegramDeveloperApp, int(app_id))
            if not app:
                raise HTTPException(status_code=404, detail="开发者应用不存在")
            if row is None:
                session.add(AppSetting(key=key, value=str(int(app_id))))
            else:
                row.value = str(int(app_id))
            await session.commit()
            return {"old_app_id": old_app_id, "new_app_id": int(app_id)}

    async def resolve_credentials(
        self,
        *,
        session: Any,
        developer_app_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> DeveloperAppCredentials:
        target_id: Optional[int] = int(developer_app_id) if developer_app_id else None

        if target_id is None and user_id is not None:
            target_id = await self.get_user_preferred_app_id(session, int(user_id))

        if target_id is None:
            target_id = await self.get_default_app_id(session)

        explicit_app_requested = developer_app_id is not None
        if target_id is not None:
            row = await session.get(TelegramDeveloperApp, int(target_id))
            if row and row.is_active and self._is_row_healthy(row):
                try:
                    api_hash = decrypt_proxy_password(row.api_hash_encrypted)
                except ValueError as exc:
                    logger.error(
                        "开发者应用凭证解密失败: app_id={}, app_name={}, error={}",
                        row.id,
                        row.app_name,
                        exc,
                    )
                    raise HTTPException(status_code=503, detail="开发者应用凭证异常，请联系管理员重新配置") from exc
                return DeveloperAppCredentials(
                    app_id=int(row.id),
                    api_id=int(row.api_id),
                    api_hash=api_hash,
                    credentials_version=int(row.credentials_version or 1),
                    source="db",
                )
            if explicit_app_requested:
                if row is None:
                    raise HTTPException(status_code=404, detail="开发者应用不存在")
                if not row.is_active:
                    raise HTTPException(status_code=400, detail="开发者应用未启用")
                raise HTTPException(status_code=400, detail="开发者应用当前不健康，请稍后重试或联系管理员")

        return self._env_credentials_or_error()

    async def resolve_credentials_for_account(self, account_id: str) -> DeveloperAppCredentials:
        async with get_async_session() as session:
            result = await session.execute(
                select(Account.developer_app_id, Account.user_id)
                .where(Account.account_id == account_id)
                .limit(1)
            )
            row = result.first()
            if not row:
                raise HTTPException(status_code=404, detail="账号不存在")
            return await self.resolve_credentials(
                session=session,
                developer_app_id=row.developer_app_id,
                user_id=row.user_id,
            )

    async def choose_login_credentials_for_user(
        self,
        user_id: int,
        *,
        existing_tg_user_id: Optional[int] = None,
    ) -> DeveloperAppCredentials:
        preferred_app_id: Optional[int] = None
        exclude_account_id: Optional[str] = None
        existing_account: Optional[Account] = None
        async with get_async_session() as session:
            if existing_tg_user_id is not None:
                existing_account = (
                    await session.execute(
                        select(Account)
                        .where(
                            Account.user_id == int(user_id),
                            Account.tg_user_id == int(existing_tg_user_id),
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if existing_account is not None:
                    preferred_app_id = None
                    exclude_account_id = existing_account.account_id

            assignable_app_id = await self._resolve_assignable_app_id_with_session(
                session,
                user_id=int(user_id),
                preferred_app_id=preferred_app_id,
                exclude_account_id=exclude_account_id,
                assignment_context=(
                    ASSIGNMENT_CONTEXT_EXISTING_REASSIGN
                    if existing_account is not None
                    else ASSIGNMENT_CONTEXT_NEW
                ),
                existing_app_id=int(existing_account.developer_app_id) if existing_account and existing_account.developer_app_id is not None else None,
            )
            return await self.resolve_credentials(
                session=session,
                developer_app_id=assignable_app_id,
                user_id=user_id,
            )

    async def list_apps(self) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            await self._ensure_core_settings(session)
            rows = (
                await session.execute(
                    select(TelegramDeveloperApp).order_by(TelegramDeveloperApp.id.asc())
                )
            ).scalars().all()
            default_id = await self.get_default_app_id(session)
            usage_map = await self._account_usage_map(session)

            data: List[Dict[str, Any]] = []
            for row in rows:
                data.append(
                    {
                        "id": int(row.id),
                        "app_name": row.app_name,
                        "api_id": int(row.api_id),
                        "is_active": bool(row.is_active),
                        "max_accounts": int(row.max_accounts or 0),
                        "selection_weight": int(row.selection_weight or DEFAULT_SELECTION_WEIGHT),
                        "health_status": row.health_status or DeveloperAppHealthStatus.HEALTHY.value,
                        "last_health_check_at": row.last_health_check_at.isoformat() if row.last_health_check_at else None,
                        "last_health_error": row.last_health_error,
                        "last_health_latency_ms": row.last_health_latency_ms,
                        "health_fail_count": int(row.health_fail_count or 0),
                        "credentials_version": int(row.credentials_version or 1),
                        "last_rotated_at": row.last_rotated_at.isoformat() if row.last_rotated_at else None,
                        "notes": row.notes,
                        "is_default": int(row.id) == int(default_id) if default_id is not None else False,
                        "account_usage": int(usage_map.get(int(row.id), 0)),
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    }
                )
            return data

    async def create_app(
        self,
        *,
        app_name: str,
        api_id: int,
        api_hash: str,
        is_active: bool = True,
        max_accounts: int = 0,
        selection_weight: int = DEFAULT_SELECTION_WEIGHT,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        app_name = (app_name or "").strip()
        if not app_name:
            raise HTTPException(status_code=400, detail="应用名称不能为空")
        if not api_hash:
            raise HTTPException(status_code=400, detail="API_HASH 不能为空")

        encrypted_hash = encrypt_proxy_password(api_hash.strip())

        async with get_async_session() as session:
            await self._ensure_core_settings(session)
            existing = await session.execute(
                select(TelegramDeveloperApp.id).where(TelegramDeveloperApp.api_id == int(api_id)).limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                raise HTTPException(status_code=400, detail="该 API_ID 已存在")

            row = TelegramDeveloperApp(
                app_name=app_name,
                api_id=int(api_id),
                api_hash_encrypted=encrypted_hash,
                is_active=bool(is_active),
                max_accounts=max(0, int(max_accounts or 0)),
                selection_weight=max(1, int(selection_weight or DEFAULT_SELECTION_WEIGHT)),
                health_status=(
                    DeveloperAppHealthStatus.HEALTHY.value
                    if bool(is_active)
                    else DeveloperAppHealthStatus.DISABLED.value
                ),
                health_fail_count=0,
                credentials_version=1,
                notes=(notes or "").strip() or None,
            )
            session.add(row)
            await session.flush()

            default_row = await session.get(AppSetting, DEFAULT_APP_SETTING_KEY)
            if default_row is None:
                session.add(AppSetting(key=DEFAULT_APP_SETTING_KEY, value=str(row.id)))

            await session.commit()
            return self._snapshot_app(row)

    async def update_app(
        self,
        app_id: int,
        *,
        app_name: Optional[str] = None,
        api_hash: Optional[str] = None,
        is_active: Optional[bool] = None,
        max_accounts: Optional[int] = None,
        selection_weight: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with get_async_session() as session:
            row = await session.get(TelegramDeveloperApp, int(app_id))
            if not row:
                raise HTTPException(status_code=404, detail="开发者应用不存在")

            old_value = self._snapshot_app(row)
            rotated_accounts = 0
            if app_name is not None:
                normalized = app_name.strip()
                if not normalized:
                    raise HTTPException(status_code=400, detail="应用名称不能为空")
                row.app_name = normalized
            if api_hash is not None:
                normalized_hash = api_hash.strip()
                if not normalized_hash:
                    raise HTTPException(status_code=400, detail="API_HASH 不能为空")
                try:
                    current_hash = self._decrypt_stored_api_hash(row)
                except Exception as exc:
                    logger.warning(
                        "developer_app_hash_decrypt_failed: app_id={}, app_name={}, context=update_app, error={}",
                        row.id,
                        row.app_name,
                        exc,
                    )
                    raise HTTPException(status_code=400, detail="无法确认旧的 API_HASH，请人工重建或重新录入该开发者应用") from exc

                if current_hash != normalized_hash:
                    row.api_hash_encrypted = encrypt_proxy_password(normalized_hash)
                    now = datetime.now()
                    row.credentials_version = int(row.credentials_version or 1) + 1
                    row.last_rotated_at = now
                    logger.warning(
                        "developer_app_api_hash_updated_without_forcing_reauth: app_id={}, app_name={}",
                        row.id,
                        row.app_name,
                    )
            if is_active is not None:
                row.is_active = bool(is_active)
                if not row.is_active:
                    row.health_status = DeveloperAppHealthStatus.DISABLED.value
                elif (row.health_status or "") == DeveloperAppHealthStatus.DISABLED.value:
                    row.health_status = DeveloperAppHealthStatus.HEALTHY.value
                    row.health_fail_count = 0
                    row.last_health_error = None
            if max_accounts is not None:
                row.max_accounts = max(0, int(max_accounts))
            if selection_weight is not None:
                row.selection_weight = max(1, int(selection_weight))
            if notes is not None:
                row.notes = notes.strip() or None

            await session.commit()
            new_value = self._snapshot_app(row)
            return {
                **self._snapshot_app(row),
                "rotated_accounts": rotated_accounts,
                "old_value": old_value,
                "new_value": new_value,
            }

    async def set_default_app(self, app_id: int) -> Dict[str, Optional[int]]:
        async with get_async_session() as session:
            await self._ensure_core_settings(session)
            row = await session.get(TelegramDeveloperApp, int(app_id))
            if not row:
                raise HTTPException(status_code=404, detail="开发者应用不存在")
            if not row.is_active:
                raise HTTPException(status_code=400, detail="开发者应用未启用，不能设为默认")

            setting = await session.get(AppSetting, DEFAULT_APP_SETTING_KEY)
            old_default_id = None
            if setting and (setting.value or "").strip():
                try:
                    old_default_id = int((setting.value or "").strip())
                except Exception:
                    old_default_id = None
            if setting is None:
                session.add(AppSetting(key=DEFAULT_APP_SETTING_KEY, value=str(int(app_id))))
            else:
                setting.value = str(int(app_id))
            await session.commit()
            return {
                "old_default_app_id": old_default_id,
                "new_default_app_id": int(app_id),
            }

    async def _probe_app(self, row: TelegramDeveloperApp) -> tuple[str, Optional[str], Optional[int]]:
        if not row.is_active:
            return DeveloperAppHealthStatus.DISABLED.value, None, None

        start = time.perf_counter()
        client: Optional[TelegramClient] = None
        try:
            api_hash = decrypt_proxy_password(row.api_hash_encrypted)
            client = TelegramClient(
                StringSession(),
                api_id=int(row.api_id),
                api_hash=api_hash,
                timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
                connection_retries=1,
                retry_delay=1,
                auto_reconnect=False,
            )
            await client.connect()
            await client(GetConfigRequest())
            latency_ms = int((time.perf_counter() - start) * 1000)
            return DeveloperAppHealthStatus.HEALTHY.value, None, latency_ms
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            log_fn = logger.warning
            if isinstance(exc, ValueError):
                log_fn = logger.error
            log_fn(
                "开发者应用健康检查失败: app_id={}, app_name={}, error={}",
                row.id,
                row.app_name,
                exc,
            )
            return DeveloperAppHealthStatus.UNHEALTHY.value, f"{type(exc).__name__}: {exc}", latency_ms
        finally:
            await self._safe_disconnect_probe_client(client)

    @staticmethod
    async def _safe_disconnect_probe_client(client: Optional[TelegramClient]) -> None:
        if client is None:
            return
        with suppress(Exception):
            await client.disconnect()

        disconnected = getattr(client, "disconnected", None)
        if callable(disconnected):
            with suppress(Exception):
                disconnected = disconnected()
        if disconnected is None or not hasattr(disconnected, "__await__"):
            return

        with suppress(Exception):
            await asyncio.wait_for(disconnected, timeout=1)

    async def _append_health_audit(
        self,
        session: Any,
        *,
        actor: str,
        action: str,
        app_id: int,
        old_value: Dict[str, Any],
        new_value: Dict[str, Any],
        detail: Dict[str, Any],
        ip_address: Optional[str] = None,
    ) -> None:
        session.add(
            AdminAuditLog(
                actor=actor,
                action=action,
                target_type="developer_app",
                target_id=str(app_id),
                developer_app_id=int(app_id),
                old_value=old_value,
                new_value=new_value,
                detail=detail,
                ip_address=ip_address,
            )
        )

    async def _migrate_accounts_from_unhealthy_app(
        self,
        session: Any,
        *,
        app_id: int,
    ) -> tuple[List[str], List[str]]:
        rows = (
            await session.execute(
                select(Account)
                .where(Account.developer_app_id == int(app_id))
                .order_by(Account.updated_at.desc(), Account.created_at.desc())
            )
        ).scalars().all()
        migrated: List[str] = []
        stalled: List[str] = []
        for account in rows:
            try:
                target_app_id = await self._resolve_assignable_app_id_with_session(
                    session,
                    user_id=int(account.user_id),
                    preferred_app_id=None,
                    exclude_account_id=account.account_id,
                    disallowed_app_ids={int(app_id)},
                )
            except HTTPException as exc:
                logger.warning(
                    "开发者应用自动迁移失败，账号将标记为待处理: account_id={}, old_app_id={}, error={}",
                    account.account_id,
                    app_id,
                    exc.detail,
                )
                target_app_id = None
            if target_app_id is None:
                account.health_status = HealthStatus.OFFLINE.value
                account.reauth_required = False
                account.reauth_reason = DEVELOPER_APP_UNHEALTHY_REASON
                account.reauth_required_at = None
                stalled.append(account.account_id)
                continue
            target_app = await session.get(TelegramDeveloperApp, int(target_app_id))
            account.developer_app_id = int(target_app_id)
            account.developer_app_version = int(target_app.credentials_version or 1) if target_app else 1
            account.health_status = HealthStatus.OFFLINE.value
            account.reauth_required = False
            account.reauth_reason = None
            account.reauth_required_at = None
            migrated.append(account.account_id)
        return migrated, stalled

    async def _recoverable_stalled_account_ids(self, *, app_id: int) -> List[str]:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(Account.account_id).where(
                        Account.developer_app_id == int(app_id),
                        Account.health_status == HealthStatus.OFFLINE.value,
                        Account.reauth_required == False,
                        Account.reauth_reason == DEVELOPER_APP_UNHEALTHY_REASON,
                    )
                )
            ).scalars().all()
        return [str(account_id) for account_id in rows]

    @staticmethod
    def _is_online_health_status(status: Any) -> bool:
        value = status.value if hasattr(status, "value") else status
        return str(value or "").strip().lower() == HealthStatus.ONLINE.value

    async def _recover_stalled_accounts_from_recovered_app(
        self,
        app_id: int,
    ) -> tuple[List[str], List[str]]:
        from backend.bot.account.manager import get_account_manager

        account_ids = await self._recoverable_stalled_account_ids(app_id=int(app_id))
        manager = get_account_manager()
        recovered: List[str] = []
        unrecovered: List[str] = []
        for account_id in account_ids:
            try:
                status = await manager.health_check(account_id)
            except Exception as exc:
                logger.warning(
                    "开发者应用恢复后账号探测失败: app_id={}, account_id={}, error={}",
                    app_id,
                    account_id,
                    exc,
                )
                unrecovered.append(account_id)
                continue
            if self._is_online_health_status(status):
                recovered.append(account_id)
            else:
                unrecovered.append(account_id)
        return recovered, unrecovered

    async def _close_cached_clients(self, account_ids: Sequence[str]) -> None:
        if not account_ids:
            return
        try:
            from backend.bot.account.client_runtime import close_client
            from backend.bot.account.manager import get_account_manager

            manager = get_account_manager()
            for account_id in account_ids:
                try:
                    await close_client(manager, account_id)
                except Exception as exc:
                    logger.warning("关闭账号客户端失败: account_id={}, error={}", account_id, exc)
        except Exception as exc:
            logger.warning("清理账号客户端缓存失败: {}", exc)

    async def _notify_admins_for_health_change(self, result: DeveloperAppHealthCheckResult) -> List[int]:
        recipient_ids = await self.get_alert_recipient_ids()
        if not recipient_ids:
            return []
        from backend.bot.client_runtime.manager import ensure_manager_bot_ready

        if not await ensure_manager_bot_ready():
            logger.warning(
                "Manager Bot 当前未就绪，跳过本轮开发者应用告警发送: app_id={}",
                result.app_id,
            )
            return []

        migrated_count = len(result.migrated_account_ids)
        stalled_count = len(result.stalled_account_ids)
        if result.current_status == DeveloperAppHealthStatus.HEALTHY.value:
            title = "✅ 开发者应用已恢复"
            body = (
                f"应用：{result.app_name} (#{result.app_id})\n"
                f"状态：{result.current_status}\n"
                f"最近耗时：{result.latency_ms or '-'} ms\n"
                f"迁移账号数：{migrated_count}\n"
                f"待处理账号数：{stalled_count}"
            )
        else:
            body = (
                f"应用：{result.app_name} (#{result.app_id})\n"
                f"状态：{result.current_status}\n"
                f"最近错误：{result.error or '-'}\n"
                f"最近耗时：{result.latency_ms or '-'} ms\n"
                f"已自动迁移账号数：{migrated_count}\n"
                f"待处理账号数：{stalled_count}"
            )
            title = "⚠️ 开发者应用异常"

        message = f"{title}\n\n{body}"
        sent: List[int] = []
        try:
            from backend.bot.client_runtime.manager import bot_client

            for user_id in recipient_ids:
                try:
                    await bot_client.send_message(int(user_id), message)
                    sent.append(int(user_id))
                except Exception as exc:
                    logger.warning("发送开发者应用告警失败: user_id={}, app_id={}, error={}", user_id, result.app_id, exc)
        except Exception as exc:
            logger.warning("加载 Manager Bot 发送开发者应用告警失败: {}", exc)
        return sent

    async def check_app_health(
        self,
        app_id: int,
        *,
        actor: str = "system",
        ip_address: Optional[str] = None,
        notify_admins: bool = True,
        force_audit: bool = False,
    ) -> Dict[str, Any]:
        async with get_async_session() as session:
            row = await session.get(TelegramDeveloperApp, int(app_id))
            if not row:
                raise HTTPException(status_code=404, detail="开发者应用不存在")
            previous = self._snapshot_app(row)
            api_hash_encrypted = row.api_hash_encrypted
            app_name = row.app_name
            app_id_value = int(row.id)
            is_active = bool(row.is_active)

        temp_row = TelegramDeveloperApp(
            id=app_id_value,
            app_name=app_name,
            api_id=previous["api_id"],
            api_hash_encrypted=api_hash_encrypted,
            is_active=is_active,
        )
        probe_status, error, latency_ms = await self._probe_app(temp_row)
        checked_at = datetime.now()
        migrated_account_ids: List[str] = []
        stalled_account_ids: List[str] = []
        recovered_account_ids: List[str] = []
        unrecovered_account_ids: List[str] = []
        is_manual_check = actor != "system"
        should_recover_stalled_accounts = False

        async with get_async_session() as session:
            row = await session.get(TelegramDeveloperApp, int(app_id))
            if not row:
                raise HTTPException(status_code=404, detail="开发者应用不存在")
            previous_status = row.health_status or DeveloperAppHealthStatus.HEALTHY.value
            next_fail_count = (
                0
                if probe_status in {DeveloperAppHealthStatus.HEALTHY.value, DeveloperAppHealthStatus.DISABLED.value}
                else int(row.health_fail_count or 0) + 1
            )
            current_status, probe_failed_without_downgrade = self._resolve_health_transition(
                previous_status=previous_status,
                probe_status=probe_status,
                next_fail_count=next_fail_count,
                is_manual_check=is_manual_check,
            )
            row.health_status = current_status
            row.last_health_check_at = checked_at
            row.last_health_error = error
            row.last_health_latency_ms = latency_ms
            row.health_fail_count = next_fail_count if probe_status == DeveloperAppHealthStatus.UNHEALTHY.value else 0

            if (
                current_status == DeveloperAppHealthStatus.UNHEALTHY.value
                and probe_status == DeveloperAppHealthStatus.UNHEALTHY.value
            ):
                migrated_account_ids, stalled_account_ids = await self._migrate_accounts_from_unhealthy_app(
                    session,
                    app_id=int(app_id),
                )
            should_recover_stalled_accounts = (
                previous_status == DeveloperAppHealthStatus.UNHEALTHY.value
                and current_status == DeveloperAppHealthStatus.HEALTHY.value
                and probe_status == DeveloperAppHealthStatus.HEALTHY.value
            )

            new_snapshot = self._snapshot_app(row)
            changed = previous_status != current_status
            if force_audit or changed or migrated_account_ids or stalled_account_ids:
                if current_status == DeveloperAppHealthStatus.HEALTHY.value and previous_status != current_status:
                    action = "system.developer_app_health_recovered"
                elif force_audit and actor != "system":
                    action = "admin.check_developer_app_health"
                else:
                    action = "system.developer_app_health_changed"
                await self._append_health_audit(
                    session,
                    actor=actor,
                    action=action,
                    app_id=int(app_id),
                    old_value=previous,
                    new_value=new_snapshot,
                    detail={
                        "previous_status": previous_status,
                        "probe_status": probe_status,
                        "current_status": current_status,
                        "last_health_error": error,
                        "last_health_latency_ms": latency_ms,
                        "health_fail_count": int(row.health_fail_count or 0),
                        "probe_failed_without_downgrade": probe_failed_without_downgrade,
                        "migrated_account_ids": migrated_account_ids,
                        "stalled_account_ids": stalled_account_ids,
                    },
                    ip_address=ip_address,
                )
            await session.commit()

        await self._close_cached_clients([*migrated_account_ids, *stalled_account_ids])
        if should_recover_stalled_accounts:
            recovered_account_ids, unrecovered_account_ids = (
                await self._recover_stalled_accounts_from_recovered_app(int(app_id))
            )
            if recovered_account_ids or unrecovered_account_ids:
                async with get_async_session() as session:
                    row = await session.get(TelegramDeveloperApp, int(app_id))
                    if row is not None:
                        await self._append_health_audit(
                            session,
                            actor=actor,
                            action="system.developer_app_accounts_recovered",
                            app_id=int(app_id),
                            old_value=previous,
                            new_value=self._snapshot_app(row),
                            detail={
                                "recovered_account_ids": recovered_account_ids,
                                "unrecovered_account_ids": unrecovered_account_ids,
                            },
                            ip_address=ip_address,
                        )
                        await session.commit()
        migration_executed = bool(migrated_account_ids or stalled_account_ids)
        result = DeveloperAppHealthCheckResult(
            app_id=int(app_id),
            app_name=app_name,
            previous_status=previous.get("health_status") or DeveloperAppHealthStatus.HEALTHY.value,
            probe_status=probe_status,
            current_status=current_status,
            checked_at=checked_at,
            latency_ms=latency_ms,
            error=error,
            migrated_account_ids=migrated_account_ids,
            stalled_account_ids=stalled_account_ids,
            notified_recipients=[],
            probe_ok=probe_status in {DeveloperAppHealthStatus.HEALTHY.value, DeveloperAppHealthStatus.DISABLED.value},
            status_changed=previous.get("health_status") != current_status,
            migration_executed=migration_executed,
            probe_failed_without_downgrade=probe_failed_without_downgrade,
            recovered_account_ids=recovered_account_ids,
            unrecovered_account_ids=unrecovered_account_ids,
        )
        if is_manual_check:
            self._log_manual_health_check(
                app_id=result.app_id,
                app_name=result.app_name,
                probe_status=result.probe_status,
                current_status=result.current_status,
                health_fail_count=int(next_fail_count),
                probe_failed_without_downgrade=result.probe_failed_without_downgrade,
                migration_executed=result.migration_executed,
                migrated_count=len(result.migrated_account_ids),
                stalled_count=len(result.stalled_account_ids),
                last_health_error=result.error,
                actor=actor,
                ip_address=ip_address,
            )
        if notify_admins and result.previous_status != result.current_status:
            result.notified_recipients = await self._notify_admins_for_health_change(result)
        return {
            "app_id": result.app_id,
            "app_name": result.app_name,
            "previous_status": result.previous_status,
            "probe_status": result.probe_status,
            "current_status": result.current_status,
            "checked_at": result.checked_at.isoformat(),
            "last_health_error": result.error,
            "last_health_latency_ms": result.latency_ms,
            "health_fail_count": next_fail_count,
            "migrated_account_ids": result.migrated_account_ids,
            "stalled_account_ids": result.stalled_account_ids,
            "notified_recipients": result.notified_recipients,
            "probe_ok": result.probe_ok,
            "status_changed": result.status_changed,
            "migration_executed": result.migration_executed,
            "probe_failed_without_downgrade": result.probe_failed_without_downgrade,
            "recovered_account_ids": result.recovered_account_ids,
            "unrecovered_account_ids": result.unrecovered_account_ids,
        }

    async def run_health_check_cycle(self) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(TelegramDeveloperApp.id)
                    .where(TelegramDeveloperApp.is_active.is_(True))
                    .order_by(TelegramDeveloperApp.id.asc())
                )
            ).scalars().all()
        results: List[Dict[str, Any]] = []
        for app_id in rows:
            try:
                results.append(await self.check_app_health(int(app_id), actor="system", notify_admins=True))
            except Exception as exc:
                logger.exception("执行开发者应用健康检查失败: app_id={}, error={}", app_id, exc)
        return results


_developer_app_service: Optional[DeveloperAppService] = None


def get_developer_app_service() -> DeveloperAppService:
    """Get singleton developer app service."""
    global _developer_app_service
    if _developer_app_service is None:
        _developer_app_service = DeveloperAppService()
    return _developer_app_service
