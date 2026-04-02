"""Runtime auto-sync for Telegram account resources."""
from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy import select

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import Account
from backend.h5_backend.services.account.service import get_account_service


class AccountAutoSyncRuntime:
    INTERVAL_SECONDS = 20 * 60

    def __init__(self) -> None:
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("✅ 账号资源自动同步任务已启动（间隔: {} 秒）", self.INTERVAL_SECONDS)
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("账号资源自动同步任务异常: {}: {!r}", type(exc).__name__, exc)
            await asyncio.sleep(self.INTERVAL_SECONDS)

    async def stop(self) -> None:
        self._running = False

    async def run_once(self) -> None:
        async with get_async_session() as session:
            result = await session.execute(
                select(Account.user_id).where(Account.is_active.is_(True)).distinct()
            )
            user_ids = [int(row[0]) for row in result.all() if row[0] is not None]

        if not user_ids:
            return

        service = get_account_service()
        for user_id in user_ids:
            try:
                await service.sync_all_resources(user_id, wait=True)
            except Exception as exc:
                logger.warning("自动同步用户账号资源失败: user_id={}, error={}", user_id, exc)


account_auto_sync_runtime = AccountAutoSyncRuntime()
