"""H5 API shared dependencies and permission checks."""
import hmac

from fastapi import Header
from fastapi import HTTPException
from sqlalchemy import select

from backend.config.core.settings import settings
from backend.bot.account.manager import get_account_manager
from backend.bot.proxy.pool import get_proxy_pool
from backend.database.schema.models import Account, Proxy, ScheduledMessageTask
from backend.database.runtime.session import get_async_session


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


def require_admin_token(x_admin_token: str = Header(default="", alias="X-Admin-Token")) -> bool:
    """Simple admin API token guard for out-of-band admin backend."""
    expected = (settings.admin_api_token or "").strip()
    provided = (x_admin_token or "").strip()

    if not expected:
        raise HTTPException(status_code=503, detail="管理员接口未配置 ADMIN_API_TOKEN")

    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="管理员鉴权失败")

    return True
