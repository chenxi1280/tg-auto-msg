"""Task management API routes."""
from typing import List

from fastapi import APIRouter, Depends, File, Form, UploadFile

from backend.database.schema.models import User
from backend.h5_backend.routers.auth import get_current_user
from backend.h5_backend.services.task.service import get_task_service

router = APIRouter(tags=["任务"])


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
    return {"success": True, "data": {"task_id": task_id}}


@router.put("/api/tasks/{task_id}")
async def update_task(task_id: str, task_data: dict, current_user: User = Depends(get_current_user)):
    """更新任务"""
    service = get_task_service()
    await service.update_task(task_id, task_data, current_user.id)
    return {"success": True}


@router.post("/api/tasks/upload-media")
async def upload_task_media(
    account_id: str = Form(...),
    media: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传任务媒体到 Telegram（账号收藏夹），返回可持久引用的 media_file_id。"""
    service = get_task_service()
    data = await service.upload_media(account_id, current_user.id, media)
    return {"success": True, "data": data}


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, current_user: User = Depends(get_current_user)):
    """删除任务"""
    service = get_task_service()
    await service.delete_task(task_id, current_user.id)
    return {"success": True}


@router.get("/api/tasks/{task_id}/logs")
async def get_task_logs(task_id: str, limit: int = 50, current_user: User = Depends(get_current_user)):
    """获取任务日志"""
    service = get_task_service()
    logs = await service.list_task_logs(task_id, current_user.id, limit=limit)
    return {"success": True, "data": logs}


@router.post("/api/tasks/batch")
async def batch_update_tasks(task_ids: List[str], update_data: dict, current_user: User = Depends(get_current_user)):
    """批量更新任务"""
    service = get_task_service()
    count = await service.batch_update_tasks(task_ids, update_data, current_user.id)
    return {"success": True, "count": count}
