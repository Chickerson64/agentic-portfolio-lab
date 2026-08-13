"""FastAPI application factory for the read-first integrated MVP."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentic_portfolio_lab.dashboard_demo import build_demo_dashboard_data

from .queries import MvpQueryService, MvpReadState, MvpReadStateSnapshot
from .routes import create_router


def create_app(*, state: MvpReadState | None = None) -> FastAPI:
    """Create the HTTP adapter with explicit, replaceable application state."""
    source = MvpReadStateSnapshot.from_dashboard_demo(build_demo_dashboard_data()) if state is None else state
    app = FastAPI(title="Agentic Portfolio Lab", version="1.0.0")
    # The static Phase 2 frontend is served locally on port 8001. Production
    # origins are intentionally not configured by this development adapter.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8001", "http://127.0.0.1:8001"],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=[],
    )
    app.include_router(create_router(MvpQueryService(source)))
    return app


app = create_app()
