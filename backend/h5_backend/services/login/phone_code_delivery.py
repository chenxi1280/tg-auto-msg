"""Safe Telegram phone-code delivery metadata."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


DELIVERY_METHOD_TELEGRAM_APP = "telegram_app"
DELIVERY_METHOD_SMS = "sms"
DELIVERY_METHOD_PHONE_CALL = "phone_call"
DELIVERY_METHOD_EMAIL = "email"
DELIVERY_METHOD_UNKNOWN = "unknown"
MINIMUM_RESEND_SECONDS = 1

_SMS_TYPE_NAMES = {
    "SentCodeTypeFirebaseSms",
    "SentCodeTypeFragmentSms",
    "SentCodeTypeSms",
    "SentCodeTypeSmsPhrase",
    "SentCodeTypeSmsWord",
}
_PHONE_CALL_TYPE_NAMES = {
    "SentCodeTypeCall",
    "SentCodeTypeFlashCall",
    "SentCodeTypeMissedCall",
}
_EMAIL_TYPE_NAMES = {
    "SentCodeTypeEmailCode",
    "SentCodeTypeSetUpEmailRequired",
}


@dataclass(frozen=True)
class PhoneCodeDelivery:
    """Non-sensitive delivery facts safe to persist in a login session."""

    delivery_method: str = DELIVERY_METHOD_UNKNOWN
    next_delivery_method: Optional[str] = None
    code_length: Optional[int] = None
    resend_after_seconds: int = 0

    def to_response_fields(self) -> dict[str, Any]:
        return {
            "delivery_method": self.delivery_method,
            "next_delivery_method": self.next_delivery_method,
            "code_length": self.code_length,
            "resend_after_seconds": self.resend_after_seconds,
        }

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, Any],
        *,
        resend_after_seconds: Optional[int] = None,
    ) -> "PhoneCodeDelivery":
        retry_after = (
            values.get("resend_after_seconds")
            if resend_after_seconds is None
            else resend_after_seconds
        )
        return cls(
            delivery_method=_normalize_method(values.get("delivery_method")),
            next_delivery_method=_optional_method(values.get("next_delivery_method")),
            code_length=_positive_int(values.get("code_length")),
            resend_after_seconds=max(0, int(retry_after or 0)),
        )


def describe_sent_code(
    sent_code: Any,
    *,
    fallback_resend_cooldown_seconds: int,
) -> PhoneCodeDelivery:
    """Extract only public delivery facts from Telethon's SentCode response."""
    timeout = _positive_int(getattr(sent_code, "timeout", None))
    fallback = max(MINIMUM_RESEND_SECONDS, int(fallback_resend_cooldown_seconds))
    return PhoneCodeDelivery(
        delivery_method=_method_for_type(getattr(sent_code, "type", None)),
        next_delivery_method=_optional_method_for_type(getattr(sent_code, "next_type", None)),
        code_length=_positive_int(getattr(getattr(sent_code, "type", None), "length", None)),
        resend_after_seconds=timeout or fallback,
    )


def _method_for_type(value: Any) -> str:
    type_name = type(value).__name__
    if type_name == "SentCodeTypeApp":
        return DELIVERY_METHOD_TELEGRAM_APP
    if type_name in _SMS_TYPE_NAMES:
        return DELIVERY_METHOD_SMS
    if type_name in _PHONE_CALL_TYPE_NAMES:
        return DELIVERY_METHOD_PHONE_CALL
    if type_name in _EMAIL_TYPE_NAMES:
        return DELIVERY_METHOD_EMAIL
    return DELIVERY_METHOD_UNKNOWN


def _optional_method_for_type(value: Any) -> Optional[str]:
    method = _method_for_type(value)
    return None if method == DELIVERY_METHOD_UNKNOWN else method


def _normalize_method(value: Any) -> str:
    allowed = {
        DELIVERY_METHOD_TELEGRAM_APP,
        DELIVERY_METHOD_SMS,
        DELIVERY_METHOD_PHONE_CALL,
        DELIVERY_METHOD_EMAIL,
        DELIVERY_METHOD_UNKNOWN,
    }
    candidate = str(value or "")
    return candidate if candidate in allowed else DELIVERY_METHOD_UNKNOWN


def _optional_method(value: Any) -> Optional[str]:
    method = _normalize_method(value)
    return None if method == DELIVERY_METHOD_UNKNOWN else method


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None
