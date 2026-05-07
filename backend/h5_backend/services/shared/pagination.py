"""Shared pagination utilities."""
from __future__ import annotations

from typing import Any, Dict, List


def paginate_items(
    items: List[Dict[str, Any]],
    *,
    limit: int,
    offset: int,
) -> Dict[str, Any]:
    """Paginate a pre-loaded list of items."""
    normalized_limit = max(1, min(500, int(limit)))
    normalized_offset = max(0, int(offset))
    sliced = items[normalized_offset:normalized_offset + normalized_limit]
    return {
        "items": sliced,
        "total": len(items),
        "limit": normalized_limit,
        "offset": normalized_offset,
    }


def normalize_page(limit: int, offset: int) -> tuple[int, int]:
    """Normalize and clamp pagination parameters."""
    return max(1, min(500, int(limit))), max(0, int(offset))
