"""Shared purchase button parsing and normalization."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from backend.utils.url_validation import is_valid_purchase_button_url

DEFAULT_PURCHASE_URL = "https://t.me/"
DEFAULT_PURCHASE_BUTTON_TEXT = "联系 Telegram 购买"
PURCHASE_SETTING_KEYS = ["purchase_url", "purchase_button_text", "purchase_buttons"]


def load_purchase_buttons_json(raw_value: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    if not raw_value:
        return None
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    return [item for item in parsed if isinstance(item, dict)]


def normalize_purchase_buttons(
    raw_buttons: Optional[List[Dict[str, Any]]],
    *,
    legacy_url: str,
    legacy_button_text: str,
    strict: bool,
) -> List[Dict[str, str]]:
    buttons: List[Dict[str, str]] = []
    for index, item in enumerate((raw_buttons or [])[:2]):
        text = str(item.get("text") or item.get("button_text") or "").strip()
        url = str(item.get("url") or "").strip()
        if not text and not url:
            continue
        if not url:
            if strict:
                raise HTTPException(status_code=400, detail=f"购买按钮 {index + 1} 链接不能为空")
            continue
        if not is_valid_purchase_button_url(url):
            if strict:
                raise HTTPException(status_code=400, detail=f"购买按钮 {index + 1} 链接格式无效，仅支持 Telegram 链接或公网 HTTP/HTTPS 商铺链接")
            continue
        buttons.append(
            {
                "text": text or (DEFAULT_PURCHASE_BUTTON_TEXT if index == 0 else f"购买入口 {index + 1}"),
                "url": url,
            }
        )

    if buttons:
        return buttons

    fallback_url = (legacy_url or DEFAULT_PURCHASE_URL).strip()
    fallback_text = (legacy_button_text or DEFAULT_PURCHASE_BUTTON_TEXT).strip()
    if not is_valid_purchase_button_url(fallback_url):
        if strict:
            raise HTTPException(status_code=400, detail="购买链接格式无效，仅支持 Telegram 链接或公网 HTTP/HTTPS 商铺链接")
        fallback_url = DEFAULT_PURCHASE_URL
    return [{"text": fallback_text or DEFAULT_PURCHASE_BUTTON_TEXT, "url": fallback_url}]
