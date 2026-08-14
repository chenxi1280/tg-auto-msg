"""Safe, Bot-local state helpers for phone-code resend prompts."""
from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import Any, Mapping, Optional

from backend.h5_backend.services.login.phone_code_delivery import PhoneCodeDelivery


PHONE_CODE_RESEND_DEADLINE_KEY = "phone_code_resend_deadline_monotonic"
NO_RESEND_WAIT_SECONDS = 0


def delivery_from_phone_code_state(values: Mapping[str, Any]) -> PhoneCodeDelivery:
    """Return delivery metadata with the current remaining resend wait."""
    delivery = PhoneCodeDelivery.from_mapping(values)
    remaining_seconds = _remaining_resend_seconds(values)
    if remaining_seconds is None:
        return delivery
    return replace(delivery, resend_after_seconds=remaining_seconds)


def phone_code_state_fields(delivery: PhoneCodeDelivery) -> dict[str, Any]:
    """Build non-sensitive FSM fields for a newly accepted code request."""
    return {
        "delivery_method": delivery.delivery_method,
        "next_delivery_method": delivery.next_delivery_method or "",
        "code_length": delivery.code_length or "",
        "resend_after_seconds": delivery.resend_after_seconds,
        PHONE_CODE_RESEND_DEADLINE_KEY: time.monotonic() + delivery.resend_after_seconds,
    }


def delivery_with_retry_after(
    values: Mapping[str, Any],
    retry_after_seconds: int,
) -> PhoneCodeDelivery:
    """Apply a 429 retry value without discarding a known active cooldown."""
    delivery = delivery_from_phone_code_state(values)
    if retry_after_seconds <= NO_RESEND_WAIT_SECONDS:
        return delivery
    return replace(delivery, resend_after_seconds=retry_after_seconds)


def _remaining_resend_seconds(values: Mapping[str, Any]) -> Optional[int]:
    raw_deadline = values.get(PHONE_CODE_RESEND_DEADLINE_KEY)
    if raw_deadline is None:
        return None
    try:
        remaining = math.ceil(float(raw_deadline) - time.monotonic())
    except (TypeError, ValueError, OverflowError):
        return None
    return max(NO_RESEND_WAIT_SECONDS, remaining)
