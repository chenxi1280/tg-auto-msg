"""Task management API routes."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from backend.database.schema.models import User
from backend.h5_backend.routers.auth import get_current_user
from backend.h5_backend.services.task.service import get_task_service
from backend.h5_backend.services.task.v2_payload import coerce_expected_revision
from backend.task_media.capture_service import (
    create_capture,
    get_capture_status,
)
from backend.task_media.mutation_service import delete_task_media

router = APIRouter(tags=["任务"])


def _expected_revision(payload: dict) -> int:
    value = payload.get("expected_revision")
    if value is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "EXPECTED_REVISION_REQUIRED",
                "message": "缺少 expected_revision",
            },
        )
    return coerce_expected_revision(value)


@router.get("/api/tasks")
async def get_tasks(current_user: User = Depends(get_current_user)):
    """获取当前用户的任务列表"""
    service = get_task_service()
    tasks = await service.list_tasks(current_user.id)
    return {"success": True, "data": tasks}


@router.get("/api/tasks/{task_id}")
async def get_task(task_id: str, current_user: User = Depends(get_current_user)):
    """获取单个任务详情"""
    service = get_task_service()
    task = await service.get_task_detail(task_id, current_user.id)
    return {"success": True, "data": task}


@router.post("/api/tasks")
async def create_task(task_data: dict, current_user: User = Depends(get_current_user)):
    """创建任务"""
    service = get_task_service()
    task_id = await service.create_task(task_data, current_user.id)
    return {"success": True, "data": {"task_id": task_id, "revision": 1}}


@router.put("/api/tasks/{task_id}")
async def update_task(
    task_id: str, task_data: dict, current_user: User = Depends(get_current_user)
):
    """更新任务"""
    service = get_task_service()
    revision = await service.update_task(task_id, task_data, current_user.id)
    return {"success": True, "data": {"revision": revision}}


@router.post("/api/tasks/{task_id}/media-captures")
async def create_task_media_capture(
    task_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
):
    """创建 Telegram Bot 媒体捕获入口。"""
    capture = await create_capture(
        task_id=task_id,
        user_id=current_user.id,
        expected_revision=_expected_revision(payload),
    )
    return {"success": True, "data": capture.__dict__}


@router.get("/api/tasks/{task_id}/media-captures/{capture_id}")
async def get_task_media_capture(
    task_id: str,
    capture_id: str,
    current_user: User = Depends(get_current_user),
):
    """读取 Telegram Bot 媒体捕获状态。"""
    data = await get_capture_status(
        task_id=task_id,
        capture_id=capture_id,
        user_id=current_user.id,
    )
    return {"success": True, "data": data}


@router.delete("/api/tasks/{task_id}/media")
async def clear_task_media(
    task_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
):
    """只清除任务媒体引用，不删除 Telegram 收藏夹原消息。"""
    revision = await delete_task_media(
        task_id=task_id,
        user_id=current_user.id,
        expected_revision=_expected_revision(payload),
    )
    return {"success": True, "data": {"revision": revision}}


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, current_user: User = Depends(get_current_user)):
    """删除任务"""
    service = get_task_service()
    await service.delete_task(task_id, current_user.id)
    return {"success": True}


@router.get("/api/tasks/{task_id}/logs")
async def get_task_logs(
    task_id: str, limit: int = 50, current_user: User = Depends(get_current_user)
):
    """获取任务日志"""
    service = get_task_service()
    logs = await service.list_task_logs(task_id, current_user.id, limit=limit)
    return {"success": True, "data": logs}


@router.post("/api/tasks/{task_id}/trigger")
async def trigger_task(task_id: str, current_user: User = Depends(get_current_user)):
    """手动执行一次任务。"""
    service = get_task_service()
    summary = await service.trigger_task_once(task_id, current_user.id)
    return {"success": True, "data": summary}


@router.post("/api/tasks/batch")
async def batch_update_tasks(
    task_ids: List[str],
    update_data: dict,
    current_user: User = Depends(get_current_user),
):
    """批量更新任务"""
    service = get_task_service()
    count = await service.batch_update_tasks(task_ids, update_data, current_user.id)
    return {"success": True, "count": count}
