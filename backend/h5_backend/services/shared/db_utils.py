"""Shared database query utilities."""
from __future__ import annotations

from typing import Any, Type

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_or_404(
    session: AsyncSession,
    model: Type,
    *,
    detail: str = "记录不存在",
    **filters,
) -> Any:
    """Query a single record by filters; raise HTTP 404 if not found.

    Usage:
        plan = await get_or_404(session, PricingPlan, plan_code="monthly")
    """
    stmt = select(model)
    for col_name, value in filters.items():
        col = getattr(model, col_name, None)
        if col is None:
            raise ValueError(f"{model.__name__} has no column '{col_name}'")
        stmt = stmt.where(col == value)
    stmt = stmt.limit(1)

    result = await session.execute(stmt)
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail=detail)
    return obj
