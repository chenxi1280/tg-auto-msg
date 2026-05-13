"""Admin card generation, listing, export, and status management service."""
from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import Select, and_, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import selectinload

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import (
    ActivationCard,
    PricingPlan,
    UserAuthorization,
    UserAuthorizationCard,
)
from backend.h5_backend.services.shared.audit import append_audit_log, mask_actor_name
from backend.h5_backend.services.shared.card_utils import CARD_ALPHABET, generate_card_code
from backend.h5_backend.services.shared.pagination import paginate_items
from backend.h5_backend.services.shared.search import LIKE_ESCAPE_CHAR, contains_like_pattern
from backend.h5_backend.services.shared.serializers import serialize_pricing_plan

MAX_CARD_EXPORT_ROWS = 5000


def _serialize_card(card: ActivationCard) -> Dict[str, Any]:
    loaded_slot_usages = card.__dict__.get("slot_usages") or []
    first_usage = loaded_slot_usages[0] if loaded_slot_usages else None
    loaded_used_user = card.__dict__.get("used_by_user")
    bound_account = None
    if first_usage and first_usage.__dict__.get("slot") is not None:
        bound_account = first_usage.slot.__dict__.get("current_account")
    bound_account_name = None
    if bound_account is not None:
        bound_account_name = (
            bound_account.username
            or bound_account.phone
            or bound_account.first_name
            or (str(bound_account.tg_user_id) if bound_account.tg_user_id is not None else None)
        )
    return {
        "id": card.id,
        "card_code": card.card_code,
        "plan_code": card.plan_code,
        "duration_days": card.duration_days,
        "is_active": card.is_active,
        "is_used": card.is_used,
        "expires_at": card.expires_at.isoformat() if card.expires_at else None,
        "used_by_user_id": card.used_by_user_id,
        "used_by_username": loaded_used_user.username if loaded_used_user else None,
        "used_at": card.used_at.isoformat() if card.used_at else None,
        "authorization_id": first_usage.authorization_id if first_usage else None,
        "bound_account_id": (
            first_usage.slot.current_account_id
            if first_usage and first_usage.__dict__.get("slot") is not None
            else None
        ),
        "bound_account_name": bound_account_name,
        "authorization_end_at": (
            first_usage.slot.end_at.isoformat()
            if first_usage and first_usage.__dict__.get("slot") is not None and first_usage.slot.end_at
            else None
        ),
        "created_at": card.created_at.isoformat() if card.created_at else None,
        "updated_at": card.updated_at.isoformat() if card.updated_at else None,
    }


class CardsService:
    """Card generation, listing, export, and status management for admins."""

    async def generate_cards(
        self,
        plan_code: str,
        quantity: int,
        expires_at: Optional[datetime] = None,
        prefix: str = "",
        *,
        creator_account_id: Optional[int] = None,
        owner_account_id: Optional[int] = None,
        root_master_account_id: Optional[int] = None,
        direct_parent_account_id: Optional[int] = None,
        settlement_unit_price_cents: Optional[int] = None,
        card_source_type: str = "legacy",
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if quantity <= 0 or quantity > 500:
            raise HTTPException(status_code=400, detail="quantity 取值范围为 1~500")

        if expires_at and expires_at <= datetime.now():
            raise HTTPException(status_code=400, detail="expires_at 必须是未来时间")

        normalized_prefix = (prefix or "").strip().upper()
        if len(normalized_prefix) > 20:
            raise HTTPException(status_code=400, detail="prefix 最长 20 位")
        if normalized_prefix and not all(ch in CARD_ALPHABET for ch in normalized_prefix):
            raise HTTPException(status_code=400, detail="prefix 仅支持大写字母和数字")
        async with get_async_session() as session:
            try:
                plan_result = await session.execute(
                    select(PricingPlan).where(PricingPlan.plan_code == plan_code).limit(1)
                )
                plan = plan_result.scalar_one_or_none()
            except SQLAlchemyError as exc:
                logger.exception("查询套餐失败: plan_code={}, error={}", plan_code, exc)
                raise HTTPException(status_code=500, detail="查询套餐失败，请稍后重试") from exc
            if not plan:
                raise HTTPException(status_code=404, detail="套餐不存在")
            resolved_duration_days = int(plan.duration_days)
            if resolved_duration_days <= 0:
                raise HTTPException(status_code=400, detail="套餐时长无效，请检查卡密规格配置")
            generated_codes: set[str] = set()
            max_attempts = quantity * 20
            attempts = 0
            while len(generated_codes) < quantity and attempts < max_attempts:
                attempts += 1
                generated_codes.add(generate_card_code(prefix=normalized_prefix))

            if len(generated_codes) < quantity:
                raise HTTPException(status_code=500, detail="生成卡密失败，请重试")

            # 过滤数据库中已存在的编码（极低概率冲突，仍做防御）
            while True:
                existing_result = await session.execute(
                    select(ActivationCard.card_code).where(ActivationCard.card_code.in_(list(generated_codes)))
                )
                existing_codes = {row[0] for row in existing_result.all()}
                if not existing_codes:
                    break
                generated_codes -= existing_codes
                while len(generated_codes) < quantity:
                    generated_codes.add(generate_card_code(prefix=normalized_prefix))

            created_cards: List[ActivationCard] = [
                ActivationCard(
                    card_code=code,
                    plan_code=plan_code,
                    duration_days=resolved_duration_days,
                    is_active=True,
                    is_used=False,
                    expires_at=expires_at,
                    creator_account_id=creator_account_id,
                    owner_account_id=owner_account_id,
                    direct_parent_account_id=direct_parent_account_id,
                    root_master_account_id=root_master_account_id,
                    settlement_unit_price_cents=settlement_unit_price_cents if settlement_unit_price_cents is not None else int(plan.price_cents or 0),
                    card_source_type=(card_source_type or "").strip() or "legacy",
                )
                for code in sorted(generated_codes)
            ]
            session.add_all(created_cards)
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
                action="admin.generate_cards",
                target_type="plan",
                target_id=plan_code,
                detail={
                    "quantity": quantity,
                    "duration_days": resolved_duration_days,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                    "prefix": normalized_prefix,
                    "sample_card": created_cards[0].card_code if created_cards else None,
                },
                ip_address=ip_address,
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                logger.warning(
                    "生成卡密写入冲突: plan_code={}, quantity={}, prefix={}, error={}",
                    plan_code,
                    quantity,
                    normalized_prefix,
                    exc,
                )
                raise HTTPException(status_code=409, detail="生成卡密冲突，请稍后重试") from exc
            except SQLAlchemyError as exc:
                await session.rollback()
                logger.exception(
                    "生成卡密数据库异常: plan_code={}, quantity={}, prefix={}, error={}",
                    plan_code,
                    quantity,
                    normalized_prefix,
                    exc,
                )
                raise HTTPException(status_code=500, detail="生成卡密失败，请稍后重试") from exc
            for card in created_cards:
                await session.refresh(card)

        return [_serialize_card(card) for card in created_cards]

    async def list_cards(
        self,
        plan_code: Optional[str] = None,
        is_used: Optional[bool] = None,
        is_active: Optional[bool] = None,
        keyword: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        limit = max(1, min(500, int(limit)))
        offset = max(0, int(offset))

        stmt: Select[Any] = select(ActivationCard).options(
            selectinload(ActivationCard.slot_usages)
            .selectinload(UserAuthorizationCard.slot)
            .selectinload(UserAuthorization.current_account),
            selectinload(ActivationCard.used_by_user),
        )
        count_stmt: Select[Any] = select(func.count(ActivationCard.id))
        conditions = []
        if plan_code:
            conditions.append(ActivationCard.plan_code == plan_code)
        if is_used is not None:
            conditions.append(ActivationCard.is_used.is_(is_used))
        if is_active is not None:
            conditions.append(ActivationCard.is_active.is_(is_active))
        if keyword:
            keyword_value = contains_like_pattern(keyword.strip())
            conditions.append(
                ActivationCard.card_code.ilike(keyword_value, escape=LIKE_ESCAPE_CHAR)
                | ActivationCard.plan_code.ilike(keyword_value, escape=LIKE_ESCAPE_CHAR)
            )
        if conditions:
            stmt = stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))

        sortable_fields = {
            "created_at": ActivationCard.created_at,
            "used_at": ActivationCard.used_at,
            "expires_at": ActivationCard.expires_at,
        }
        sort_column = sortable_fields.get((sort_by or "").strip(), ActivationCard.created_at)
        sort_mode = (sort_order or "desc").strip().lower()
        if sort_mode == "asc":
            stmt = stmt.order_by(sort_column.asc().nullslast(), ActivationCard.id.desc())
        else:
            stmt = stmt.order_by(sort_column.desc().nullslast(), ActivationCard.id.desc())
        stmt = stmt.limit(limit).offset(offset)

        async with get_async_session() as session:
            total = int((await session.execute(count_stmt)).scalar_one() or 0)
            used_count_stmt: Select[Any] = select(func.count(ActivationCard.id))
            unused_count_stmt: Select[Any] = select(func.count(ActivationCard.id))
            used_conditions = list(conditions) + [ActivationCard.is_used.is_(True)]
            unused_conditions = list(conditions) + [ActivationCard.is_used.is_(False)]
            used_count_stmt = used_count_stmt.where(and_(*used_conditions))
            unused_count_stmt = unused_count_stmt.where(and_(*unused_conditions))
            used_total = int((await session.execute(used_count_stmt)).scalar_one() or 0)
            unused_total = int((await session.execute(unused_count_stmt)).scalar_one() or 0)
            result = await session.execute(stmt)
            cards = result.scalars().all()

        return {
            "items": [_serialize_card(card) for card in cards],
            "total": total,
            "limit": limit,
            "offset": offset,
            "stats": {
                "total": total,
                "used": used_total,
                "unused": unused_total,
            },
        }

    async def export_cards_xlsx(
        self,
        *,
        plan_code: Optional[str] = None,
        is_used: Optional[bool] = None,
        is_active: Optional[bool] = None,
        max_rows: int = MAX_CARD_EXPORT_ROWS,
    ) -> Tuple[bytes, int]:
        page_data = await self.list_cards(
            plan_code=plan_code,
            is_used=is_used,
            is_active=is_active,
            limit=max_rows + 1,
            offset=0,
        )
        rows = page_data["items"]
        if len(rows) > max_rows:
            raise HTTPException(
                status_code=400,
                detail=f"导出数量超过限制（最多 {max_rows} 条），请缩小筛选范围后重试",
            )

        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font
        except ModuleNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail="当前环境缺少 openpyxl，暂时无法导出 XLSX；但服务其他功能可正常使用。",
            ) from exc

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "卡密列表"

        headers = ["卡密", "套餐", "时长(天)", "状态", "激活用户", "激活时间", "创建时间", "失效时间"]
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)

        for row in rows:
            status = "已失效"
            if row.get("is_active"):
                status = "已使用" if row.get("is_used") else "可用"
            used_user = row.get("used_by_username") or (
                f"用户ID:{row['used_by_user_id']}" if row.get("used_by_user_id") is not None else ""
            )
            sheet.append(
                [
                    row.get("card_code") or "",
                    row.get("plan_code") or "",
                    row.get("duration_days") or "",
                    status,
                    used_user,
                    row.get("used_at") or "",
                    row.get("created_at") or "",
                    row.get("expires_at") or "",
                ]
            )

        sheet.column_dimensions["A"].width = 28
        sheet.column_dimensions["B"].width = 14
        sheet.column_dimensions["C"].width = 10
        sheet.column_dimensions["D"].width = 10
        sheet.column_dimensions["E"].width = 18
        sheet.column_dimensions["F"].width = 20
        sheet.column_dimensions["G"].width = 20
        sheet.column_dimensions["H"].width = 20

        buffer = BytesIO()
        workbook.save(buffer)
        workbook.close()
        return buffer.getvalue(), len(rows)

    async def set_card_active(
        self,
        card_code: str,
        is_active: bool,
        *,
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_code = (card_code or "").strip().upper()
        async with get_async_session() as session:
            result = await session.execute(
                select(ActivationCard)
                .where(ActivationCard.card_code == normalized_code)
                .limit(1)
            )
            card = result.scalar_one_or_none()
            if not card:
                raise HTTPException(status_code=404, detail="卡密不存在")

            if card.is_used and is_active:
                raise HTTPException(status_code=400, detail="已使用卡密不能重新启用")

            card.is_active = is_active
            await append_audit_log(
                session,
                actor=mask_actor_name(actor),
                action="admin.set_card_active",
                target_type="card",
                target_id=normalized_code,
                detail={"is_active": is_active, "is_used": card.is_used},
                ip_address=ip_address,
            )
            await session.commit()
            await session.refresh(card)

        return _serialize_card(card)

    async def create_single_card(
        self,
        plan_code: str,
        valid_days: Optional[int] = None,
        prefix: str = "",
        *,
        creator_account_id: Optional[int] = None,
        owner_account_id: Optional[int] = None,
        root_master_account_id: Optional[int] = None,
        direct_parent_account_id: Optional[int] = None,
        settlement_unit_price_cents: Optional[int] = None,
        card_source_type: str = "legacy",
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        expires_at = None
        if valid_days is not None:
            if valid_days <= 0:
                raise HTTPException(status_code=400, detail="valid_days 必须大于 0")
            expires_at = datetime.now() + timedelta(days=valid_days)

        cards = await self.generate_cards(
            plan_code=plan_code,
            quantity=1,
            expires_at=expires_at,
            prefix=prefix,
            creator_account_id=creator_account_id,
            owner_account_id=owner_account_id,
            root_master_account_id=root_master_account_id,
            direct_parent_account_id=direct_parent_account_id,
            settlement_unit_price_cents=settlement_unit_price_cents,
            card_source_type=card_source_type,
            actor=actor,
            ip_address=ip_address,
        )
        return cards[0]


_card_service: CardsService | None = None


def get_card_service() -> CardsService:
    global _card_service
    if _card_service is None:
        _card_service = CardsService()
    return _card_service
