"""H5 backend service layer."""

__all__ = [
    "AccountService",
    "AdminLicenseService",
    "AuthService",
    "LoginService",
    "MeService",
    "ProxyService",
    "TaskService",
    "get_account_service",
    "get_admin_license_service",
    "get_auth_service",
    "get_login_service",
    "get_me_service",
    "get_proxy_service",
    "get_task_service",
]


def __getattr__(name: str):
    if name in {"AccountService", "get_account_service"}:
        from backend.h5_backend.services.account.service import AccountService, get_account_service

        return {"AccountService": AccountService, "get_account_service": get_account_service}[name]
    if name in {"AdminLicenseService", "get_admin_license_service"}:
        from backend.h5_backend.services.admin.service import AdminLicenseService, get_admin_license_service

        return {"AdminLicenseService": AdminLicenseService, "get_admin_license_service": get_admin_license_service}[name]
    if name in {"AuthService", "get_auth_service"}:
        from backend.h5_backend.services.auth.service import AuthService, get_auth_service

        return {"AuthService": AuthService, "get_auth_service": get_auth_service}[name]
    if name in {"LoginService", "get_login_service"}:
        from backend.h5_backend.services.login.service import LoginService, get_login_service

        return {"LoginService": LoginService, "get_login_service": get_login_service}[name]
    if name in {"MeService", "get_me_service"}:
        from backend.h5_backend.services.me.service import MeService, get_me_service

        return {"MeService": MeService, "get_me_service": get_me_service}[name]
    if name in {"ProxyService", "get_proxy_service"}:
        from backend.h5_backend.services.proxy.service import ProxyService, get_proxy_service

        return {"ProxyService": ProxyService, "get_proxy_service": get_proxy_service}[name]
    if name in {"TaskService", "get_task_service"}:
        from backend.h5_backend.services.task.service import TaskService, get_task_service

        return {"TaskService": TaskService, "get_task_service": get_task_service}[name]
    raise AttributeError(name)
