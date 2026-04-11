"""H5 backend package."""

__all__ = ["app", "create_app"]


def __getattr__(name: str):
    if name in {"app", "create_app"}:
        from backend.h5_backend.app.factory import app, create_app

        return {"app": app, "create_app": create_app}[name]
    raise AttributeError(name)
