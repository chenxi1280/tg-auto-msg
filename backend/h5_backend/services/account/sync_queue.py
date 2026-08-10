"""Priority queue and completion tracking for account synchronization."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Optional

SYNC_TRIGGER_MANUAL = "manual"
SYNC_TRIGGER_LOGIN_SUCCESS = "login_success"
SYNC_TRIGGER_AUTO_TIMER = "auto_timer"

_TRIGGER_PRIORITY = {
    SYNC_TRIGGER_MANUAL: 0,
    SYNC_TRIGGER_LOGIN_SUCCESS: 1,
    SYNC_TRIGGER_AUTO_TIMER: 2,
}


@dataclass(order=True, frozen=True)
class AccountSyncWorkItem:
    """One immutable account synchronization queue item."""

    priority: int
    sequence: int
    account_id: str = field(compare=False)
    user_id: int = field(compare=False)
    trigger_source: str = field(compare=False)


class AccountSyncQueue:
    """Deduplicated priority queue with a shared result per account."""

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[AccountSyncWorkItem] = asyncio.PriorityQueue()
        self._queued_items: dict[str, AccountSyncWorkItem] = {}
        self._running_items: dict[str, AccountSyncWorkItem] = {}
        self._completion_futures: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._sequence = count()

    async def enqueue(self, *, account_id: str, user_id: int, trigger_source: str) -> str:
        priority = self._priority(trigger_source)
        if account_id in self._running_items:
            return "running"

        queued = self._queued_items.get(account_id)
        if queued is not None and priority >= queued.priority:
            return "queued"

        status = "reprioritized" if queued is not None else "enqueued"
        if queued is None:
            self._completion_futures[account_id] = asyncio.get_running_loop().create_future()

        item = AccountSyncWorkItem(
            priority=priority,
            sequence=next(self._sequence),
            account_id=account_id,
            user_id=user_id,
            trigger_source=trigger_source,
        )
        self._queued_items[account_id] = item
        await self._queue.put(item)
        return status

    async def get(self) -> AccountSyncWorkItem:
        while True:
            item = await self._queue.get()
            if self._queued_items.get(item.account_id) is item:
                self._queued_items.pop(item.account_id, None)
                self._running_items[item.account_id] = item
                return item
            self._queue.task_done()

    def complete(self, item: AccountSyncWorkItem, result: dict[str, Any]) -> None:
        running = self._running_items.get(item.account_id)
        if running is not item:
            raise RuntimeError(f"account sync item is not running: {item.account_id}")
        self._running_items.pop(item.account_id, None)
        future = self._completion_futures[item.account_id]
        if not future.done():
            future.set_result(dict(result))
        self._queue.task_done()

    async def wait_for_result(
        self,
        account_id: str,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> dict[str, Any]:
        future = self._completion_futures.get(account_id)
        if future is None:
            raise RuntimeError(f"account sync completion is unavailable: {account_id}")
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout_seconds)

    async def join(self) -> None:
        await self._queue.join()

    def pending_count(self) -> int:
        return len(self._queued_items)

    @staticmethod
    def _priority(trigger_source: str) -> int:
        try:
            return _TRIGGER_PRIORITY[trigger_source]
        except KeyError as exc:
            raise ValueError(f"unsupported account sync trigger: {trigger_source}") from exc
