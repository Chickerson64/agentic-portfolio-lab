"""Read-only FastAPI application adapter for the integrated MVP."""

from .app import app, create_app

__all__ = ["app", "create_app"]
