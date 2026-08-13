"""Thin read-only HTTP routes for the MVP application adapter."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agentic_portfolio_lab.application.refresh_prices import RefreshPricesService
from agentic_portfolio_lab.domain.market_prices import MarketPriceConfigurationError, MarketPriceError

from .models import (
    BenchmarkSnapshotResponse,
    DashboardResponse,
    DecisionMemoResponse,
    HealthResponse,
    HistoryResponse,
    PerformanceResponse,
    PortfolioSnapshotResponse,
    ResearchBatchResponse,
    PriceRefreshResponse,
)
from .queries import LatestResourceNotFound, MvpQueryService, MvpReadState


def _query_or_unavailable(query):
    try:
        return query()
    except LatestResourceNotFound as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "latest_resource_not_found", "message": str(error)},
        ) from error
    except (IndexError, ValueError) as error:
        raise HTTPException(status_code=503, detail=f"application state unavailable: {error}") from error


def create_router(state: MvpReadState, *, refresh_service: RefreshPricesService) -> APIRouter:
    router = APIRouter()

    def service() -> MvpQueryService:
        # A durable state source is loaded once for each HTTP query, avoiding a
        # stale startup snapshot while keeping each response internally coherent.
        return MvpQueryService(state)

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return service().health()

    @router.post("/commands/refresh-prices", response_model=PriceRefreshResponse)
    def refresh_prices() -> PriceRefreshResponse:
        try:
            result = refresh_service.refresh(service.held_securities())
        except MarketPriceConfigurationError as error:
            raise HTTPException(status_code=503, detail={"code": "market_price_configuration", "message": str(error)}) from error
        except MarketPriceError as error:
            raise HTTPException(status_code=502, detail={"code": "market_price_unavailable", "message": str(error)}) from error
        except (IndexError, ValueError) as error:
            raise HTTPException(status_code=503, detail={"code": "refresh_unavailable", "message": str(error)}) from error
        return PriceRefreshResponse(
            refreshed_tickers=tuple(observation.security.ticker for observation in result.observations),
            provider_identity=result.provider_identity,
            latest_source_timestamp=result.latest_source_timestamp.isoformat(),
            price_convention=result.observations[0].price_convention,
        )

    @router.get("/portfolio", response_model=PortfolioSnapshotResponse)
    def portfolio() -> PortfolioSnapshotResponse:
        return _query_or_unavailable(service().portfolio)

    @router.get("/benchmark", response_model=BenchmarkSnapshotResponse)
    def benchmark() -> BenchmarkSnapshotResponse:
        return _query_or_unavailable(service().benchmark)

    @router.get("/performance", response_model=PerformanceResponse)
    def performance() -> PerformanceResponse:
        return _query_or_unavailable(service().performance)

    @router.get("/decisions/latest", response_model=DecisionMemoResponse)
    def latest_decision() -> DecisionMemoResponse:
        return _query_or_unavailable(service().latest_decision)

    @router.get("/decisions", response_model=HistoryResponse)
    def decisions() -> HistoryResponse:
        return _query_or_unavailable(service().decisions)

    @router.get("/research/latest", response_model=ResearchBatchResponse)
    def research_latest() -> ResearchBatchResponse:
        return _query_or_unavailable(service().research_latest)

    @router.get("/dashboard", response_model=DashboardResponse)
    def dashboard() -> DashboardResponse:
        return _query_or_unavailable(service().dashboard)

    return router
