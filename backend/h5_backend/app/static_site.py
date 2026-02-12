"""SPA static mount helpers for H5 frontend."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

SPA_ROUTES = (
    "/",
    "/login",
    "/register",
    "/bind-tg",
    "/accounts",
    "/resources",
    "/proxies",
    "/tasks",
)

EXCLUDED_PREFIXES = ("api", "assets", "static", "docs", "redoc", "openapi.json")


def mount_spa(app: FastAPI, project_root: Path) -> None:
    """Mount built frontend assets and SPA route fallbacks."""
    frontend_dist = os.path.join(project_root, "frontend", "h5", "dist")
    frontend_index_file = os.path.join(frontend_dist, "index.html")

    if not os.path.exists(frontend_index_file):
        print(f"⚠ 前端构建产物不存在: {frontend_dist}")
        print("  提示: 运行 'cd frontend/h5 && npm run build' 构建前端")
        return

    static_dist = os.path.join(frontend_dist, "assets")
    if os.path.exists(static_dist):
        app.mount("/assets", StaticFiles(directory=static_dist), name="frontend-assets")

    def serve_frontend_index() -> FileResponse:
        return FileResponse(frontend_index_file)

    for route in SPA_ROUTES:
        app.add_api_route(
            route,
            endpoint=serve_frontend_index,
            methods=["GET"],
            include_in_schema=False,
        )

    async def serve_frontend_spa_fallback(full_path: str):
        for prefix in EXCLUDED_PREFIXES:
            if full_path == prefix or full_path.startswith(f"{prefix}/"):
                raise HTTPException(status_code=404, detail="Not Found")
        return serve_frontend_index()

    app.add_api_route(
        "/{full_path:path}",
        endpoint=serve_frontend_spa_fallback,
        methods=["GET"],
        include_in_schema=False,
    )

    print(f"✓ 前端静态文件已挂载: {frontend_dist}")
