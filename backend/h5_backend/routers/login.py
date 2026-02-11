"""Login and account binding API routes."""
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse

from backend.database.models import User
from backend.h5_backend.routers.auth import get_current_user
from backend.h5_backend.services.login_service import get_login_service

router = APIRouter(tags=["登录"])


@router.post("/api/login/create")
async def create_login_session(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """创建新的登录会话（使用 Redis 存储状态）"""
    service = get_login_service()
    data = await service.create_login_session(current_user.id, background_tasks)
    return {"success": True, "data": data}


@router.get("/api/login/status")
async def get_login_status(login_id: str, current_user: User = Depends(get_current_user)):
    """获取登录状态（从 Redis 查询）"""
    service = get_login_service()
    return await service.get_login_status(login_id, current_user.id)


@router.get("/api/login/check")
async def check_login_status(current_user: User = Depends(get_current_user)):
    """检查 Userbot 登录状态"""
    service = get_login_service()
    data = await service.check_userbot_login()
    return {"success": True, "data": data}


@router.post("/api/login/bind")
async def bind_account(request: Request, current_user: User = Depends(get_current_user)):
    """绑定 Telegram 账号到当前系统用户"""
    service = get_login_service()
    data = await service.bind_account(request, current_user.id)
    return {"success": True, "message": "绑定成功", "data": data}


@router.get("/api/login/get-token")
async def get_existing_token():
    """[已弃用] 获取已登录 userbot 的 token。"""
    return JSONResponse({"success": False, "error": "接口已弃用，请使用系统登录"}, status_code=410)
