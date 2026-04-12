"""Task domain service for H5 API."""
from __future__ import annotations

from datetime import datetime
import io
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile
from loguru import logger
from sqlalchemy import delete, func, select

from backend.bot.account.manager import get_account_manager
from backend.database.schema.models import (
    Account,
    AppSetting,
    ScheduledMessageTask,
    TaskLog,
    TaskTriggerMode,
    TaskTriggerSource,
)
from backend.database.runtime.session import get_async_session
from backend.h5_backend.dependencies import check_account_permission, check_task_permission
from backend.h5_backend.services.licensing.service import require_account_task_permission
from backend.h5_backend.services.task.payload import (
    apply_system_strategy_fields,
    apply_update_payload,
    ensure_initial_next_run,
    normalize_targets,
    validate_task_payload,
)
from backend.h5_backend.services.task.serializers import (
    serialize_task_detail,
    serialize_task_list_item,
    serialize_task_logs,
)
from backend.h5_backend.services.task.helpers import (
    MAX_TASK_MEDIA_SIZE,
    build_telegram_media_ref,
    resolve_upload_media_type,
)
from backend.scheduler.core.task_runner import execute_task_once


class TaskService:
    """Task business service."""

    async def _sync_user_shortcut_keyboards(self, user_id: int) -> None:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(AppSetting.key).where(
                        AppSetting.key.like("tg_user_link:%"),
                        AppSetting.value == str(int(user_id)),
                    )
                )
            ).all()

        tg_user_ids: list[int] = []
        for (key,) in rows:
            try:
                tg_user_ids.append(int(str(key).split("tg_user_link:", 1)[1]))
            except Exception:
                continue

        if not tg_user_ids:
            return

        from backend.bot.onboarding import get_onboarding_service

        onboarding_service = get_onboarding_service()
        for tg_user_id in tg_user_ids:
            try:
                await onboarding_service.sync_home_reply_keyboard(int(tg_user_id))
            except Exception as exc:
                logger.warning(
                    "同步用户快捷键盘失败: user_id={}, tg_user_id={}, error={!r}",
                    user_id,
                    tg_user_id,
                    exc,
                )

    async def _validate_shortcut_constraints(
        self,
        session,
        *,
        user_id: int,
        payload: Dict[str, Any],
        current_task_id: Optional[str] = None,
    ) -> None:
        trigger_mode = str(payload.get("trigger_mode") or TaskTriggerMode.SCHEDULED.value).strip().lower()
        shortcut_slot = payload.get("shortcut_slot")

        if trigger_mode != TaskTriggerMode.MANUAL_SHORTCUT.value:
            payload["shortcut_slot"] = None
            payload["shortcut_label"] = None
            return

        total_stmt = select(func.count()).select_from(ScheduledMessageTask).where(
            ScheduledMessageTask.user_id == user_id,
            ScheduledMessageTask.trigger_mode == TaskTriggerMode.MANUAL_SHORTCUT.value,
        )
        if current_task_id:
            total_stmt = total_stmt.where(ScheduledMessageTask.task_id != current_task_id)
        manual_task_count = int((await session.execute(total_stmt)).scalar_one() or 0)
        if manual_task_count >= 3:
            raise HTTPException(status_code=400, detail="每个用户最多只能配置 3 个快捷任务")

        shortcut_label = str(payload.get("shortcut_label") or "").strip()
        if shortcut_label:
            duplicate_label_stmt = select(ScheduledMessageTask.task_id).where(
                ScheduledMessageTask.user_id == user_id,
                ScheduledMessageTask.trigger_mode == TaskTriggerMode.MANUAL_SHORTCUT.value,
                func.lower(ScheduledMessageTask.shortcut_label) == shortcut_label.lower(),
            )
            if current_task_id:
                duplicate_label_stmt = duplicate_label_stmt.where(ScheduledMessageTask.task_id != current_task_id)
            if (await session.execute(duplicate_label_stmt)).scalar_one_or_none() is not None:
                raise HTTPException(status_code=400, detail="手动任务按钮名称已存在，请换一个名称")

        occupied_slots_stmt = select(ScheduledMessageTask.shortcut_slot).where(
            ScheduledMessageTask.user_id == user_id,
            ScheduledMessageTask.trigger_mode == TaskTriggerMode.MANUAL_SHORTCUT.value,
            ScheduledMessageTask.shortcut_slot.is_not(None),
        )
        if current_task_id:
            occupied_slots_stmt = occupied_slots_stmt.where(ScheduledMessageTask.task_id != current_task_id)
        occupied_slots = {
            int(slot)
            for slot in (await session.execute(occupied_slots_stmt)).scalars().all()
            if slot is not None
        }

        if shortcut_slot is None:
            for candidate in (1, 2, 3):
                if candidate not in occupied_slots:
                    payload["shortcut_slot"] = candidate
                    return
            raise HTTPException(status_code=400, detail="快捷栏位置已满，请先删除一个手动任务后再试")

        shortcut_slot = int(shortcut_slot)
        if shortcut_slot in occupied_slots:
            raise HTTPException(status_code=400, detail=f"快捷栏位置 {shortcut_slot} 已被其他任务占用")
        payload["shortcut_slot"] = shortcut_slot

    async def list_tasks(self, user_id: int) -> List[Dict[str, Any]]:
        async with get_async_session() as session:
            query = (
                select(ScheduledMessageTask)
                .where(ScheduledMessageTask.user_id == user_id)
                .order_by(ScheduledMessageTask.created_at.desc())
            )
            result = await session.execute(query)
            tasks = result.scalars().all()
        return [serialize_task_list_item(task) for task in tasks]

    async def get_task_detail(self, task_id: str, user_id: int) -> Dict[str, Any]:
        task = await check_task_permission(task_id, user_id)
        return serialize_task_detail(task)

    async def create_task(self, task_data: dict, user_id: int) -> str:
        payload = dict(task_data or {})
        payload["user_id"] = user_id
        account = await self._resolve_account(payload, user_id)
        if account is not None:
            await require_account_task_permission(account.account_id, action_text="创建自动发送任务")
        now_ts = int(datetime.now().timestamp())

        normalize_targets(payload, fallback_task=None)
        validate_task_payload(payload, current_task=None)
        apply_system_strategy_fields(payload, account)
        ensure_initial_next_run(payload, now_ts, current_task=None)

        async with get_async_session() as session:
            await self._validate_shortcut_constraints(
                session,
                user_id=user_id,
                payload=payload,
            )
            task = ScheduledMessageTask(**payload)
            session.add(task)
            await session.commit()
            await session.refresh(task)
            created_task_id = task.task_id
        await self._sync_user_shortcut_keyboards(user_id)
        return created_task_id

    async def update_task(self, task_id: str, task_data: dict, user_id: int) -> None:
        original_task = await check_task_permission(task_id, user_id)
        payload = dict(task_data or {})
        now_ts = int(datetime.now().timestamp())

        account = await self._resolve_account(payload, user_id, default_account_id=original_task.account_id)
        if account is not None:
            await require_account_task_permission(account.account_id, action_text="保存自动发送任务")
        normalize_targets(payload, fallback_task=original_task)
        validate_task_payload(payload, current_task=original_task)
        apply_system_strategy_fields(payload, account)

        async with get_async_session() as session:
            await self._validate_shortcut_constraints(
                session,
                user_id=user_id,
                payload=payload,
                current_task_id=task_id,
            )
            task = await session.merge(original_task)
            was_enabled = bool(task.enabled)
            apply_update_payload(task, payload)
            ensure_initial_next_run(payload, now_ts, current_task=task, was_enabled=was_enabled)

            await session.commit()
            await session.refresh(task)
        await self._sync_user_shortcut_keyboards(user_id)

    async def delete_task(self, task_id: str, user_id: int) -> None:
        await check_task_permission(task_id, user_id)
        async with get_async_session() as session:
            await session.execute(delete(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id))
            await session.commit()
        await self._sync_user_shortcut_keyboards(user_id)

    async def list_task_logs(self, task_id: str, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        await check_task_permission(task_id, user_id)
        async with get_async_session() as session:
            result = await session.execute(
                select(TaskLog).where(TaskLog.task_id == task_id).order_by(TaskLog.send_at.desc()).limit(limit)
            )
            logs = result.scalars().all()
        return serialize_task_logs(logs)

    async def trigger_task_once(
        self,
        task_id: str,
        user_id: int,
        *,
        trigger_source: str = TaskTriggerSource.API_MANUAL.value,
    ) -> Dict[str, Any]:
        task = await check_task_permission(task_id, user_id)
        if not task.enabled:
            raise HTTPException(status_code=400, detail="任务已禁用，请启用后再手动执行")
        if task.account_id:
            await require_account_task_permission(task.account_id, action_text="手动执行任务")

        summary = await execute_task_once(
            task_id,
            trigger_source=trigger_source,
            advance_schedule=False,
            respect_schedule_constraints=False,
        )
        return summary.to_dict()

    async def list_manual_shortcuts(
        self,
        user_id: int,
        *,
        account_id: Optional[str] = None,
    ) -> List[ScheduledMessageTask]:
        async with get_async_session() as session:
            stmt = (
                select(ScheduledMessageTask)
                .where(
                    ScheduledMessageTask.user_id == user_id,
                    ScheduledMessageTask.enabled == True,
                    ScheduledMessageTask.trigger_mode == TaskTriggerMode.MANUAL_SHORTCUT.value,
                    ScheduledMessageTask.shortcut_slot.is_not(None),
                )
                .order_by(ScheduledMessageTask.shortcut_slot.asc(), ScheduledMessageTask.created_at.asc())
            )
            if account_id:
                stmt = stmt.where(ScheduledMessageTask.account_id == str(account_id))
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def batch_update_tasks(self, task_ids: List[str], update_data: dict, user_id: int) -> int:
        async with get_async_session() as session:
            now_ts = int(datetime.now().timestamp())
            count = 0
            for task_id in task_ids:
                result = await session.execute(
                    select(ScheduledMessageTask).where(
                        ScheduledMessageTask.task_id == task_id,
                        ScheduledMessageTask.user_id == user_id,
                    )
                )
                task = result.scalar_one_or_none()
                if not task:
                    continue

                for key, value in update_data.items():
                    if hasattr(task, key) and key not in {"user_id", "task_id"}:
                        setattr(task, key, value)

                if (
                    task.enabled
                    and task.next_run_at is None
                    and str(task.trigger_mode or TaskTriggerMode.SCHEDULED.value) == TaskTriggerMode.SCHEDULED.value
                ):
                    start_at_ts = int(task.start_at or 0)
                    task.next_run_at = max(now_ts, start_at_ts) if start_at_ts > 0 else now_ts
                count += 1

            if count > 0:
                await session.commit()
        if count > 0:
            await self._sync_user_shortcut_keyboards(user_id)
        return count

    async def upload_media(self, account_id: str, user_id: int, media: UploadFile) -> Dict[str, Any]:
        await check_account_permission(account_id, user_id)

        if not media.filename:
            raise HTTPException(status_code=400, detail="媒体文件名为空")

        media_type = resolve_upload_media_type(media)
        filename = media.filename
        account_manager = get_account_manager()
        client = await account_manager.get_client(account_id)
        if not client:
            raise HTTPException(status_code=400, detail="账号客户端不可用，请重新绑定该账号")

        total_size = 0
        raw_data = bytearray()
        try:
            while True:
                chunk = await media.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_TASK_MEDIA_SIZE:
                    max_mb = MAX_TASK_MEDIA_SIZE // (1024 * 1024)
                    raise HTTPException(status_code=400, detail=f"媒体文件过大，最大支持 {max_mb}MB")
                raw_data.extend(chunk)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"读取媒体文件失败: {exc}") from exc
        finally:
            await media.close()

        if total_size <= 0:
            raise HTTPException(status_code=400, detail="媒体文件为空")

        file_buffer = io.BytesIO(bytes(raw_data))
        file_buffer.name = filename

        try:
            sent_msg = await client.send_file("me", file=file_buffer, caption=f"[task-media] {filename}")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"上传到 Telegram 失败: {exc}") from exc

        media_ref = build_telegram_media_ref(account_id, int(sent_msg.id))
        return {
            "media_type": media_type.value,
            "media_file_id": media_ref,
            "filename": filename,
            "size": total_size,
            "storage": "telegram",
        }

    async def _resolve_account(
        self,
        payload: Dict[str, Any],
        user_id: int,
        default_account_id: Optional[str] = None,
    ) -> Optional[Account]:
        account_id = payload.get("account_id") or default_account_id
        if not account_id:
            return None
        return await check_account_permission(str(account_id), user_id)


_task_service: Optional[TaskService] = None


def get_task_service() -> TaskService:
    """Get singleton task service instance."""
    global _task_service
    if _task_service is None:
        _task_service = TaskService()
    return _task_service
