"""Account selection/health/statistics helpers for AccountManager."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
import random

from loguru import logger
from sqlalchemy import select, update

from backend.bot.session.redis_login_manager import get_redis_login_manager
from backend.database.schema.models import Account, HealthStatus, Resource
from backend.database.runtime.session import get_async_session


def _select_from_candidates(manager, accounts, *, user_id: int, strategy):
    if not accounts:
        return None

    if strategy.value == "weight":
        weights = [acc.weight for acc in accounts]
        total_weight = sum(weights)
        if total_weight == 0:
            return accounts[0]

        rand = random.randint(0, total_weight - 1)
        current = 0
        for acc in accounts:
            current += acc.weight
            if rand < current:
                return acc

    if strategy.value == "least_used":
        return min(accounts, key=lambda acc: acc.messages_sent)

    if strategy.value == "round_robin":
        if user_id not in manager._round_robin_counter:
            manager._round_robin_counter[user_id] = 0
        index = manager._round_robin_counter[user_id] % len(accounts)
        manager._round_robin_counter[user_id] += 1
        return accounts[index]

    return accounts[0]


async def select_account(
    manager,
    *,
    user_id: int,
    peer_id: Optional[int],
    strategy,
):
    """Select one healthy account based on strategy."""
    accounts = await manager.get_accounts(user_id, is_active=True)
    if not accounts:
        return None

    healthy_accounts = [
        acc
        for acc in accounts
        if acc.health_status == HealthStatus.ONLINE and not acc.is_flooding and not acc.is_banned
    ]
    if not healthy_accounts:
        logger.warning(f"用户 {user_id} 没有可用的健康账号")
        return None

    if peer_id:
        candidate_ids = {str(acc.account_id) for acc in healthy_accounts}
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(Resource.account_id).where(
                        Resource.peer_id == int(peer_id),
                        Resource.account_id.in_(candidate_ids),
                        Resource.is_active == True,
                    )
                )
            ).scalars().all()
        preferred_ids = {str(account_id) for account_id in rows}
        if preferred_ids:
            preferred_accounts = [
                acc for acc in healthy_accounts if str(acc.account_id) in preferred_ids
            ]
            selected = _select_from_candidates(
                manager,
                preferred_accounts,
                user_id=user_id,
                strategy=strategy,
            )
            if selected:
                return selected

    return _select_from_candidates(
        manager,
        healthy_accounts,
        user_id=user_id,
        strategy=strategy,
    )


async def health_check(manager, account_id: str) -> HealthStatus:
    """Perform get_me check and persist health status."""
    client = await manager.get_client(account_id)
    if not client:
        return HealthStatus.OFFLINE

    try:
        me = await client.get_me()
        if me:
            await update_health_status(manager, account_id, HealthStatus.ONLINE)
            return HealthStatus.ONLINE
    except Exception as e:
        logger.error(f"健康检查失败 {account_id}: {e}")
        await update_health_status(manager, account_id, HealthStatus.OFFLINE)
        return HealthStatus.OFFLINE
    return HealthStatus.OFFLINE


async def update_health_status(manager, account_id: str, status: HealthStatus) -> None:
    """Persist health status into DB + Redis cache."""
    await manager.update_account(account_id, health_status=status.value)

    redis_client = await get_redis_login_manager()._get_redis()
    key = f"health:account:{account_id}"
    await redis_client.hset(
        key,
        mapping={"status": status.value, "last_check": datetime.now().isoformat()},
    )
    await redis_client.expire(key, 300)


async def get_health_status(account_id: str) -> Optional[Dict[str, Any]]:
    """Read account health cache from Redis."""
    redis_client = await get_redis_login_manager()._get_redis()
    key = f"health:account:{account_id}"
    data = await redis_client.hgetall(key)
    if data:
        return {"status": data.get("status"), "last_check": data.get("last_check")}
    return None


async def increment_messages_sent(session, account_id: str) -> None:
    """Increment sent statistics within the caller's transaction."""
    await session.execute(
        update(Account)
        .where(Account.account_id == account_id)
        .values(
            messages_sent=Account.messages_sent + 1,
            last_used_at=datetime.now(),
        )
    )
