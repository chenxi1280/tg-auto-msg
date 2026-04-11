"""URL validation helpers shared across bot and service layers."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

LOCAL_BUTTON_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def is_valid_button_url(url: str) -> bool:
    """Validate URL for Telegram button usage."""
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = (parsed.hostname or "").lower()
    if host in LOCAL_BUTTON_HOSTS:
        return False
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    except ValueError:
        pass
    return True
