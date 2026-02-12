"""H5 backend app assembly package."""

from backend.h5_backend.app.factory import app, create_app
from backend.h5_backend.app.lifespan import app_lifespan

__all__ = ["app", "create_app", "app_lifespan"]
