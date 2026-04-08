"""Login and account binding API routes."""
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse

from backend.database.schema.models import User
from backend.h5_backend.routers.auth import get_current_user
from backend.h5_backend.services.login.service import get_login_service

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


@router.post("/api/login/phone/create")
async def create_phone_login_session(current_user: User = Depends(get_current_user)):
    """创建手机号登录会话。"""
    service = get_login_service()
    data = await service.create_phone_login_session(current_user.id)
    return {"success": True, "data": data}


@router.post("/api/login/phone/send-code")
async def send_phone_login_code(request: Request, current_user: User = Depends(get_current_user)):
    """提交手机号并发送 Telegram 验证码。"""
    payload = await request.json()
    service = get_login_service()
    data = await service.submit_phone_number_data(
        login_id=(payload.get("login_id") or "").strip(),
        user_id=current_user.id,
        phone_number=payload.get("phone_number") or "",
    )
    return {"success": True, "data": data}


@router.post("/api/login/phone/code")
async def submit_phone_login_code(request: Request, current_user: User = Depends(get_current_user)):
    """提交 Telegram 验证码完成登录。"""
    payload = await request.json()
    service = get_login_service()
    data = await service.submit_phone_code_data(
        login_id=(payload.get("login_id") or "").strip(),
        user_id=current_user.id,
        code=payload.get("code") or "",
        input_mode="h5_api",
    )
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
    """[已弃用] 账号级绑定 Telegram 账号到当前系统用户。"""
    service = get_login_service()
    data = await service.bind_account(request, current_user.id)
    return {"success": True, "message": "绑定成功", "data": data}


@router.post("/api/login/bot-bind-link")
async def create_bot_bind_link(current_user: User = Depends(get_current_user)):
    """生成系统账号到 TG Bot 的一次性绑定链接。"""
    service = get_login_service()
    data = await service.create_system_bind_link(current_user.id)
    return {"success": True, "data": data}


@router.post("/api/login/password")
async def submit_login_password(request: Request, current_user: User = Depends(get_current_user)):
    """提交 Telegram 二步密码并完成登录"""
    service = get_login_service()
    data = await service.submit_password(request, current_user.id)
    return {"success": True, "message": "登录成功", "data": data}


@router.get("/api/login/get-token")
async def get_existing_token():
    """[已弃用] 获取已登录 userbot 的 token。"""
    return JSONResponse({"success": False, "error": "接口已弃用，请使用系统登录"}, status_code=410)
