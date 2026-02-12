"""Task domain service for H5 API."""
from __future__ import annotations

from datetime import datetime
import io
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, select

from backend.bot.account.manager import get_account_manager
from backend.database.schema.models import Account, ScheduledMessageTask, TaskLog
from backend.database.runtime.session import get_async_session
from backend.h5_backend.dependencies import check_account_permission, check_task_permission
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


class TaskService:
    """Task business service."""

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
        now_ts = int(datetime.now().timestamp())

        normalize_targets(payload, fallback_task=None)
        validate_task_payload(payload, current_task=None)
        apply_system_strategy_fields(payload, account)
        ensure_initial_next_run(payload, now_ts, current_task=None)

        async with get_async_session() as session:
            task = ScheduledMessageTask(**payload)
            session.add(task)
            await session.commit()
            await session.refresh(task)
            return task.task_id

    async def update_task(self, task_id: str, task_data: dict, user_id: int) -> None:
        original_task = await check_task_permission(task_id, user_id)
        payload = dict(task_data or {})
        now_ts = int(datetime.now().timestamp())

        account = await self._resolve_account(payload, user_id, default_account_id=original_task.account_id)
        normalize_targets(payload, fallback_task=original_task)
        validate_task_payload(payload, current_task=original_task)
        apply_system_strategy_fields(payload, account)

        async with get_async_session() as session:
            task = await session.merge(original_task)
            was_enabled = bool(task.enabled)
            apply_update_payload(task, payload)
            ensure_initial_next_run(payload, now_ts, current_task=task, was_enabled=was_enabled)

            await session.commit()
            await session.refresh(task)

    async def delete_task(self, task_id: str, user_id: int) -> None:
        await check_task_permission(task_id, user_id)
        async with get_async_session() as session:
            await session.execute(delete(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id))
            await session.commit()

    async def list_task_logs(self, task_id: str, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        await check_task_permission(task_id, user_id)
        async with get_async_session() as session:
            result = await session.execute(
                select(TaskLog).where(TaskLog.task_id == task_id).order_by(TaskLog.send_at.desc()).limit(limit)
            )
            logs = result.scalars().all()
        return serialize_task_logs(logs)

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

                if task.enabled and task.next_run_at is None:
                    start_at_ts = int(task.start_at or 0)
                    task.next_run_at = max(now_ts, start_at_ts) if start_at_ts > 0 else now_ts
                count += 1

            if count > 0:
                await session.commit()
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
            raise HTTPException(status_code=400, detail="账号客户端不可用，请重新登录该账号")

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
