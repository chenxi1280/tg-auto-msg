"""Telegram phone-code request workflow with a per-login send lease."""
from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any, Callable

from backend.h5_backend.services.login.phone_code_delivery import (
    PhoneCodeDelivery,
    describe_sent_code,
)


class PhoneCodeResendCooldownError(Exception):
    """Raised before Telegram is contacted when a login's send lease is active."""

    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        super().__init__(f"验证码重发冷却中：{self.retry_after_seconds} 秒")


async def request_phone_code(
    *,
    login_manager: Any,
    phone_code_lease_store: Any,
    login_id: str,
    phone_number: str,
    client: Any,
    save_pending_session: Callable[[], str],
    code_input_status: Any,
    fallback_resend_cooldown_seconds: int,
    inflight_lease_ttl_seconds: int,
    log: Any,
) -> PhoneCodeDelivery:
    lease_token = await _acquire_phone_code_lease(
        phone_code_lease_store,
        login_id=login_id,
        inflight_lease_ttl_seconds=inflight_lease_ttl_seconds,
    )

    response_received = False
    try:
        await client.connect()
        sent_code = await client.send_code_request(phone_number)
        response_received = True
        delivery = describe_sent_code(
            sent_code,
            fallback_resend_cooldown_seconds=fallback_resend_cooldown_seconds,
        )
        await _persist_sent_code(
            login_manager=login_manager,
            phone_code_lease_store=phone_code_lease_store,
            login_id=login_id,
            lease_token=lease_token,
            phone_number=phone_number,
            sent_code=sent_code,
            delivery=delivery,
            code_input_status=code_input_status,
            save_pending_session=save_pending_session,
        )
        _log_requested_code(
            log,
            login_id=login_id,
            phone_number=phone_number,
            delivery=delivery,
        )
        return delivery
    except Exception:
        if not response_received:
            await phone_code_lease_store.release_phone_code_send(login_id, lease_token)
        raise
    finally:
        await _disconnect_client(client, login_id=login_id, log=log)


async def _acquire_phone_code_lease(
    phone_code_lease_store: Any,
    *,
    login_id: str,
    inflight_lease_ttl_seconds: int,
) -> str:
    lease_token = secrets.token_urlsafe(18)
    retry_after = await phone_code_lease_store.acquire_phone_code_send(
        login_id,
        lease_token,
        ttl_seconds=inflight_lease_ttl_seconds,
    )
    if retry_after > 0:
        raise PhoneCodeResendCooldownError(retry_after)
    return lease_token


async def _persist_sent_code(
    *,
    login_manager: Any,
    phone_code_lease_store: Any,
    login_id: str,
    lease_token: str,
    phone_number: str,
    sent_code: Any,
    delivery: PhoneCodeDelivery,
    code_input_status: Any,
    save_pending_session: Callable[[], str],
) -> None:
    await login_manager.update_status(
        login_id,
        code_input_status,
        phone_number=phone_number,
        phone_code_hash=sent_code.phone_code_hash,
        code_sent_at=datetime.now().isoformat(),
        code_attempts="0",
        pending_session_encrypted=save_pending_session(),
        error="",
        password_hint="",
        qr_url="",
        delivery_method=delivery.delivery_method,
        next_delivery_method=delivery.next_delivery_method or "",
        code_length=delivery.code_length or "",
    )
    refreshed = await phone_code_lease_store.refresh_phone_code_send(
        login_id,
        lease_token,
        ttl_seconds=delivery.resend_after_seconds,
    )
    if not refreshed:
        raise RuntimeError("验证码重发租约更新失败")


def _log_requested_code(
    log: Any,
    *,
    login_id: str,
    phone_number: str,
    delivery: PhoneCodeDelivery,
) -> None:
    log.info(
        "手机号登录验证码请求已受理: login_id={}, phone={}, delivery_method={}, "
        "next_delivery_method={}, retry_after_seconds={}",
        login_id,
        _mask_phone(phone_number),
        delivery.delivery_method,
        delivery.next_delivery_method or "",
        delivery.resend_after_seconds,
    )


def _mask_phone(phone_number: str) -> str:
    return f"{str(phone_number or '')[:4]}***"


async def _disconnect_client(client: Any, *, login_id: str, log: Any) -> None:
    try:
        await client.disconnect()
    except Exception as exc:
        log.warning(
            "phone login client disconnect failed: login_id={}, error_type={}",
            login_id,
            type(exc).__name__,
        )
