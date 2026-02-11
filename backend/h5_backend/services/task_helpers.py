"""Task payload normalization and media helper functions."""
from typing import Any, Dict, List, Optional
import random

from fastapi import HTTPException, UploadFile

from backend.database.models import Account, MediaType

MAX_TASK_MEDIA_SIZE = 20 * 1024 * 1024  # 20MB
TELEGRAM_MEDIA_REF_PREFIX = "tgmsg://"


def media_value(value: object) -> str:
    """Normalize enum/string media type output to lowercase value."""
    if isinstance(value, MediaType):
        return value.value
    return str(value or MediaType.NONE.value).lower()


def normalize_media_type(raw_value: object) -> MediaType:
    """Normalize media_type input."""
    if isinstance(raw_value, MediaType):
        return raw_value
    media_type = str(raw_value or MediaType.NONE.value).strip().lower()
    if media_type == "gif":
        media_type = MediaType.ANIMATION.value
    try:
        return MediaType(media_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"不支持的 media_type: {raw_value}") from exc


def normalize_target_peers(raw_value: Any) -> List[Dict[str, Any]]:
    """
    Normalize target_peers list.

    Item format:
    {
      "peer_id": int,
      "peer_type": "user|chat|supergroup|channel",
      "access_hash": int | None
    }
    """
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise HTTPException(status_code=400, detail="target_peers 必须是数组")

    normalized: List[Dict[str, Any]] = []
    allowed_types = {"user", "chat", "supergroup", "channel"}

    for idx, item in enumerate(raw_value):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"target_peers[{idx}] 必须是对象")

        raw_peer_id = item.get("peer_id", item.get("target_peer_id"))
        raw_peer_type = item.get("peer_type", item.get("target_peer_type"))
        raw_access_hash = item.get("access_hash", item.get("target_access_hash"))

        try:
            peer_id = int(raw_peer_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"target_peers[{idx}].peer_id 非法") from exc

        peer_type = str(raw_peer_type or "").strip().lower()
        if peer_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"target_peers[{idx}].peer_type 非法，必须为 user/chat/supergroup/channel",
            )

        access_hash: Optional[int] = None
        if raw_access_hash not in (None, ""):
            try:
                access_hash = int(raw_access_hash)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"target_peers[{idx}].access_hash 非法") from exc

        normalized.append(
            {
                "peer_id": peer_id,
                "peer_type": peer_type,
                "access_hash": access_hash,
            }
        )

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for peer in normalized:
        key = (peer["peer_type"], peer["peer_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(peer)

    return deduped


def build_auto_delay_profile(priority: int, account: Optional[Account]) -> tuple[int, int, int]:
    """
    System-generated random delay profile (user does not control directly).

    Returns:
    - delay_min_seconds
    - delay_max_seconds
    - jitter_seconds
    """
    weight = int(getattr(account, "weight", 100) or 100)

    if priority >= 100:
        min_range = (0, 5)
        max_range = (8, 20)
    elif weight < 50:
        min_range = (60, 120)
        max_range = (180, 300)
    elif weight < 100:
        min_range = (30, 60)
        max_range = (120, 240)
    else:
        min_range = (10, 30)
        max_range = (60, 180)

    delay_min = random.randint(*min_range)
    delay_max_low = max(delay_min + 1, max_range[0])
    delay_max = random.randint(delay_max_low, max_range[1])
    jitter_seconds = random.randint(0, min(delay_max, 300))
    return delay_min, delay_max, jitter_seconds


def resolve_upload_media_type(upload: UploadFile) -> MediaType:
    """Resolve media type from upload file metadata."""
    content_type = (upload.content_type or "").lower()
    filename = (upload.filename or "").lower()

    if content_type.startswith("image/"):
        if content_type == "image/gif" or filename.endswith(".gif"):
            return MediaType.ANIMATION
        return MediaType.PHOTO
    if content_type.startswith("video/"):
        return MediaType.VIDEO
    if filename.endswith(".gif"):
        return MediaType.ANIMATION
    raise HTTPException(status_code=400, detail="仅支持图片/GIF/视频文件上传")


def build_telegram_media_ref(account_id: str, message_id: int) -> str:
    """Build Telegram media ref string: tgmsg://{account_id}/{message_id}."""
    return f"{TELEGRAM_MEDIA_REF_PREFIX}{account_id}/{message_id}"
