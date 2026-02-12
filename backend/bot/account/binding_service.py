"""Binding-related helpers for AccountManager."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.bot.session.redis_login_manager import get_redis_login_manager
from backend.bot.handlers.core.user_link import (
    set_active_account_id,
    set_linked_system_user_id,
)
from backend.bot.developer_apps import get_developer_app_service
from backend.config.core.settings import settings
from backend.database.schema.models import Account, AccountBindLog, HealthStatus, TelegramDeveloperApp
from backend.database.runtime.session import get_async_session
from backend.utils.security.crypto import generate_bind_code


_BIND_FAIL_KEY_PREFIX = "bind:fail:"
_BIND_LOCK_KEY_PREFIX = "bind:lock:"


class BindRateLimitError(RuntimeError):
    """Raised when bind attempts are temporarily locked due to too many failures."""

    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        super().__init__(f"绑定尝试过于频繁，请 {self.retry_after_seconds} 秒后重试")


def _build_bind_actor_key(user_id: int, actor_tg_user_id: Optional[int]) -> str:
    actor = int(actor_tg_user_id or 0)
    if actor > 0:
        return f"tg:{actor}"
    return f"user:{int(user_id)}"


async def _get_lock_ttl(redis_client, actor_key: str) -> int:
    lock_key = _BIND_LOCK_KEY_PREFIX + actor_key
    if not await redis_client.exists(lock_key):
        return 0
    ttl = int(await redis_client.ttl(lock_key) or 0)
    return ttl if ttl > 0 else max(1, int(settings.bind_lock_seconds))


async def _record_bind_failure(redis_client, actor_key: str) -> int:
    """
    记录绑定失败并返回锁定剩余秒数。
    返回值 > 0 表示本次已触发锁定。
    """
    fail_key = _BIND_FAIL_KEY_PREFIX + actor_key
    lock_key = _BIND_LOCK_KEY_PREFIX + actor_key

    failures = int(await redis_client.incr(fail_key))
    if failures == 1:
        await redis_client.expire(fail_key, int(settings.bind_failure_window_seconds))

    if failures >= int(settings.bind_max_failures):
        lock_seconds = max(1, int(settings.bind_lock_seconds))
        await redis_client.set(lock_key, "1", ex=lock_seconds)
        await redis_client.delete(fail_key)
        return lock_seconds
    return 0


async def _clear_bind_failures(redis_client, actor_key: str) -> None:
    await redis_client.delete(_BIND_FAIL_KEY_PREFIX + actor_key, _BIND_LOCK_KEY_PREFIX + actor_key)


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
    actor_tg_user_id: Optional[int] = None,
) -> Optional[Account]:
    """Bind account by one-time bind code."""
    login_manager = get_redis_login_manager()
    redis_client = await login_manager._get_redis()
    actor_key = _build_bind_actor_key(user_id, actor_tg_user_id)

    lock_ttl = await _get_lock_ttl(redis_client, actor_key)
    if lock_ttl > 0:
        logger.warning(f"绑定请求触发限流: actor={actor_key}, retry_after={lock_ttl}s")
        raise BindRateLimitError(lock_ttl)

    async def _reject(reason: str) -> None:
        lock_after = await _record_bind_failure(redis_client, actor_key)
        if lock_after > 0:
            logger.warning(
                f"绑定失败并触发锁定: actor={actor_key}, reason={reason}, retry_after={lock_after}s"
            )
            raise BindRateLimitError(lock_after)
        logger.warning(f"绑定失败: actor={actor_key}, reason={reason}")
        return None

    bind_data = await login_manager.get_account_by_bind_code(bind_code)
    if not bind_data:
        return await _reject("invalid_bind_code")

    actor_tg_user_id = int(actor_tg_user_id or 0)
    owner_raw = bind_data.get("system_user_id")
    developer_app_id_raw = bind_data.get("developer_app_id")
    developer_app_id = None
    if developer_app_id_raw not in (None, ""):
        try:
            developer_app_id = int(developer_app_id_raw)
        except Exception:
            developer_app_id = None
    tg_user_id = int(bind_data["tg_user_id"])

    if owner_raw not in (None, ""):
        owner_user_id = int(owner_raw)
        # 安全校验：
        # - H5 绑定：user_id 应该是系统用户ID，必须等于 owner_user_id
        # - Bot /bind：user_id 可能是已映射系统用户ID，或首次绑定时的 tg_user_id
        if user_id != owner_user_id and user_id != tg_user_id:
            return await _reject(
                "invalid_request_source:"
                f"user_id={user_id},owner={owner_user_id},tg={tg_user_id}"
            )
    else:
        # 历史数据兜底：优先从已存在账号回推归属用户；若无法回推则拒绝绑定。
        async with get_async_session() as _session:
            existing_owner = await _session.execute(
                select(Account.user_id).where(Account.tg_user_id == tg_user_id).limit(1)
            )
            owner_user_id = existing_owner.scalar_one_or_none()
        if owner_user_id is None:
            return await _reject(
                "missing_owner_and_cannot_infer:"
                f"user_id={user_id},tg={tg_user_id}"
            )
        if user_id != owner_user_id and user_id != tg_user_id:
            return await _reject(
                "missing_owner_invalid_source:"
                f"user_id={user_id},owner={owner_user_id},tg={tg_user_id}"
            )

    if user_id != owner_user_id:
        logger.info(f"绑定请求 user_id={user_id} 与绑定码归属 owner_user_id={owner_user_id} 不一致，按归属用户绑定")

    async with get_async_session() as session:
        developer_service = get_developer_app_service()
        existing = await session.execute(
            select(Account).where(
                Account.user_id == owner_user_id,
                Account.tg_user_id == tg_user_id,
            )
        )
        existing_account = existing.scalar_one_or_none()
        if existing_account:
            preferred_app_id = (
                developer_app_id
                if developer_app_id is not None
                else existing_account.developer_app_id
            )
            try:
                resolved_app_id = await developer_service.resolve_assignable_app_id(
                    user_id=int(owner_user_id),
                    preferred_app_id=preferred_app_id,
                    exclude_account_id=existing_account.account_id,
                )
            except Exception as exc:
                raise RuntimeError(f"开发者凭证分配失败: {exc}") from exc
            resolved_app_version = 1
            if resolved_app_id is not None:
                app_row = await session.get(TelegramDeveloperApp, int(resolved_app_id))
                if app_row is not None:
                    resolved_app_version = int(app_row.credentials_version or 1)

            existing_account.username = bind_data.get("username") or existing_account.username
            existing_account.phone = bind_data.get("phone") or existing_account.phone
            existing_account.string_session_encrypted = bind_data["string_session_encrypted"]
            existing_account.developer_app_id = resolved_app_id
            existing_account.developer_app_version = resolved_app_version
            existing_account.reauth_required = False
            existing_account.reauth_reason = None
            existing_account.reauth_required_at = None
            existing_account.health_status = HealthStatus.ONLINE

            log = AccountBindLog(
                account_id=existing_account.account_id,
                user_id=owner_user_id,
                bind_code=bind_code,
                ip_address=ip_address,
            )
            session.add(log)
            if actor_tg_user_id > 0:
                await set_linked_system_user_id(session, actor_tg_user_id, owner_user_id)
                await set_active_account_id(session, actor_tg_user_id, owner_user_id, existing_account.account_id)
            await session.commit()
            await session.refresh(existing_account)

            await login_manager.consume_bind_code(bind_code)
            await login_manager.set_user_logged_in(owner_user_id)
            await _clear_bind_failures(redis_client, actor_key)
            logger.info(f"重复绑定已更新账号信息: {existing_account.account_id} -> user {owner_user_id}")
            return existing_account

        existing_any = await session.execute(
            select(Account).where(Account.tg_user_id == tg_user_id)
        )
        existing_account = existing_any.scalar_one_or_none()
        if existing_account and existing_account.user_id != owner_user_id:
            return await _reject(
                f"tg_account_owned_by_other_user:tg={tg_user_id},owner={existing_account.user_id}"
            )

        try:
            resolved_app_id = await developer_service.resolve_assignable_app_id(
                user_id=int(owner_user_id),
                preferred_app_id=developer_app_id,
                exclude_account_id=None,
            )
        except Exception as exc:
            raise RuntimeError(f"开发者凭证分配失败: {exc}") from exc
        resolved_app_version = 1
        if resolved_app_id is not None:
            app_row = await session.get(TelegramDeveloperApp, int(resolved_app_id))
            if app_row is not None:
                resolved_app_version = int(app_row.credentials_version or 1)

        account = Account(
            user_id=owner_user_id,
            tg_user_id=tg_user_id,
            username=bind_data.get("username", ""),
            phone=bind_data.get("phone", ""),
            string_session_encrypted=bind_data["string_session_encrypted"],
            developer_app_id=resolved_app_id,
            developer_app_version=resolved_app_version,
            reauth_required=False,
            reauth_reason=None,
            reauth_required_at=None,
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
        if actor_tg_user_id > 0:
            await set_linked_system_user_id(session, actor_tg_user_id, owner_user_id)
            await set_active_account_id(session, actor_tg_user_id, owner_user_id, account.account_id)
        await session.commit()

        await login_manager.consume_bind_code(bind_code)
        await login_manager.set_user_logged_in(owner_user_id)
        await _clear_bind_failures(redis_client, actor_key)
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
            "developer_app_id": str(account.developer_app_id or ""),
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
