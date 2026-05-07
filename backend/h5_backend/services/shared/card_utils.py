"""Shared card code generation utilities."""
from __future__ import annotations

import secrets
import string

CARD_ALPHABET = string.ascii_uppercase + string.digits


def generate_card_code(prefix: str = "") -> str:
    """Generate a 16-char random card code with optional prefix."""
    normalized_prefix = (prefix or "").strip().upper()
    random_part = "".join(secrets.choice(CARD_ALPHABET) for _ in range(16))
    return f"{normalized_prefix}{random_part}"
