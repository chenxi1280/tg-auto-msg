"""Task execution helpers for scheduler worker."""
from __future__ import annotations

import os
import re
from typing import Optional

from loguru import logger
from telethon import helpers
from telethon.extensions import html as telethon_html
from telethon.tl import types

from backend.bot.circuit.breaker import get_circuit_breaker
from backend.bot.safety.rate_limiter import get_rate_limiter
from backend.database.schema.models import MediaType, ScheduledMessageTask
from backend.scheduler.core.task_media_runtime import resolve_v2_task_media
from backend.task_media.contract import TaskMediaError, validate_message_length

TARGET_DELIVERY_SUSPENDED = "suspended"
TELEGRAM_USERNAME_PATTERN = re.compile(r"@[A-Za-z0-9_]{5,32}")
TELEGRAM_URL_PATTERN = re.compile(
    r"(?:https?://|tg://)[^\s<]+|(?<![\w/])t\.me/[A-Za-z0-9_/?=&%+.-]+"
)


def count_configured_task_targets(task: ScheduledMessageTask) -> int:
    """Return total valid targets regardless of suspended runtime state."""
    raw_targets = getattr(task, "target_peers", None)
    count = 0
    if isinstance(raw_targets, list):
        for item in raw_targets:
            if not isinstance(item, dict):
                continue
            try:
                int(item.get("peer_id"))
            except Exception:
                continue
            peer_type = str(item.get("peer_type") or "").strip().lower()
            if peer_type in {"user", "chat", "supergroup", "channel"}:
                count += 1
    elif task.target_peer_id or task.chat_id:
        count = 1
    return count


def collect_task_targets(task: ScheduledMessageTask) -> list[dict]:
    """Collect target peers from task, compatible with new/legacy fields."""
    targets: list[dict] = []
    has_explicit_target_peers = False

    raw_targets = getattr(task, "target_peers", None)
    if isinstance(raw_targets, list):
        for item in raw_targets:
            if not isinstance(item, dict):
                continue
            try:
                peer_id = int(item.get("peer_id"))
            except Exception:
                continue
            peer_type = str(item.get("peer_type") or "").strip().lower()
            if peer_type not in {"user", "chat", "supergroup", "channel"}:
                continue
            has_explicit_target_peers = True
            delivery_status = str(item.get("delivery_status") or "").strip().lower()
            if delivery_status == TARGET_DELIVERY_SUSPENDED:
                continue
            access_hash = item.get("access_hash")
            if access_hash not in (None, ""):
                try:
                    access_hash = int(access_hash)
                except Exception:
                    access_hash = None
            targets.append(
                {
                    "peer_id": peer_id,
                    "peer_type": peer_type,
                    "access_hash": access_hash,
                    "title": (str(item.get("title") or "").strip() or None),
                }
            )

    if not targets and not has_explicit_target_peers:
        target_peer_id = task.target_peer_id or task.chat_id
        if target_peer_id:
            fallback_peer_type = str(task.target_peer_type or "user").strip().lower()
            if fallback_peer_type not in {"user", "chat", "supergroup", "channel"}:
                fallback_peer_type = "user"
            targets.append(
                {
                    "peer_id": int(target_peer_id),
                    "peer_type": fallback_peer_type,
                    "access_hash": task.target_access_hash,
                }
            )

    deduped: list[dict] = []
    seen = set()
    for target in targets:
        key = (target["peer_type"], target["peer_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(target)
    return deduped


def get_target_last_message_id(
    task: ScheduledMessageTask,
    *,
    target_peer_id: int,
    target_peer_type: Optional[str],
) -> Optional[int]:
    """Return the last sent message id for one specific target."""
    peer_type = str(target_peer_type or task.target_peer_type or "").strip().lower()

    raw_targets = getattr(task, "target_peers", None)
    if isinstance(raw_targets, list):
        for item in raw_targets:
            if not isinstance(item, dict):
                continue
            try:
                peer_id = int(item.get("peer_id"))
            except Exception:
                continue
            item_peer_type = str(item.get("peer_type") or "").strip().lower()
            if peer_id == int(target_peer_id) and item_peer_type == peer_type:
                message_id = item.get("last_sent_message_id")
                if message_id in (None, ""):
                    return task.last_sent_message_id
                try:
                    return int(message_id)
                except Exception:
                    return task.last_sent_message_id

    return task.last_sent_message_id


def update_task_target_last_message_ids(
    task: ScheduledMessageTask,
    *,
    target_message_ids: dict[tuple[str, int], int],
) -> None:
    """Persist last message ids back into task target metadata."""
    raw_targets = getattr(task, "target_peers", None)
    if isinstance(raw_targets, list) and raw_targets:
        updated_targets: list[dict] = []
        for item in raw_targets:
            if not isinstance(item, dict):
                updated_targets.append(item)
                continue
            updated_item = dict(item)
            try:
                peer_id = int(updated_item.get("peer_id"))
            except Exception:
                updated_targets.append(updated_item)
                continue
            peer_type = str(updated_item.get("peer_type") or "").strip().lower()
            message_id = target_message_ids.get((peer_type, peer_id))
            if message_id:
                updated_item["last_sent_message_id"] = int(message_id)
            updated_targets.append(updated_item)
        task.target_peers = updated_targets

    if len(target_message_ids) == 1:
        task.last_sent_message_id = next(iter(target_message_ids.values()))
    elif target_message_ids:
        task.last_sent_message_id = next(reversed(list(target_message_ids.values())))


async def resolve_send_target(
    *,
    client,
    task: ScheduledMessageTask,
    target_peer_id: int,
    target_peer_type: Optional[str],
    target_access_hash: Optional[int],
    resource_manager,
):
    """Resolve a reliable send target entity with DB-resource-first strategy."""
    peer_type = target_peer_type or task.target_peer_type
    access_hash = (
        target_access_hash if target_access_hash is not None else task.target_access_hash
    )

    if task.account_id and peer_type:
        try:
            input_peer = await resource_manager.get_input_peer(
                account_id=task.account_id,
                peer_id=target_peer_id,
                peer_type=peer_type,
                access_hash=access_hash,
            )
            if input_peer is not None:
                return input_peer
        except Exception as e:
            logger.warning(
                "任务 {} 使用资源表解析目标失败，回退 get_input_entity: "
                "peer_id={}, peer_type={}, error={}",
                task.task_id, target_peer_id, peer_type, e,
            )

    try:
        return await client.get_input_entity(target_peer_id)
    except Exception as e:
        logger.warning(
            "任务 {} get_input_entity 解析失败: peer_id={}, error={}",
            task.task_id, target_peer_id, e,
        )

    try:
        dialogs = await client.get_dialogs()
        for dialog in dialogs:
            entity = dialog.entity
            if getattr(entity, "id", None) == target_peer_id:
                return entity
    except Exception as e:
        logger.warning(
            "任务 {} 从 dialogs 回填实体失败: peer_id={}, error={}",
            task.task_id, target_peer_id, e,
        )

    return target_peer_id


async def resolve_task_media(
    *,
    client,
    media_file_id: str,
    account_id: Optional[str],
    media_ref_prefix: str,
):
    """Resolve media source by reference or fallback raw payload."""
    raw = str(media_file_id or "").strip()
    if not raw.startswith(media_ref_prefix):
        return raw

    payload = raw[len(media_ref_prefix) :]
    parts = payload.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"无效的 Telegram 媒体引用: {media_file_id}")

    ref_account_id, msg_id_raw = parts
    if account_id and ref_account_id and account_id != ref_account_id:
        raise ValueError("媒体所属账号与当前执行账号不一致，请在当前执行账号下重新上传媒体")

    try:
        message_id = int(msg_id_raw)
    except ValueError:
        raise ValueError(f"无效的 Telegram 媒体消息 ID: {msg_id_raw}")

    stored_msg = await client.get_messages("me", ids=message_id)
    if not stored_msg or not getattr(stored_msg, "media", None):
        raise ValueError("媒体引用已失效（收藏夹消息不存在或不含媒体），请重新上传媒体")

    return stored_msg.media


def _entity_bounds(entity) -> tuple[int, int]:
    start = int(getattr(entity, "offset", 0) or 0)
    return start, start + int(getattr(entity, "length", 0) or 0)


def _entity_overlaps(entity, start: int, end: int) -> bool:
    entity_start, entity_end = _entity_bounds(entity)
    return start < entity_end and end > entity_start


def _has_existing_link_entity(entities: list, start: int, end: int) -> bool:
    link_entity_types = (
        types.MessageEntityMention,
        types.MessageEntityTextUrl,
        types.MessageEntityUrl,
    )
    return any(
        isinstance(entity, link_entity_types) and _entity_overlaps(entity, start, end)
        for entity in entities
    )


def build_telegram_text_and_entities(text: Optional[str]) -> tuple[Optional[str], Optional[list]]:
    """Parse configured HTML text and add explicit entities for raw usernames/URLs."""
    if not text:
        return text, None

    parsed_text, entities = telethon_html.parse(text)
    entities = list(entities or [])
    surrogate_text = helpers.add_surrogate(parsed_text)

    for match in TELEGRAM_USERNAME_PATTERN.finditer(surrogate_text):
        start, end = match.span()
        if _has_existing_link_entity(entities, start, end):
            continue
        entities.append(types.MessageEntityMention(offset=start, length=end - start))

    for match in TELEGRAM_URL_PATTERN.finditer(surrogate_text):
        start, end = match.span()
        if _has_existing_link_entity(entities, start, end):
            continue
        entities.append(types.MessageEntityUrl(offset=start, length=end - start))

    entities.sort(key=lambda entity: (int(getattr(entity, "offset", 0) or 0), -int(getattr(entity, "length", 0) or 0)))
    return parsed_text, entities or None


async def do_send_message(
    *,
    client,
    task: ScheduledMessageTask,
    send_target,
    previous_message_id: Optional[int],
    media_ref_prefix: str,
) -> Optional[int]:
    """Send one task message and return sent message id."""
    send_text, formatting_entities = _prepare_task_content(task)
    if task.delete_previous and previous_message_id:
        try:
            await client.delete_messages(send_target, [previous_message_id])
        except Exception as exc:
            logger.warning(
                "删除上一条消息失败 task={}, previous_message_id={}: {}",
                task.task_id, previous_message_id, exc,
            )
    message = await _send_task_content(
        client=client,
        task=task,
        send_target=send_target,
        send_text=send_text,
        formatting_entities=formatting_entities,
        media_ref_prefix=media_ref_prefix,
    )
    if message and task.pin_message:
        try:
            await client.pin_message(send_target, message.id, notify=False)
        except Exception as exc:
            logger.warning("置顶消息失败 task={}: {}", task.task_id, exc)
    return message.id if message else None


def _prepare_task_content(task: ScheduledMessageTask):
    text = task.text
    if text:
        text = get_rate_limiter().add_invisible_variation(text)
    send_text, formatting_entities = build_telegram_text_and_entities(text)
    validate_message_length(send_text, has_media=task.media_type != MediaType.NONE)
    if task.buttons:
        raise TaskMediaError(
            "TASK_BUTTONS_UNSUPPORTED_FOR_USER_ACCOUNT",
            "执行账号不是 Bot，任务消息不能携带按钮",
        )
    return send_text, formatting_entities


async def _send_task_content(
    *, client, task, send_target, send_text, formatting_entities, media_ref_prefix
):
    if task.media_type == MediaType.NONE:
        return await client.send_message(
            send_target,
            send_text,
            buttons=None,
            parse_mode=None,
            formatting_entities=formatting_entities,
        )
    send_media = await _resolve_send_media(
        client=client, task=task, media_ref_prefix=media_ref_prefix
    )
    if task.media_type in {MediaType.PHOTO, MediaType.VIDEO, MediaType.ANIMATION}:
        return await client.send_file(
            send_target,
            file=send_media,
            caption=send_text,
            buttons=None,
            parse_mode=None,
            formatting_entities=formatting_entities,
        )
    if task.media_type == MediaType.STICKER:
        return await client.send_file(send_target, file=send_media, buttons=None)
    raise ValueError(f"不支持的媒体类型: {task.media_type}")


async def _resolve_send_media(*, client, task, media_ref_prefix):
    if int(task.content_contract_version or 1) == 2:
        return await resolve_v2_task_media(client=client, task=task)
    if not task.media_file_id:
        raise ValueError("V1 媒体任务缺少 media_file_id")
    media = await resolve_task_media(
        client=client,
        media_file_id=task.media_file_id,
        account_id=task.account_id,
        media_ref_prefix=media_ref_prefix,
    )
    if isinstance(media, str) and os.path.isabs(media) and not os.path.exists(media):
        raise FileNotFoundError(f"媒体文件不存在: {media}")
    return media


async def send_with_protections(
    *,
    client,
    task: ScheduledMessageTask,
    send_target,
    lock_peer_id: int,
    account_id: str,
    previous_message_id: Optional[int],
    media_ref_prefix: str,
) -> Optional[int]:
    """Apply rate-limit and circuit-breaker before actual send."""
    rate_limiter = get_rate_limiter()
    circuit_breaker = get_circuit_breaker()

    await rate_limiter.wait_for_slot(account_id, lock_peer_id)

    if account_id == "default":
        return await do_send_message(
            client=client,
            task=task,
            send_target=send_target,
            previous_message_id=previous_message_id,
            media_ref_prefix=media_ref_prefix,
        )

    return await circuit_breaker.execute_with_circuit_breaker(
        account_id,
        do_send_message,
        client=client,
        task=task,
        send_target=send_target,
        previous_message_id=previous_message_id,
        media_ref_prefix=media_ref_prefix,
    )
