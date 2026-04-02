"""FastAPI app factory for H5 backend."""

import os
from pathlib import Path

from fastapi import FastAPI

from backend.h5_backend.app.lifespan import app_lifespan
from backend.h5_backend.app.static_site import mount_spa
from backend.h5_backend.routers.accounts import router as accounts_router
from backend.h5_backend.routers.admin_licenses import router as admin_licenses_router
from backend.h5_backend.routers.auth import router as auth_router
from backend.h5_backend.routers.login import router as login_router
from backend.h5_backend.routers.me import router as me_router
from backend.h5_backend.routers.proxies import router as proxies_router
from backend.h5_backend.routers.tasks import router as tasks_router

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def create_app() -> FastAPI:
    """Create and configure FastAPI app."""
    app = FastAPI(title="全球通管理 API", lifespan=app_lifespan)

    app.include_router(auth_router)
    app.include_router(login_router)
    app.include_router(accounts_router)
    app.include_router(admin_licenses_router)
    app.include_router(tasks_router)
    app.include_router(proxies_router)
    app.include_router(me_router)

    if os.getenv("SERVE_FRONTEND", "true").lower() in {"1", "true", "yes", "on"}:
        mount_spa(app, PROJECT_ROOT)
    return app


app = create_app()
