"""Presentation-only copy for Telegram phone-code login prompts."""
from __future__ import annotations

from typing import Optional

from backend.h5_backend.services.login.phone_code_delivery import PhoneCodeDelivery


_DELIVERY_LABELS = {
    "telegram_app": "已登录的 Telegram 客户端",
    "sms": "短信",
    "phone_call": "电话",
    "email": "邮箱",
    "unknown": "Telegram 官方渠道",
}


def build_phone_code_prompt(
    *,
    phone_number: str,
    masked_code: str,
    input_count: int,
    delivery: Optional[PhoneCodeDelivery] = None,
    detail: Optional[str] = None,
    request_accepted: Optional[bool] = True,
) -> str:
    """Build a prompt without embedding a verification code or session secret."""
    current_input = f"`{masked_code}`（已输入 {input_count} 位）" if input_count > 0 else "`未输入`"
    lines = [
        _request_title(request_accepted),
        "",
        f"手机号：`{phone_number or '未记录'}`",
        _delivery_instruction(delivery),
        "请使用下方数字按钮输入 Telegram 验证码，不要直接发送验证码消息。",
        "为避免验证码被 Telegram 判定失效，Bot 不会在聊天中接收明文验证码。",
        "",
        f"当前输入：{current_input}",
        "",
        _resend_instruction(delivery),
        "下一步：输入验证码后，若账号开启二步验证，Bot 会继续提示你输入密码。",
    ]
    if detail:
        lines[7:7] = ["", f"⚠️ {detail}"]
    return "\n".join(lines)


def _request_title(request_accepted: Optional[bool]) -> str:
    if request_accepted is True:
        return "📨 **验证码请求已被 Telegram 受理**"
    if request_accepted is False:
        return "⏳ **请等待后再重发验证码**"
    return "⚠️ **验证码请求未成功**"


def _delivery_instruction(delivery: Optional[PhoneCodeDelivery]) -> str:
    if delivery is None:
        return "请根据 Telegram 官方提示查看验证码。"
    current = _DELIVERY_LABELS.get(delivery.delivery_method, _DELIVERY_LABELS["unknown"])
    next_delivery = _DELIVERY_LABELS.get(delivery.next_delivery_method or "", "")
    next_hint = f" 若暂未收到，Telegram 可能后续改用{next_delivery}。" if next_delivery else ""
    length_hint = f" 验证码共 {delivery.code_length} 位。" if delivery.code_length else ""
    return f"Telegram 指示：请在{current}查看验证码。{next_hint}{length_hint}"


def _resend_instruction(delivery: Optional[PhoneCodeDelivery]) -> str:
    retry_after = delivery.resend_after_seconds if delivery else 0
    if retry_after > 0:
        return f"请勿连续重发；{retry_after} 秒后才可重新请求验证码。"
    return "如未收到验证码，可点击「🔄 重发验证码」重新请求。"
