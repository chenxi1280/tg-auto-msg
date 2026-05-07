"""Shared ORM → dict serializers used across admin services."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from backend.database.schema.models import PricingPlan


def _to_price_yuan(price_cents: int) -> str:
    return f"{(Decimal(price_cents) / Decimal(100)).quantize(Decimal('0.00'))}"


def serialize_pricing_plan(plan: PricingPlan) -> Dict[str, Any]:
    """Serialize a PricingPlan ORM object to a dict."""
    return {
        "plan_code": plan.plan_code,
        "display_name": plan.display_name,
        "billing_cycle": plan.billing_cycle,
        "price_cents": int(plan.price_cents or 0),
        "price_yuan": _to_price_yuan(int(plan.price_cents or 0)),
        "duration_days": int(plan.duration_days or 0),
        "is_active": bool(plan.is_active),
        "sort_order": int(plan.sort_order or 0),
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }
