"""FastAPI application factory for the v0.1 operator adapter."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentic_portfolio_lab.dashboard_demo import build_demo_dashboard_data
from agentic_portfolio_lab.application.market_configuration import LIVE_PRICE_CANDIDATE_UNIVERSE, SPY_BENCHMARK, VALUE_US_EQUITIES_V1
from agentic_portfolio_lab.application.refresh_prices import InMemoryPriceRefreshState, RefreshPricesService
from agentic_portfolio_lab.application.build_research import BuildResearchService
from agentic_portfolio_lab.infrastructure.alpha_vantage import AlphaVantageResearchProvider
from agentic_portfolio_lab.application.wave2_commands import BenchmarkFulfillmentService, CashEventService
from agentic_portfolio_lab.application.decision_commands import DecisionApprovalService, RunValueManagerService
from agentic_portfolio_lab.domain.openai_value_manager import OpenAIValueManager
from agentic_portfolio_lab.domain.value_manager import ValueManager
from agentic_portfolio_lab.application.managed_execution import ManagedPaperExecutionService
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore, SQLiteMvpReadState, SQLitePriceRefreshState, SQLiteResearchBatchState
from agentic_portfolio_lab.infrastructure.twelve_data import TwelveDataMarketPriceProvider

from .queries import MvpReadState, MvpReadStateSnapshot
from .routes import create_router


def create_app(
    *,
    state: MvpReadState | None = None,
    database_path: str | None = None,
    refresh_service: RefreshPricesService | None = None,
    research_service: BuildResearchService | None = None,
    cash_event_service: CashEventService | None = None,
    benchmark_fulfillment_service: BenchmarkFulfillmentService | None = None,
    value_manager: ValueManager | None = None,
    run_value_manager_service: RunValueManagerService | None = None,
    decision_approval_service: DecisionApprovalService | None = None,
    managed_execution_service: ManagedPaperExecutionService | None = None,
) -> FastAPI:
    """Create the HTTP adapter with explicit, replaceable application state."""
    if state is not None and database_path is not None:
        raise ValueError("state and database_path are mutually exclusive")
    configured_path = database_path if database_path is not None else os.environ.get("AGENTIC_PORTFOLIO_LAB_DB_PATH")
    store: SQLiteLocalRunStore | None = None
    if state is not None:
        source = state
    elif configured_path:
        store = SQLiteLocalRunStore(configured_path)
        source = SQLiteMvpReadState(store)
    else:
        source = MvpReadStateSnapshot.from_dashboard_demo(build_demo_dashboard_data())
    app = FastAPI(title="Agentic Portfolio Lab", version="0.1.0")
    # The static Phase 2 frontend is served locally on port 8001. Production
    # origins are intentionally not configured by this development adapter.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8001", "http://127.0.0.1:8001"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=[],
    )
    service = refresh_service or RefreshPricesService(
        provider=TwelveDataMarketPriceProvider(),
        state=SQLitePriceRefreshState(store) if store is not None else InMemoryPriceRefreshState(),
        candidate_universe=LIVE_PRICE_CANDIDATE_UNIVERSE,
        spy_benchmark=SPY_BENCHMARK,
    )
    research = research_service or BuildResearchService(
        provider=AlphaVantageResearchProvider(),
        state=SQLiteResearchBatchState(store) if store is not None else _UnavailableResearchState(),
        universe=VALUE_US_EQUITIES_V1,
    )
    app.include_router(
        create_router(
            source,
            refresh_service=service,
            research_service=research,
            cash_event_service=cash_event_service or (CashEventService(store) if store is not None else None),
            benchmark_fulfillment_service=benchmark_fulfillment_service
            or (BenchmarkFulfillmentService(store) if store is not None else None),
            run_value_manager_service=run_value_manager_service
            or (RunValueManagerService(store, manager=value_manager or OpenAIValueManager()) if store is not None else None),
            decision_approval_service=decision_approval_service
            or (DecisionApprovalService(store) if store is not None else None),
            managed_execution_service=managed_execution_service
            or (ManagedPaperExecutionService(store) if store is not None else None),
        )
    )
    return app


class _UnavailableResearchState:
    def load_research_inputs(self):
        raise ValueError("research persistence requires AGENTIC_PORTFOLIO_LAB_DB_PATH")

    def persist_research_cycle(self, *, screening_run, fetched_records, batch) -> None:
        raise ValueError("research persistence requires AGENTIC_PORTFOLIO_LAB_DB_PATH")


app = create_app()
