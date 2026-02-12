"""Resources domain package."""

from backend.bot.resources.manager import ResourceManager, SyncResult, get_resource_manager

__all__ = ["SyncResult", "ResourceManager", "get_resource_manager"]
