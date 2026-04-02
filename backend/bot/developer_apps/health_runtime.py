"""Periodic developer-app health checker runtime."""
from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger

from backend.bot.developer_apps.service import get_developer_app_service


class DeveloperAppHealthRuntime:
    """Background runtime for developer-app health checks."""

    CHECK_INTERVAL_SECONDS = 300

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def _run_forever(self) -> None:
        while self._running:
            try:
                results = await get_developer_app_service().run_health_check_cycle()
                logger.info("开发者应用健康检查完成: total={}", len(results))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("开发者应用健康检查任务异常: {}", exc)
            await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None


developer_app_health_runtime = DeveloperAppHealthRuntime()
