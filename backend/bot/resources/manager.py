"""Resource manager facade for dialogs synchronization and query APIs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from backend.bot.account.manager import get_account_manager
from backend.bot.resources.peer_utils import get_peer_type, get_title, has_resource_changed
from backend.bot.resources.query_ops import (
    get_input_peer as _get_input_peer,
    get_input_peer_by_resource_id as _get_input_peer_by_resource_id,
    get_resource as _get_resource,
    get_resources as _get_resources,
    search_resources as _search_resources,
)
from backend.bot.resources.sync_ops import (
    diagnose_client_unavailable as _diagnose_client_unavailable,
    full_sync as _full_sync,
    sync_peer as _sync_peer,
)


@dataclass
class SyncResult:
    """Resource synchronization result summary."""
    synced: int
    new: int
    updated: int
    deleted: int
    failed: int
    error: str = ""


class ResourceManager:
    """Dialogs resource manager."""

    def __init__(self):
        self._account_manager = get_account_manager()

    async def full_sync(self, account_id: str) -> SyncResult:
        """Full sync: scan dialogs and upsert resources."""
        return await _full_sync(self, account_id=account_id, result_factory=SyncResult)

    async def _diagnose_client_unavailable(self, account_id: str) -> str:
        """Backward-compatible wrapper."""
        return await _diagnose_client_unavailable(self._account_manager, account_id)

    async def _sync_peer(
        self,
        account_id: str,
        peer: Any,
        existing: Dict[int, Any],
        session=None,
    ) -> str:
        """Backward-compatible wrapper."""
        return await _sync_peer(
            account_id=account_id,
            peer=peer,
            existing=existing,
            session=session,
        )

    def _get_peer_type(self, peer: Any) -> Optional[str]:
        """Backward-compatible wrapper."""
        return get_peer_type(peer)

    def _get_title(self, peer: Any) -> str:
        """Backward-compatible wrapper."""
        return get_title(peer)

    def _has_resource_changed(self, resource, data: Dict[str, Any]) -> bool:
        """Backward-compatible wrapper."""
        return has_resource_changed(resource, data)

    async def incremental_sync(self, account_id: str) -> SyncResult:
        """Incremental sync (currently full-sync fallback)."""
        return await self.full_sync(account_id)

    async def get_resources(
        self,
        account_id: str,
        peer_type: Optional[str] = None,
        is_active: bool = True,
        limit: int = 1000,
    ):
        """Get resources by account and filters."""
        return await _get_resources(
            account_id=account_id,
            peer_type=peer_type,
            is_active=is_active,
            limit=limit,
        )

    async def search_resources(
        self,
        account_id: str,
        query: str,
        peer_type: Optional[str] = None,
        limit: int = 50,
    ):
        """Search resources by keyword."""
        return await _search_resources(
            account_id=account_id,
            query_text=query,
            peer_type=peer_type,
            limit=limit,
        )

    async def get_resource(self, account_id: str, peer_id: int):
        """Get one active resource by peer id."""
        return await _get_resource(account_id=account_id, peer_id=peer_id)

    async def get_input_peer(
        self,
        account_id: str,
        peer_id: int,
        peer_type: str,
        access_hash: Optional[int] = None,
    ):
        """Build InputPeer for one target."""
        return await _get_input_peer(
            account_id=account_id,
            peer_id=peer_id,
            peer_type=peer_type,
            access_hash=access_hash,
        )

    async def get_input_peer_by_resource_id(self, account_id: str, resource_id: int):
        """Build InputPeer by resource id."""
        return await _get_input_peer_by_resource_id(
            account_id=account_id,
            resource_id=resource_id,
        )


_resource_manager: Optional[ResourceManager] = None


def get_resource_manager() -> ResourceManager:
    """Get singleton resource manager instance."""
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = ResourceManager()
    return _resource_manager
