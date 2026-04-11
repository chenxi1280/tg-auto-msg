"""H5 backend app assembly package."""

__all__ = ["app", "create_app", "app_lifespan"]


def __getattr__(name: str):
    if name in {"app", "create_app"}:
        from backend.h5_backend.app.factory import app, create_app

        return {"app": app, "create_app": create_app}[name]
    if name == "app_lifespan":
        from backend.h5_backend.app.lifespan import app_lifespan

        return app_lifespan
    raise AttributeError(name)
