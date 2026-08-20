"""Auditable V1 inventory and account-serial V2 migration."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Optional

from sqlalchemy import select, update

from backend.bot.account.manager import get_account_manager
from backend.bot.account.reauth import is_reauth_required_account
from backend.database.runtime.session import get_async_session
from backend.database.schema.models import MediaType, ScheduledMessageTask
from backend.task_media.contract import TaskMediaError, classify_message_media, utc_now

LEGACY_REF_PREFIX = "tgmsg://"
DEFAULT_BATCH_SIZE = 50
ACCOUNT_AUTH_ERROR_TYPES = frozenset(
    {
        "AuthKeyUnregisteredError",
        "SessionRevokedError",
        "UserDeactivatedError",
        "UserDeactivatedBanError",
    }
)


@dataclass(frozen=True)
class V1TaskSnapshot:
    task_id: str
    account_id: str
    revision: int
    media_type: str
    media_file_id: Optional[str]
    has_buttons: bool
    media_source_state: str
    media_source_error_code: Optional[str]


def parse_legacy_media_ref(raw_value: str | None) -> tuple[str, int]:
    raw = str(raw_value or "").strip()
    if not raw.startswith(LEGACY_REF_PREFIX):
        code = (
            "LEGACY_MEDIA_LOCAL_PATH"
            if os.path.isabs(raw)
            else "LEGACY_MEDIA_UNKNOWN_REF"
        )
        raise TaskMediaError(code, "旧媒体引用不是可迁移的 Telegram 收藏夹引用")
    account_id, separator, message_id = raw[len(LEGACY_REF_PREFIX) :].partition("/")
    if not account_id or not separator:
        raise TaskMediaError("LEGACY_MEDIA_UNKNOWN_REF", "旧 Telegram 媒体引用格式错误")
    try:
        return account_id, int(message_id)
    except ValueError as exc:
        raise TaskMediaError(
            "LEGACY_MEDIA_UNKNOWN_REF", "旧 Telegram 消息 ID 非法"
        ) from exc


async def inventory_v1_media_tasks() -> dict:
    """Return an overlapping, independently auditable read-only inventory."""
    async with get_async_session() as session:
        tasks = list(
            (
                await session.scalars(
                    select(ScheduledMessageTask).where(
                        ScheduledMessageTask.content_contract_version == 1,
                        ScheduledMessageTask.media_type != MediaType.NONE,
                    )
                )
            ).all()
        )
    categories = {
        "telegram_ref": [],
        "sticker": [],
        "local_path": [],
        "unknown_ref": [],
        "buttons": [],
        "enabled": [],
        "account_mismatch": [],
    }
    for task in tasks:
        _categorize_inventory_task(task, categories)
    return {
        "total_v1_media_tasks": len(tasks),
        "categories": {
            name: {"count": len(task_ids), "task_ids": task_ids}
            for name, task_ids in categories.items()
        },
    }


def _categorize_inventory_task(task, categories: dict) -> None:
    raw_ref = str(task.media_file_id or "").strip()
    if (
        str(getattr(task.media_type, "value", task.media_type))
        == MediaType.STICKER.value
    ):
        categories["sticker"].append(task.task_id)
    if task.buttons:
        categories["buttons"].append(task.task_id)
    if task.enabled:
        categories["enabled"].append(task.task_id)
    try:
        ref_account_id, _ = parse_legacy_media_ref(raw_ref)
        categories["telegram_ref"].append(task.task_id)
        if ref_account_id != task.account_id:
            categories["account_mismatch"].append(task.task_id)
    except TaskMediaError as exc:
        target = (
            "local_path" if exc.code == "LEGACY_MEDIA_LOCAL_PATH" else "unknown_ref"
        )
        categories[target].append(task.task_id)


async def migrate_account_batch(
    *, account_id: str, limit: int = DEFAULT_BATCH_SIZE
) -> dict:
    """Migrate one bounded account batch serially; a single task failure is retained."""
    snapshots = await _load_account_batch(account_id=account_id, limit=limit)
    client = await _open_migration_client(account_id)
    result = {"planned": len(snapshots), "migrated": 0, "failed": 0, "conflict": 0}
    for snapshot in snapshots:
        try:
            outcome = await _migrate_snapshot(client=client, snapshot=snapshot)
        except TaskMediaError as exc:
            result["stopped_error_code"] = exc.code
            break
        result[outcome] += 1
    result["remaining"] = await _count_remaining(account_id)
    result["blocked"] = await _count_blocked(account_id)
    return result


async def _open_migration_client(account_id: str):
    manager = get_account_manager()
    account = await manager.get_account(account_id)
    if is_reauth_required_account(account):
        raise TaskMediaError(
            "MIGRATION_ACCOUNT_REAUTH_REQUIRED", "迁移账号需要重新授权"
        )
    try:
        client = await manager.get_client(account_id)
    except Exception as exc:
        raise TaskMediaError(
            "MIGRATION_ACCOUNT_CLIENT_UNAVAILABLE", "迁移账号客户端连接失败"
        ) from exc
    if not client:
        account = await manager.get_account(account_id)
        if is_reauth_required_account(account):
            raise TaskMediaError(
                "MIGRATION_ACCOUNT_REAUTH_REQUIRED", "迁移账号需要重新授权"
            )
        raise TaskMediaError(
            "MIGRATION_ACCOUNT_CLIENT_UNAVAILABLE", "迁移账号客户端不可用"
        )
    try:
        authorized = await client.is_user_authorized()
    except Exception as exc:
        raise TaskMediaError(
            "MIGRATION_ACCOUNT_CLIENT_UNAVAILABLE", "无法校验迁移账号授权状态"
        ) from exc
    if not authorized:
        raise TaskMediaError(
            "MIGRATION_ACCOUNT_REAUTH_REQUIRED", "迁移账号需要重新授权"
        )
    return client


async def _load_account_batch(*, account_id: str, limit: int) -> list[V1TaskSnapshot]:
    async with get_async_session() as session:
        tasks = list(
            (
                await session.scalars(
                    select(ScheduledMessageTask)
                    .where(
                        ScheduledMessageTask.account_id == account_id,
                        ScheduledMessageTask.content_contract_version == 1,
                        ScheduledMessageTask.media_type != MediaType.NONE,
                        ScheduledMessageTask.media_source_state != "invalid",
                    )
                    .order_by(ScheduledMessageTask.created_at.asc())
                    .limit(limit)
                )
            ).all()
        )
    return [
        V1TaskSnapshot(
            task_id=task.task_id,
            account_id=str(task.account_id),
            revision=int(task.revision),
            media_type=str(getattr(task.media_type, "value", task.media_type)),
            media_file_id=task.media_file_id,
            has_buttons=bool(task.buttons),
            media_source_state=str(task.media_source_state or "none"),
            media_source_error_code=task.media_source_error_code,
        )
        for task in tasks
    ]


async def _migrate_snapshot(*, client, snapshot: V1TaskSnapshot) -> str:
    try:
        media_message_id = _validate_snapshot(snapshot)
        source = await _read_legacy_source(client, media_message_id)
        if not source:
            raise TaskMediaError("MEDIA_SOURCE_UNAVAILABLE", "旧收藏夹消息不存在")
        classified = classify_message_media(source)
        if classified.media_type != snapshot.media_type:
            raise TaskMediaError("MEDIA_SOURCE_TYPE_CHANGED", "旧收藏夹媒体类型已变化")
        return await _write_migration_success(
            snapshot=snapshot, source=source, meta=classified.meta
        )
    except TaskMediaError as exc:
        if exc.code == "MIGRATION_ACCOUNT_REAUTH_REQUIRED":
            raise
        return await _write_migration_failure(snapshot=snapshot, error_code=exc.code)


async def _read_legacy_source(client, message_id: int):
    try:
        return await client.get_messages("me", ids=message_id)
    except Exception as exc:
        if type(exc).__name__ in ACCOUNT_AUTH_ERROR_TYPES:
            raise TaskMediaError(
                "MIGRATION_ACCOUNT_REAUTH_REQUIRED", "迁移账号授权已失效"
            ) from exc
        raise TaskMediaError(
            "MEDIA_SOURCE_UNAVAILABLE", "旧收藏夹媒体回读失败"
        ) from exc


def _validate_snapshot(snapshot: V1TaskSnapshot) -> int:
    if snapshot.has_buttons:
        raise TaskMediaError(
            "TASK_BUTTONS_UNSUPPORTED_FOR_USER_ACCOUNT", "旧任务仍有消息按钮"
        )
    if snapshot.media_type == MediaType.STICKER.value:
        raise TaskMediaError("MEDIA_SOURCE_TYPE_UNSUPPORTED", "V2 不支持贴纸")
    ref_account_id, message_id = parse_legacy_media_ref(snapshot.media_file_id)
    if ref_account_id != snapshot.account_id:
        raise TaskMediaError("MEDIA_SOURCE_ACCOUNT_MISMATCH", "旧媒体引用账号不匹配")
    return message_id


async def _write_migration_success(
    *, snapshot: V1TaskSnapshot, source, meta: dict
) -> str:
    now = utc_now()
    async with get_async_session() as session:
        result = await session.execute(
            update(ScheduledMessageTask)
            .where(
                ScheduledMessageTask.task_id == snapshot.task_id,
                ScheduledMessageTask.revision == snapshot.revision,
                ScheduledMessageTask.content_contract_version == 1,
            )
            .values(
                content_contract_version=2,
                media_source_account_id=snapshot.account_id,
                media_source_message_id=int(source.id),
                media_source_meta=meta,
                media_source_state="valid",
                media_source_error_code=None,
                media_source_verified_at=now,
                revision=ScheduledMessageTask.revision + 1,
                updated_at=now,
            )
        )
    return "migrated" if result.rowcount == 1 else "conflict"


async def _write_migration_failure(*, snapshot: V1TaskSnapshot, error_code: str) -> str:
    if (
        snapshot.media_source_state == "invalid"
        and snapshot.media_source_error_code == error_code
    ):
        return "failed"
    async with get_async_session() as session:
        result = await session.execute(
            update(ScheduledMessageTask)
            .where(
                ScheduledMessageTask.task_id == snapshot.task_id,
                ScheduledMessageTask.revision == snapshot.revision,
                ScheduledMessageTask.content_contract_version == 1,
            )
            .values(
                media_source_state="invalid",
                media_source_error_code=error_code,
                revision=ScheduledMessageTask.revision + 1,
                updated_at=utc_now(),
            )
        )
    return "failed" if result.rowcount == 1 else "conflict"


async def _count_remaining(account_id: str) -> int:
    async with get_async_session() as session:
        rows = await session.scalars(
            select(ScheduledMessageTask.task_id).where(
                ScheduledMessageTask.account_id == account_id,
                ScheduledMessageTask.content_contract_version == 1,
                ScheduledMessageTask.media_type != MediaType.NONE,
            )
        )
        return len(list(rows.all()))


async def _count_blocked(account_id: str) -> int:
    async with get_async_session() as session:
        rows = await session.scalars(
            select(ScheduledMessageTask.task_id).where(
                ScheduledMessageTask.account_id == account_id,
                ScheduledMessageTask.content_contract_version == 1,
                ScheduledMessageTask.media_type != MediaType.NONE,
                ScheduledMessageTask.media_source_state == "invalid",
            )
        )
        return len(list(rows.all()))
