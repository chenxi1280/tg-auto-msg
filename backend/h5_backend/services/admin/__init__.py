"""Admin license service package."""

__all__ = ["AdminLicenseService", "get_admin_license_service"]


def __getattr__(name: str):
    if name in {"AdminLicenseService", "get_admin_license_service"}:
        from backend.h5_backend.services.admin.service import AdminLicenseService, get_admin_license_service

        return {"AdminLicenseService": AdminLicenseService, "get_admin_license_service": get_admin_license_service}[name]
    raise AttributeError(name)
