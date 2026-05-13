"""Shared search helpers for SQL LIKE patterns."""
from __future__ import annotations


LIKE_ESCAPE_CHAR = "\\"


def escape_like_keyword(value: str) -> str:
    """Escape SQL LIKE wildcards while keeping normal substring search behavior."""
    text = str(value or "")
    return (
        text.replace(LIKE_ESCAPE_CHAR, LIKE_ESCAPE_CHAR * 2)
        .replace("%", LIKE_ESCAPE_CHAR + "%")
        .replace("_", LIKE_ESCAPE_CHAR + "_")
    )


def contains_like_pattern(value: str) -> str:
    return f"%{escape_like_keyword(value)}%"
