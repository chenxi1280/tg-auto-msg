"""H5 backend service layer."""

from backend.h5_backend.services.account.service import AccountService, get_account_service
from backend.h5_backend.services.auth.service import AuthService, get_auth_service
from backend.h5_backend.services.login.service import LoginService, get_login_service
from backend.h5_backend.services.proxy.service import ProxyService, get_proxy_service
from backend.h5_backend.services.task.service import TaskService, get_task_service

__all__ = [
    "AccountService",
    "AuthService",
    "LoginService",
    "ProxyService",
    "TaskService",
    "get_account_service",
    "get_auth_service",
    "get_login_service",
    "get_proxy_service",
    "get_task_service",
]
