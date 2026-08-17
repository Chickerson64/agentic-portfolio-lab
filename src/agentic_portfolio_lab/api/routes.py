"""Thin HTTP adapter over deterministic application commands and queries."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from agentic_portfolio_lab.application.refresh_prices import RefreshPricesService
from agentic_portfolio_lab.application.build_research import BuildResearchService
from agentic_portfolio_lab.application.bootstrap_overview import BootstrapOverviewService
from agentic_portfolio_lab.application.wave2_commands import BenchmarkFulfillmentService, CashEventService
from agentic_portfolio_lab.application.decision_commands import DecisionApprovalService, DecisionCommandConflict, RunValueManagerService
from agentic_portfolio_lab.domain.approval import ApprovalDecision
from agentic_portfolio_lab.application.managed_execution import ManagedPaperExecutionError, ManagedPaperExecutionService
from agentic_portfolio_lab.domain.market_prices import MarketPriceConfigurationError, MarketPriceError
from agentic_portfolio_lab.domain.research_provider import ResearchProviderConfigurationError, ResearchProviderError

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
    BuildResearchResponse,
    BootstrapOverviewResponse,
    CashEventCommand,
    CashEventResponse,
    BenchmarkFulfillmentResponse,
    DecisionApprovalCommand,
    RunValueManagerCommand,
    decision_memo_response,
    ExecutePaperTradeResponse,
    security_response,
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


def create_router(
    state: MvpReadState,
    *,
    refresh_service: RefreshPricesService,
    research_service: BuildResearchService,
    bootstrap_overview_service: BootstrapOverviewService,
    cash_event_service: CashEventService | None = None,
    benchmark_fulfillment_service: BenchmarkFulfillmentService | None = None,
    run_value_manager_service: RunValueManagerService | None = None,
    decision_approval_service: DecisionApprovalService | None = None,
    managed_execution_service: ManagedPaperExecutionService | None = None,
) -> APIRouter:
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
            result = refresh_service.refresh(service().held_securities())
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

    @router.post("/commands/build-research", response_model=BuildResearchResponse)
    def build_research() -> BuildResearchResponse:
        try:
            result = research_service.build(portfolio_id=service().managed_portfolio_id())
        except ResearchProviderConfigurationError as error:
            raise HTTPException(status_code=503, detail={"code": "research_provider_configuration", "message": str(error)}) from error
        except ResearchProviderError as error:
            raise HTTPException(status_code=502, detail={"code": "research_provider_unavailable", "message": str(error)}) from error
        except (IndexError, ValueError) as error:
            raise HTTPException(status_code=503, detail={"code": "research_unavailable", "message": str(error)}) from error
        return BuildResearchResponse(batch_id=result.batch.batch_id, decision_cycle_id=str(result.batch.decision_cycle_id), packet_count=len(result.batch.packets), source_provider_identity=result.provider_identity, as_of_timestamp=result.batch.as_of_timestamp.isoformat())

    @router.post("/commands/bootstrap-overview", response_model=BootstrapOverviewResponse)
    def bootstrap_overview() -> BootstrapOverviewResponse:
        try:
            result = bootstrap_overview_service.bootstrap()
        except ResearchProviderConfigurationError as error:
            raise HTTPException(status_code=503, detail={"code": "research_provider_configuration", "message": str(error)}) from error
        except ResearchProviderError as error:
            raise HTTPException(status_code=502, detail={"code": "research_provider_unavailable", "message": str(error)}) from error
        except (IndexError, ValueError) as error:
            raise HTTPException(status_code=503, detail={"code": "overview_bootstrap_unavailable", "message": str(error)}) from error
        return BootstrapOverviewResponse(
            fetched=tuple(security_response(security) for security in result.fetched),
            skipped=tuple(security_response(security) for security in result.skipped),
            remaining=tuple(security_response(security) for security in result.remaining),
            request_count=result.request_count,
            provider_identity=result.provider_identity,
        )

    @router.post("/commands/cash-events", response_model=CashEventResponse)
    def cash_event(command: CashEventCommand) -> CashEventResponse:
        if cash_event_service is None:
            raise HTTPException(status_code=503, detail={"code": "durable_state_required", "message": "cash events require configured local SQLite state"})
        try:
            result = cash_event_service.apply(amount=command.amount, currency=command.currency, source=command.source, effective_at=command.effective_at)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail={"code": "cash_event_invalid", "message": str(error)}) from error
        event = result.cash_event
        return CashEventResponse(
            event_id=str(event.event_id),
            managed_cash=format(result.funded_managed_portfolio.cash_balance.amount, "f"),
            benchmark_cash=format(result.funded_benchmark_portfolio.portfolio.cash_balance.amount, "f"),
            currency=event.currency,
            effective_at=event.effective_at.isoformat(),
        )

    @router.post("/commands/fulfill-benchmark", response_model=BenchmarkFulfillmentResponse)
    def fulfill_benchmark(fulfilled_at: datetime) -> BenchmarkFulfillmentResponse:
        if benchmark_fulfillment_service is None:
            raise HTTPException(status_code=503, detail={"code": "durable_state_required", "message": "benchmark fulfillment requires configured local SQLite state"})
        try:
            result = benchmark_fulfillment_service.fulfill(fulfilled_at=fulfilled_at)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail={"code": "benchmark_fulfillment_invalid", "message": str(error)}) from error
        fulfillment = result.fulfillment
        if fulfillment is None:
            return BenchmarkFulfillmentResponse(status=result.status.value, fulfillment_id=None, quantity=None, notional=None, provider_identity=None, observed_at=None, market_date=None, price_convention=None)
        return BenchmarkFulfillmentResponse(status=result.status.value, fulfillment_id=str(fulfillment.fulfillment_id), quantity=format(fulfillment.quantity, "f"), notional=format(fulfillment.notional, "f"), provider_identity=fulfillment.provider_identity, observed_at=fulfillment.price_observation.observed_at.isoformat(), market_date=fulfillment.price_observation.market_date.isoformat(), price_convention=fulfillment.price_observation.price_convention)

    @router.post("/commands/run-value-manager", response_model=DecisionMemoResponse)
    def run_value_manager(command: RunValueManagerCommand) -> DecisionMemoResponse:
        if run_value_manager_service is None:
            raise HTTPException(status_code=503, detail={"code": "durable_state_required", "message": "Value Manager runs require configured local SQLite state"})
        try:
            result = run_value_manager_service.run(occurred_at=command.occurred_at)
        except DecisionCommandConflict as error:
            raise HTTPException(status_code=409, detail={"code": "decision_conflict", "message": str(error)}) from error
        except RuntimeError as error:
            raise HTTPException(status_code=502, detail={"code": "value_manager_unavailable", "message": str(error)}) from error
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail={"code": "value_manager_invalid", "message": str(error)}) from error
        return decision_memo_response(result.journal_entry, None, None)

    def _record_human_decision(
        decision_cycle_id: str,
        command: DecisionApprovalCommand,
        outcome: ApprovalDecision,
    ) -> DecisionMemoResponse:
        if decision_approval_service is None:
            raise HTTPException(status_code=503, detail={"code": "durable_state_required", "message": "decision outcomes require configured local SQLite state"})
        try:
            from uuid import UUID
            approval = decision_approval_service.decide(
                decision_cycle_id=UUID(decision_cycle_id),
                decision=outcome,
                decision_maker_id=command.decision_maker_id,
                decided_at=command.decided_at,
                comment=command.comment,
            )
        except DecisionCommandConflict as error:
            raise HTTPException(status_code=409, detail={"code": "decision_conflict", "message": str(error)}) from error
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail={"code": "decision_approval_invalid", "message": str(error)}) from error
        return decision_memo_response(approval.journal_entry, approval, None)

    @router.post("/commands/decisions/{decision_cycle_id}/approve", response_model=DecisionMemoResponse)
    def approve_decision(decision_cycle_id: str, command: DecisionApprovalCommand) -> DecisionMemoResponse:
        return _record_human_decision(decision_cycle_id, command, ApprovalDecision.APPROVED)

    @router.post("/commands/decisions/{decision_cycle_id}/reject", response_model=DecisionMemoResponse)
    def reject_decision(decision_cycle_id: str, command: DecisionApprovalCommand) -> DecisionMemoResponse:
        return _record_human_decision(decision_cycle_id, command, ApprovalDecision.REJECTED)

    @router.post("/commands/decisions/{decision_cycle_id}/execute-paper-trade", response_model=ExecutePaperTradeResponse)
    async def execute_paper_trade(decision_cycle_id: UUID, executed_at: datetime, request: Request) -> ExecutePaperTradeResponse:
        if managed_execution_service is None:
            raise HTTPException(status_code=503, detail={"code": "durable_state_required", "message": "paper execution requires configured local SQLite state"})
        if await request.body():
            raise HTTPException(status_code=422, detail={"code": "paper_execution_invalid", "message": "execution price and request body are not accepted"})
        try:
            result = managed_execution_service.execute(decision_cycle_id=decision_cycle_id, executed_at=executed_at)
        except ManagedPaperExecutionError as error:
            raise HTTPException(status_code=422, detail={"code": "paper_execution_ineligible", "message": str(error)}) from error
        execution = result.execution
        trade = execution.executed_trade
        observation = execution.execution_observation
        return ExecutePaperTradeResponse(
            decision_cycle_id=str(execution.decision_cycle_id), executed_trade_id=str(trade.executed_trade_id),
            validated_trade_id=str(trade.validated_trade_id), ticker=trade.security.ticker,
            quantity=format(trade.executed_quantity, "f"), notional=format(trade.executed_notional, "f"),
            execution_price=format(trade.execution_price, "f"), provider_identity=observation.source_provider_identity,
            observed_at=observation.observed_at.isoformat(), market_date=observation.market_date.isoformat(),
            price_convention=observation.price_convention, comparison_refreshed=result.comparison_refreshed,
        )

    @router.get("/portfolio", response_model=PortfolioSnapshotResponse)
    def portfolio() -> PortfolioSnapshotResponse:
        return _query_or_unavailable(service().portfolio)

    @router.get("/benchmark", response_model=BenchmarkSnapshotResponse)
    def benchmark() -> BenchmarkSnapshotResponse:
        return _query_or_unavailable(service().benchmark)

    @router.get("/performance", response_model=PerformanceResponse | None)
    def performance() -> PerformanceResponse | None:
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
