"""H5 API shared dependencies and permission checks."""

from fastapi import Depends
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from backend.bot.account.manager import get_account_manager
from backend.bot.proxy.pool import get_proxy_pool
from backend.database.schema.models import Account, AdminAccount, Proxy, ScheduledMessageTask
from backend.database.runtime.session import get_async_session
from backend.h5_backend.services.admin_auth.service import get_admin_auth_service

admin_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/admin-auth/login")


async def check_task_permission(task_id: str, user_id: int) -> ScheduledMessageTask:
    """Check task ownership and return task."""
    async with get_async_session() as session:
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id)
        )
        task = result.scalar_one_or_none()

    if not task or task.user_id != user_id:
        raise HTTPException(status_code=404, detail="任务不存在")

    return task


async def check_account_permission(account_id: str, user_id: int) -> Account:
    """Check account ownership and return account."""
    account_manager = get_account_manager()
    account = await account_manager.get_account(account_id)
    if not account or account.user_id != user_id:
        raise HTTPException(status_code=404, detail="账号不存在")
    return account


async def check_proxy_permission(proxy_id: int, user_id: int) -> Proxy:
    """Check proxy visibility for current user and return proxy."""
    proxy_pool = get_proxy_pool()
    proxy = await proxy_pool.get_proxy(proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="代理不存在")

    if proxy.assigned_account_id:
        await check_account_permission(proxy.assigned_account_id, user_id)

    return proxy


async def get_current_admin_account(token: str = Depends(admin_oauth2_scheme)) -> AdminAccount:
    service = get_admin_auth_service()
    return await service.get_current_admin(token)


def require_admin_roles(*roles: str):
    async def _dependency(current_admin: AdminAccount = Depends(get_current_admin_account)) -> AdminAccount:
        if roles and current_admin.role_code not in set(roles):
            raise HTTPException(status_code=403, detail="无权访问该后台资源")
        return current_admin

    return _dependency
