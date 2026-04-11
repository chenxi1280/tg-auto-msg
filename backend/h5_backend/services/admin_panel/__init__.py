"""Admin panel / agent domain service package."""

__all__ = ["AdminPanelService", "get_admin_panel_service"]


def __getattr__(name: str):
    if name in {"AdminPanelService", "get_admin_panel_service"}:
        from backend.h5_backend.services.admin_panel.service import AdminPanelService, get_admin_panel_service

        return {"AdminPanelService": AdminPanelService, "get_admin_panel_service": get_admin_panel_service}[name]
    raise AttributeError(name)
