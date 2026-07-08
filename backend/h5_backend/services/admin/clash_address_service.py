"""Clash subscription/config address management."""
from __future__ import annotations

import asyncio
import os
import re
import shlex
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from fastapi import HTTPException
from sqlalchemy import select, update

from backend.database.runtime.session import get_async_session
from backend.database.schema.models import ClashAddress
from backend.h5_backend.services.shared.audit import append_audit_log, mask_actor_name
from backend.h5_backend.services.shared.pagination import paginate_items
from backend.utils.url_validation import is_valid_button_url

TOKEN_VALUE_RE = re.compile(r"([?&][^=&]*(?:token|key|secret|sub|url)[^=]*=)([^&]+)", re.IGNORECASE)
DEFAULT_APPLY_TIMEOUT_SECONDS = 120


class ClashAddressApplier(Protocol):
    async def apply(self, url: str) -> None:
        """Apply an active Clash URL to the external proxy runtime."""


class CommandClashAddressApplier:
    """Apply a Clash URL by updating a subscription file and running a sync command."""

    def __init__(
        self,
        *,
        subscription_url_file: Optional[str] = None,
        apply_command: Optional[str] = None,
        timeout_seconds: int = DEFAULT_APPLY_TIMEOUT_SECONDS,
    ) -> None:
        self._subscription_url_file = subscription_url_file or os.getenv("CLASH_ADDRESS_SUBSCRIPTION_URL_FILE", "")
        self._apply_command = apply_command or os.getenv("CLASH_ADDRESS_APPLY_COMMAND", "")
        self._timeout_seconds = int(os.getenv("CLASH_ADDRESS_APPLY_TIMEOUT_SECONDS", str(timeout_seconds)))

    async def apply(self, url: str) -> None:
        target = self._require_subscription_file()
        command = self._require_apply_command()
        previous = target.read_text(encoding="utf-8") if target.exists() else None
        self._write_subscription_url(target, url)
        try:
            await self._run_apply_command(command)
        except Exception:
            self._restore_subscription_url(target, previous)
            raise

    def _require_subscription_file(self) -> Path:
        if not self._subscription_url_file:
            raise HTTPException(status_code=503, detail="Clash 地址订阅文件未配置，无法启用")
        target = Path(self._subscription_url_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _require_apply_command(self) -> list[str]:
        if not self._apply_command:
            raise HTTPException(status_code=503, detail="Clash 地址应用命令未配置，无法启用")
        return shlex.split(self._apply_command)

    @staticmethod
    def _write_subscription_url(target: Path, url: str) -> None:
        tmp = target.with_suffix(f"{target.suffix}.next")
        tmp.write_text(url.strip() + "\n", encoding="utf-8")
        os.replace(tmp, target)

    @staticmethod
    def _restore_subscription_url(target: Path, previous: Optional[str]) -> None:
        if previous is None:
            target.unlink(missing_ok=True)
            return
        target.write_text(previous, encoding="utf-8")

    async def _run_apply_command(self, command: list[str]) -> None:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self._timeout_seconds)
        if process.returncode != 0:
            detail = self._format_command_error(stderr=stderr, stdout=stdout)
            raise HTTPException(status_code=502, detail=detail)

    @staticmethod
    def _format_command_error(*, stderr: bytes, stdout: bytes) -> str:
        output = (stderr or stdout).decode("utf-8", errors="replace").strip()
        if not output:
            return "Clash 地址应用命令执行失败"
        return f"Clash 地址应用命令执行失败: {output[-500:]}"


def _mask_secret(value: str) -> str:
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def mask_clash_url(url: str) -> str:
    masked = TOKEN_VALUE_RE.sub(lambda match: f"{match.group(1)}{_mask_secret(match.group(2))}", url)
    if masked != url:
        return masked
    if len(url) <= 16:
        return _mask_secret(url)
    return f"{url[:12]}***{url[-4:]}"


def _normalize_name(name: str) -> str:
    normalized = str(name or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Clash 地址名称不能为空")
    return normalized


def _normalize_url(url: str) -> str:
    normalized = str(url or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Clash 地址不能为空")
    if not is_valid_button_url(normalized):
        raise HTTPException(status_code=400, detail="Clash 地址格式无效，请填写公网 http/https URL")
    return normalized


class ClashAddressService:
    """CRUD service for Clash subscription/config URLs."""

    def __init__(self, *, applier: Optional[ClashAddressApplier] = None) -> None:
        self._applier = applier or CommandClashAddressApplier()

    @staticmethod
    def _serialize(row: ClashAddress) -> Dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "url_masked": mask_clash_url(row.url),
            "is_active": bool(row.is_active),
            "remark": row.remark or "",
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def list_addresses(self, *, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        async with get_async_session() as session:
            rows = (
                await session.execute(
                    select(ClashAddress).order_by(ClashAddress.is_active.desc(), ClashAddress.id.asc())
                )
            ).scalars().all()
        return paginate_items([self._serialize(row) for row in rows], limit=limit, offset=offset)

    async def create_address(
        self,
        *,
        name: str,
        url: str,
        is_active: bool = False,
        remark: str = "",
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        row = ClashAddress(name=_normalize_name(name), url=_normalize_url(url), is_active=bool(is_active), remark=remark.strip())
        async with get_async_session() as session:
            if row.is_active:
                await self._applier.apply(row.url)
                await self._deactivate_all(session)
            session.add(row)
            await session.flush()
            await self._audit(session, actor=actor, action="admin.create_clash_address", row=row, ip_address=ip_address)
            await session.commit()
        return self._serialize(row)

    async def update_address(
        self,
        address_id: int,
        *,
        name: str,
        url: Optional[str],
        is_active: bool,
        remark: str = "",
        actor: str = "admin",
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        async with get_async_session() as session:
            row = await self._get_existing(session, address_id)
            row.name = _normalize_name(name)
            if url is not None:
                row.url = _normalize_url(url)
            row.remark = remark.strip()
            if row.is_active and not is_active:
                raise HTTPException(status_code=400, detail="当前启用的 Clash 地址不能直接停用，请先启用其他地址")
            if is_active:
                await self._applier.apply(row.url)
                await self._deactivate_all(session)
            row.is_active = bool(is_active)
            await self._audit(session, actor=actor, action="admin.update_clash_address", row=row, ip_address=ip_address)
            await session.commit()
        return self._serialize(row)

    async def delete_address(self, address_id: int, *, actor: str = "admin", ip_address: Optional[str] = None) -> None:
        async with get_async_session() as session:
            row = await self._get_existing(session, address_id)
            if row.is_active:
                raise HTTPException(status_code=400, detail="当前启用的 Clash 地址不能删除，请先启用其他地址")
            await self._audit(session, actor=actor, action="admin.delete_clash_address", row=row, ip_address=ip_address)
            await session.delete(row)
            await session.commit()

    async def activate_address(self, address_id: int, *, actor: str = "admin", ip_address: Optional[str] = None) -> Dict[str, Any]:
        async with get_async_session() as session:
            row = await self._get_existing(session, address_id)
            await self._applier.apply(row.url)
            await self._deactivate_all(session)
            row.is_active = True
            await self._audit(session, actor=actor, action="admin.activate_clash_address", row=row, ip_address=ip_address)
            await session.commit()
        return self._serialize(row)

    @staticmethod
    async def _deactivate_all(session) -> None:
        await session.execute(update(ClashAddress).where(ClashAddress.is_active.is_(True)).values(is_active=False))

    @staticmethod
    async def _get_existing(session, address_id: int) -> ClashAddress:
        row = await session.get(ClashAddress, address_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Clash 地址不存在")
        return row

    @staticmethod
    async def _audit(session, *, actor: str, action: str, row: ClashAddress, ip_address: Optional[str]) -> None:
        await append_audit_log(
            session,
            actor=mask_actor_name(actor),
            action=action,
            target_type="clash_address",
            target_id=str(row.id),
            detail={"name": row.name, "url_masked": mask_clash_url(row.url), "is_active": bool(row.is_active)},
            ip_address=ip_address,
        )


_clash_address_service: ClashAddressService | None = None


def get_clash_address_service() -> ClashAddressService:
    global _clash_address_service
    if _clash_address_service is None:
        _clash_address_service = ClashAddressService()
    return _clash_address_service
