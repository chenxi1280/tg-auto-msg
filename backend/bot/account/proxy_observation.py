"""Fixed account proxy regions and 24-hour observation helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select

from backend.database.schema.models import Account, HealthStatus, Proxy

OBSERVATION_HOURS = 24
OBSERVATION_SUCCESS_LIMIT = 1
REAUTH_PROXY_SELECTED_REASON = "proxy_region_selected"


@dataclass(frozen=True)
class ProxyRegion:
    code: str
    label: str
    host: str
    port: int


SING_BOX_PROXY_REGIONS: tuple[ProxyRegion, ...] = (
    ProxyRegion("hk", "香港", "sing-box", 10801),
    ProxyRegion("tw", "台湾", "sing-box", 10802),
    ProxyRegion("jp", "日本", "sing-box", 10803),
    ProxyRegion("sg", "新加坡", "sing-box", 10804),
    ProxyRegion("us1", "美国1", "sing-box", 10805),
    ProxyRegion("us2", "美国2", "sing-box", 10806),
    ProxyRegion("uk", "英国", "sing-box", 10807),
)

REGION_BY_CODE = {region.code: region for region in SING_BOX_PROXY_REGIONS}


def normalize_region_code(region_code: str) -> str:
    normalized = str(region_code or "").strip().lower()
    if normalized not in REGION_BY_CODE:
        raise HTTPException(status_code=400, detail="不支持的代理地区")
    return normalized


def get_proxy_region_options() -> list[dict[str, Any]]:
    return [
        {
            "region_code": region.code,
            "label": region.label,
            "proxy_type": "socks5",
            "host": region.host,
            "port": region.port,
            "endpoint": f"socks5://{region.host}:{region.port}",
        }
        for region in SING_BOX_PROXY_REGIONS
    ]


async def upsert_sing_box_proxy_region(session, region: ProxyRegion) -> Proxy:
    row = (
        await session.execute(
            select(Proxy).where(
                Proxy.proxy_type == "socks5",
                Proxy.host == region.host,
                Proxy.port == region.port,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = Proxy(
            proxy_type="socks5",
            host=region.host,
            port=region.port,
            display_name=region.label,
            region_code=region.code,
            is_system_gateway=True,
            is_shared=True,
            is_active=True,
            is_healthy=True,
            assigned_account_id=None,
        )
        session.add(row)
        await session.flush()
    else:
        row.display_name = region.label
        row.region_code = region.code
        row.is_system_gateway = True
        row.is_shared = True
        row.is_active = True
        row.assigned_account_id = None
        row.username = None
        row.password_encrypted = None
    return row


async def ensure_sing_box_proxy_region(session, region_code: str) -> Proxy:
    region = REGION_BY_CODE[normalize_region_code(region_code)]
    return await upsert_sing_box_proxy_region(session, region)


def is_proxy_observation_active(account: Any, now: Optional[datetime] = None) -> bool:
    until = getattr(account, "proxy_observation_until", None)
    if until is None:
        return False
    return (now or datetime.now()) < until


def proxy_observation_remaining_seconds(account: Any, now: Optional[datetime] = None) -> int:
    until = getattr(account, "proxy_observation_until", None)
    if until is None:
        return 0
    remaining = int((until - (now or datetime.now())).total_seconds())
    return max(0, remaining)


def proxy_observation_has_send_budget(account: Any, now: Optional[datetime] = None) -> bool:
    if not is_proxy_observation_active(account, now):
        return True
    count = int(getattr(account, "proxy_observation_success_count", 0) or 0)
    return count < OBSERVATION_SUCCESS_LIMIT


def format_observation_block_message(account: Any) -> str:
    remaining = proxy_observation_remaining_seconds(account)
    hours = max(1, (remaining + 3599) // 3600) if remaining else 0
    if hours:
        return f"账号正在代理观察期内，约 {hours} 小时后恢复正常。观察期内暂不可新建任务。"
    return "账号正在代理观察期内，暂不可新建任务。"


def start_proxy_observation(account: Account, *, now: Optional[datetime] = None) -> None:
    started_at = now or datetime.now()
    account.proxy_observation_started_at = started_at
    account.proxy_observation_until = started_at + timedelta(hours=OBSERVATION_HOURS)
    account.proxy_observation_success_count = 0


async def mark_proxy_observation_success(session, account_id: str, *, now: Optional[datetime] = None) -> int:
    account = await session.get(Account, str(account_id))
    if account is None or not is_proxy_observation_active(account, now):
        return 0
    account.proxy_observation_success_count = min(
        OBSERVATION_SUCCESS_LIMIT,
        int(account.proxy_observation_success_count or 0) + 1,
    )
    return int(account.proxy_observation_success_count or 0)


async def select_reauth_proxy_for_account(
    session,
    *,
    user_id: int,
    account_id: str,
    region_code: str,
) -> dict[str, Any]:
    account = await session.get(Account, str(account_id))
    if account is None or int(account.user_id) != int(user_id):
        raise HTTPException(status_code=404, detail="账号不存在")

    proxy = await ensure_sing_box_proxy_region(session, region_code)
    if account.proxy_id and int(account.proxy_id) != int(proxy.proxy_id):
        old_proxy = await session.get(Proxy, int(account.proxy_id))
        if old_proxy and old_proxy.assigned_account_id == str(account_id):
            old_proxy.assigned_account_id = None

    account.proxy_id = proxy.proxy_id
    account.reauth_required = True
    account.reauth_reason = REAUTH_PROXY_SELECTED_REASON
    account.reauth_required_at = datetime.now()
    account.health_status = HealthStatus.OFFLINE
    account.proxy_observation_started_at = None
    account.proxy_observation_until = None
    account.proxy_observation_success_count = 0
    await session.flush()

    logger.info(
        "账号已选择固定代理等待重绑: account_id={}, region={}, proxy_id={}",
        account_id,
        proxy.region_code,
        proxy.proxy_id,
    )
    return {
        "account_id": str(account.account_id),
        "proxy_id": int(proxy.proxy_id),
        "region_code": str(proxy.region_code or ""),
        "region_label": str(proxy.display_name or ""),
        "endpoint": f"{proxy.proxy_type}://{proxy.host}:{proxy.port}",
    }


async def assert_account_can_create_task(account_id: Optional[str], *, session) -> None:
    if not account_id:
        return
    account = await session.get(Account, str(account_id))
    if account is not None and is_proxy_observation_active(account):
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=format_observation_block_message(account),
        )
