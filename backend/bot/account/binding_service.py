"""Binding-related helpers for AccountManager."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.bot.session.redis_login_manager import get_redis_login_manager
from backend.database.schema.models import Account, AccountBindLog, HealthStatus
from backend.database.runtime.session import get_async_session
from backend.utils.security.crypto import generate_bind_code


async def sync_resources_after_bind(account_id: str) -> None:
    """Async resource sync hook after successful binding."""
    try:
        from backend.bot.resources.manager import get_resource_manager

        resource_manager = get_resource_manager()
        await resource_manager.full_sync(account_id)
    except Exception as e:
        logger.error(f"绑定后资源同步失败: {e}")


async def bind_account(
    manager,
    *,
    user_id: int,
    bind_code: str,
    ip_address: str = "",
) -> Optional[Account]:
    """Bind account by one-time bind code."""
    login_manager = get_redis_login_manager()
    bind_data = await login_manager.get_account_by_bind_code(bind_code)
    if not bind_data:
        logger.warning(f"无效的绑定码: {bind_code}")
        return None

    owner_user_id = int(bind_data.get("system_user_id") or user_id)
    tg_user_id = int(bind_data["tg_user_id"])

    if user_id != owner_user_id and user_id != tg_user_id:
        logger.warning(
            f"绑定请求来源非法: user_id={user_id}, owner_user_id={owner_user_id}, tg_user_id={tg_user_id}"
        )
        return None

    if owner_user_id != user_id:
        logger.info(
            f"绑定请求 user_id={user_id} 与绑定码归属 owner_user_id={owner_user_id} 不一致，"
            "将按绑定码归属入库"
        )

    async with get_async_session() as session:
        existing = await session.execute(
            select(Account).where(
                Account.user_id == owner_user_id,
                Account.tg_user_id == tg_user_id,
            )
        )
        existing_account = existing.scalar_one_or_none()
        if existing_account:
            existing_account.username = bind_data.get("username") or existing_account.username
            existing_account.phone = bind_data.get("phone") or existing_account.phone
            existing_account.string_session_encrypted = bind_data["string_session_encrypted"]
            existing_account.health_status = HealthStatus.ONLINE

            log = AccountBindLog(
                account_id=existing_account.account_id,
                user_id=owner_user_id,
                bind_code=bind_code,
                ip_address=ip_address,
            )
            session.add(log)
            await session.commit()
            await session.refresh(existing_account)

            await login_manager.consume_bind_code(bind_code)
            await login_manager.set_user_logged_in(owner_user_id)
            logger.info(f"重复绑定已更新账号信息: {existing_account.account_id} -> user {owner_user_id}")
            return existing_account

        existing_any = await session.execute(
            select(Account).where(Account.tg_user_id == tg_user_id)
        )
        existing_account = existing_any.scalar_one_or_none()
        if existing_account and existing_account.user_id != owner_user_id:
            logger.warning(
                f"TG 账号 {tg_user_id} 已绑定到其他用户: {existing_account.user_id}"
            )
            return None

        account = Account(
            user_id=owner_user_id,
            tg_user_id=tg_user_id,
            username=bind_data.get("username", ""),
            phone=bind_data.get("phone", ""),
            string_session_encrypted=bind_data["string_session_encrypted"],
            health_status=HealthStatus.ONLINE,
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)

        log = AccountBindLog(
            account_id=account.account_id,
            user_id=owner_user_id,
            bind_code=bind_code,
            ip_address=ip_address,
        )
        session.add(log)
        await session.commit()

        await login_manager.consume_bind_code(bind_code)
        await login_manager.set_user_logged_in(owner_user_id)
        logger.info(f"绑定账号成功: {account.account_id} -> user {owner_user_id}")

        asyncio.create_task(sync_resources_after_bind(account.account_id))
        return account


async def issue_bind_code(
    manager,
    *,
    account_id: str,
    refresh: bool = True,
    ttl_seconds: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Issue short-lived bind code for existing account."""
    account = await manager.get_account(account_id)
    if not account:
        return None
    if not account.tg_user_id:
        raise RuntimeError("账号缺少 Telegram 用户 ID，无法生成绑定码")

    login_manager = get_redis_login_manager()
    redis_client = await login_manager._get_redis()
    now = datetime.now()
    effective_ttl = int(ttl_seconds or login_manager.BIND_CODE_TTL)
    old_bind_code = account.bind_code

    def _build_bind_data() -> Dict[str, str]:
        return {
            "login_id": f"account_{account.account_id}",
            "string_session_encrypted": account.string_session_encrypted,
            "tg_user_id": str(account.tg_user_id),
            "username": account.username or "",
            "phone": account.phone or "",
            "system_user_id": str(account.user_id),
        }

    if (
        not refresh
        and old_bind_code
        and account.bind_code_expires_at
        and account.bind_code_expires_at > now
    ):
        remaining_ttl = max(0, int((account.bind_code_expires_at - now).total_seconds()))
        bind_key = login_manager.BIND_KEY_PREFIX + old_bind_code
        if remaining_ttl > 0 and not await redis_client.exists(bind_key):
            await redis_client.hset(bind_key, mapping=_build_bind_data())
            await redis_client.expire(bind_key, remaining_ttl)
        return {
            "bind_code": old_bind_code,
            "expires_at": account.bind_code_expires_at,
            "ttl_seconds": remaining_ttl,
        }

    for _attempt in range(5):
        bind_code: Optional[str] = None
        for _ in range(60):
            candidate = generate_bind_code()
            if old_bind_code and candidate == old_bind_code:
                continue

            bind_key = login_manager.BIND_KEY_PREFIX + candidate
            if await redis_client.exists(bind_key):
                continue

            async with get_async_session() as session:
                code_owner = await session.execute(
                    select(Account.account_id).where(
                        Account.bind_code == candidate,
                        Account.account_id != account_id,
                    )
                )
                if code_owner.scalar_one_or_none():
                    continue

            bind_code = candidate
            break

        if not bind_code:
            break

        bind_key = login_manager.BIND_KEY_PREFIX + bind_code
        await redis_client.hset(bind_key, mapping=_build_bind_data())
        await redis_client.expire(bind_key, effective_ttl)

        expires_at = datetime.now() + timedelta(seconds=effective_ttl)
        try:
            await manager.update_account(
                account_id,
                bind_code=bind_code,
                bind_code_expires_at=expires_at,
            )
        except IntegrityError:
            await redis_client.delete(bind_key)
            logger.warning(f"签发绑定码冲突，重试中: account_id={account_id}")
            continue
        except Exception:
            await redis_client.delete(bind_key)
            raise

        if old_bind_code and old_bind_code != bind_code:
            await redis_client.delete(login_manager.BIND_KEY_PREFIX + old_bind_code)

        logger.info(f"签发账号绑定码: account_id={account_id}, code={bind_code}, ttl={effective_ttl}s")
        return {
            "bind_code": bind_code,
            "expires_at": expires_at,
            "ttl_seconds": effective_ttl,
        }

    raise RuntimeError("无法生成可用绑定码，请稍后重试")
