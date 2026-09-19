"""FastAPI application factory for the v0.1 operator adapter."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentic_portfolio_lab.dashboard_demo import build_demo_dashboard_data
from agentic_portfolio_lab.application.market_configuration import LIVE_PRICE_CANDIDATE_UNIVERSE, SPY_BENCHMARK, VALUE_US_EQUITIES_V1
from agentic_portfolio_lab.application.refresh_prices import InMemoryPriceRefreshState, RefreshPricesService
from agentic_portfolio_lab.application.build_research import BuildResearchService
from agentic_portfolio_lab.application.bootstrap_overview import BootstrapOverviewService
from agentic_portfolio_lab.infrastructure.alpha_vantage import AlphaVantageResearchProvider
from agentic_portfolio_lab.application.wave2_commands import BenchmarkFulfillmentService, CashEventService
from agentic_portfolio_lab.application.decision_commands import DecisionApprovalService, ReviewDecisionService, RunValueManagerService, ReviseDecisionCycleService
from agentic_portfolio_lab.domain.openai_reviewer import OpenAIReviewer
from agentic_portfolio_lab.domain.reviewer import AIReviewer
from agentic_portfolio_lab.domain.openai_value_manager import OpenAIValueManager
from agentic_portfolio_lab.domain.value_manager import ValueManager
from agentic_portfolio_lab.application.managed_execution import ManagedPaperExecutionService
from agentic_portfolio_lab.application.v2_weekly_cycle import V2WeeklyCycleService
from agentic_portfolio_lab.application.v2_preparation import V2WeeklyPreparationService
from agentic_portfolio_lab.application.screen_universe_v2 import ScreenUniverseV2Service
from agentic_portfolio_lab.application.refresh_universe import RefreshUniverseService
from agentic_portfolio_lab.application.build_research_v3 import BuildResearchV3Service
from agentic_portfolio_lab.application.v2_advisory import V2ManagerRiskService
from agentic_portfolio_lab.application.v2_prices import MarketDataV2PriceSnapshotProvider
from agentic_portfolio_lab.application.active_policy import load_active_value_policy
from agentic_portfolio_lab.domain.screening_v2 import ScreeningProfileIdentity
from agentic_portfolio_lab.domain.openai_v2_reviewer import OpenAIV2Reviewer
from agentic_portfolio_lab.infrastructure.alpaca import AlpacaClient
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore, SQLiteMvpReadState, SQLiteOverviewBootstrapState, SQLitePriceRefreshState, SQLiteResearchBatchState
from agentic_portfolio_lab.infrastructure.twelve_data import TwelveDataMarketPriceProvider
from agentic_portfolio_lab.infrastructure.v3_batch_store import SQLiteResearchV3Store

from .queries import MvpReadState, MvpReadStateSnapshot
from .routes import create_router


def create_app(
    *,
    state: MvpReadState | None = None,
    database_path: str | None = None,
    refresh_service: RefreshPricesService | None = None,
    research_service: BuildResearchService | None = None,
    bootstrap_overview_service: BootstrapOverviewService | None = None,
    cash_event_service: CashEventService | None = None,
    benchmark_fulfillment_service: BenchmarkFulfillmentService | None = None,
    value_manager: ValueManager | None = None,
    run_value_manager_service: RunValueManagerService | None = None,
    reviewer: AIReviewer | None = None,
    review_decision_service: ReviewDecisionService | None = None,
    decision_approval_service: DecisionApprovalService | None = None,
    managed_execution_service: ManagedPaperExecutionService | None = None,
    v2_preparation_service: V2WeeklyPreparationService | None = None,
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
    overview_bootstrap = bootstrap_overview_service or BootstrapOverviewService(
        provider=AlphaVantageResearchProvider(),
        state=SQLiteOverviewBootstrapState(store) if store is not None else _UnavailableOverviewState(),
        universe=VALUE_US_EQUITIES_V1,
    )
    v2_cycle = V2WeeklyCycleService(store, now=lambda: datetime.now(timezone.utc)) if store is not None else None
    v2_readiness_reason = "DURABLE_STATE_UNAVAILABLE" if store is None else None
    if v2_preparation_service is None and store is not None:
        selector = tuple(os.environ.get(name, "").strip() for name in ("V2_SCREENING_MANAGER_ID", "V2_SCREENING_PROFILE_NAME", "V2_SCREENING_PROFILE_VERSION"))
        credentials = all(os.environ.get(name, "").strip() for name in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "ALPHA_VANTAGE_API_KEY", "OPENAI_API_KEY"))
        if not all(selector): v2_readiness_reason = "SCREENING_PROFILE_UNCONFIGURED"
        elif store.load_screening_profile(ScreeningProfileIdentity(*selector)) is None: v2_readiness_reason = "SCREENING_PROFILE_NOT_FOUND"
        elif not credentials: v2_readiness_reason = "PROVIDER_UNCONFIGURED"
        else:
            profile = ScreeningProfileIdentity(*selector)
            market = AlpacaClient()
            v3_store = SQLiteResearchV3Store(configured_path)
            budget = int(os.environ.get("V3_DAILY_DEEP_RESEARCH_SUBJECT_BUDGET", "8"))
            v2_preparation_service = V2WeeklyPreparationService(v2_cycle, RefreshUniverseService(provider=market, state=store), ScreenUniverseV2Service(store, market), BuildResearchV3Service(provider=AlphaVantageResearchProvider(), store=v3_store, max_deep_research_subjects=budget), OpenAIValueManager(), MarketDataV2PriceSnapshotProvider(market), V2ManagerRiskService(load_active_value_policy().manager_risk_constitution), OpenAIV2Reviewer(), profile, lambda: datetime.now(timezone.utc))
    app.include_router(
        create_router(
            source,
            refresh_service=service,
            research_service=research,
            bootstrap_overview_service=overview_bootstrap,
            cash_event_service=cash_event_service or (CashEventService(store) if store is not None else None),
            benchmark_fulfillment_service=benchmark_fulfillment_service
            or (BenchmarkFulfillmentService(store) if store is not None else None),
            run_value_manager_service=run_value_manager_service
            or (RunValueManagerService(store, manager=value_manager or OpenAIValueManager()) if store is not None else None),
            review_decision_service=review_decision_service
            or (ReviewDecisionService(store, reviewer=reviewer or OpenAIReviewer()) if store is not None else None),
            decision_approval_service=decision_approval_service
            or (DecisionApprovalService(store) if store is not None else None),
            managed_execution_service=managed_execution_service
            or (ManagedPaperExecutionService(store) if store is not None else None),
            revision_service=ReviseDecisionCycleService(store) if store is not None else None,
            v2_cycle_service=v2_cycle,
            v2_preparation_service=v2_preparation_service,
            v2_readiness_reason=v2_readiness_reason,
        )
    )
    return app


class _UnavailableResearchState:
    def load_research_inputs(self):
        raise ValueError("research persistence requires AGENTIC_PORTFOLIO_LAB_DB_PATH")

    def persist_research_cycle(self, *, screening_run, fetched_records, batch) -> None:
        raise ValueError("research persistence requires AGENTIC_PORTFOLIO_LAB_DB_PATH")


class _UnavailableOverviewState:
    def load_fundamental_records(self):
        raise ValueError("overview bootstrap requires AGENTIC_PORTFOLIO_LAB_DB_PATH")

    def persist_overview_record(self, record) -> None:
        raise ValueError("overview bootstrap requires AGENTIC_PORTFOLIO_LAB_DB_PATH")


app = create_app()
