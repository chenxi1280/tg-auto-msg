"""Peer normalization helpers for resource synchronization."""
from __future__ import annotations

from typing import Any, Optional

from telethon.tl import types as tl_types
from telethon.tl.types import Channel, Chat, User

from backend.database.models import PeerType, Resource

EMPTY_PEER_TYPES = tuple(
    t
    for t in (
        getattr(tl_types, "UserEmpty", None),
        getattr(tl_types, "ChatEmpty", None),
        getattr(tl_types, "ChannelEmpty", None),
    )
    if t is not None
)


def get_peer_type(peer: Any) -> Optional[str]:
    """Detect peer type from Telethon entity."""
    if isinstance(peer, User):
        return PeerType.USER
    if isinstance(peer, Chat):
        return PeerType.CHAT
    if isinstance(peer, Channel):
        if peer.broadcast:
            return PeerType.CHANNEL
        return PeerType.SUPERGROUP
    return None


def get_title(peer: Any) -> str:
    """Render peer title with deterministic fallback."""
    if hasattr(peer, "title") and peer.title:
        return str(peer.title).strip()

    if hasattr(peer, "first_name"):
        first_name = str(peer.first_name or "").strip()
        last_name = str(getattr(peer, "last_name", "") or "").strip()
        full_name = f"{first_name} {last_name}".strip()
        if full_name:
            return full_name

    username = str(getattr(peer, "username", "") or "").strip()
    if username:
        return f"@{username}"

    peer_id = getattr(peer, "id", None)
    peer_type = get_peer_type(peer)
    if peer_type == PeerType.USER:
        return f"用户 {peer_id}"
    if peer_type in (PeerType.CHAT, PeerType.SUPERGROUP):
        return f"群组 {peer_id}"
    if peer_type == PeerType.CHANNEL:
        return f"频道 {peer_id}"
    return f"会话 {peer_id}"


def has_resource_changed(resource: Resource, data: dict[str, Any]) -> bool:
    """Check whether persisted resource fields changed."""
    return (
        resource.title != data.get("title")
        or resource.username != data.get("username")
        or resource.description != data.get("description")
        or resource.is_verified != data.get("is_verified")
        or resource.is_scam != data.get("is_scam")
    )
