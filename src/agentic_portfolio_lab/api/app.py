"""FastAPI application factory for the read-first integrated MVP."""

from __future__ import annotations

from fastapi import FastAPI

from agentic_portfolio_lab.dashboard_demo import build_demo_dashboard_data

from .queries import MvpQueryService, MvpReadState, MvpReadStateSnapshot
from .routes import create_router


def create_app(*, state: MvpReadState | None = None) -> FastAPI:
    """Create the HTTP adapter with explicit, replaceable application state."""
    source = MvpReadStateSnapshot.from_dashboard_demo(build_demo_dashboard_data()) if state is None else state
    app = FastAPI(title="Agentic Portfolio Lab", version="1.0.0")
    app.include_router(create_router(MvpQueryService(source)))
    return app


app = create_app()
