"""Thin HTTP adapter over deterministic application commands and queries."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from agentic_portfolio_lab.application.refresh_prices import PriceRefreshConflict, RefreshPricesService
from agentic_portfolio_lab.application.build_research import BuildResearchService
from agentic_portfolio_lab.application.bootstrap_overview import BootstrapOverviewService
from agentic_portfolio_lab.application.wave2_commands import BenchmarkFulfillmentService, CashEventService
from agentic_portfolio_lab.application.decision_commands import DecisionApprovalService, DecisionCommandConflict, ReviewDecisionService, RunValueManagerService, ReviseDecisionCycleService
from agentic_portfolio_lab.domain.approval import ApprovalDecision
from agentic_portfolio_lab.application.managed_execution import ManagedPaperExecutionError, ManagedPaperExecutionService
from agentic_portfolio_lab.domain.market_prices import MarketPriceConfigurationError, MarketPriceError
from agentic_portfolio_lab.domain.research_provider import ResearchProviderConfigurationError, ResearchProviderError
from agentic_portfolio_lab.application.v2_weekly_cycle import V2WeeklyCycleService

from .models import (
    BenchmarkSnapshotResponse,
    DashboardResponse,
    DecisionMemoResponse,
    DecisionCycleAuditResponse,
    HealthResponse,
    HistoryResponse,
    PerformanceResponse,
    PortfolioSnapshotResponse,
    ResearchBatchResponse,
    WeeklyRunReadinessResponse,
    PriceRefreshResponse,
    PriceRefreshStatusResponse,
    PriceRefreshRecoveryCommand,
    BuildResearchResponse,
    BootstrapOverviewResponse,
    CashEventCommand,
    CashEventResponse,
    BenchmarkFulfillmentResponse,
    DecisionApprovalCommand,
    RevisionDecisionCommand, RevisionDecisionResponse,
    RunValueManagerCommand,
    decision_memo_response,
    ExecutePaperTradeResponse,
    security_response,
    V2ApprovalCommand,
    V2RejectionCommand,
    V2CycleResponse,
)
from .queries import DecisionCycleNotFound, LatestResourceNotFound, MvpQueryService, MvpReadState


def _query_or_unavailable(query):
    try:
        return query()
    except LatestResourceNotFound as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "latest_resource_not_found", "message": str(error)},
        ) from error
    except DecisionCycleNotFound as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "decision_cycle_not_found", "message": str(error)},
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
    review_decision_service: ReviewDecisionService | None = None,
    decision_approval_service: DecisionApprovalService | None = None,
    managed_execution_service: ManagedPaperExecutionService | None = None,
    revision_service: ReviseDecisionCycleService | None = None,
    v2_cycle_service: V2WeeklyCycleService | None = None,
    v2_preparation_service=None,
    v2_readiness_reason: str | None = None,
) -> APIRouter:
    router = APIRouter()

    def service() -> MvpQueryService:
        # A durable state source is loaded once for each HTTP query, avoiding a
        # stale startup snapshot while keeping each response internally coherent.
        return MvpQueryService(state)

    def v2_response(cycle_id: UUID) -> V2CycleResponse:
        if v2_cycle_service is None:
            raise HTTPException(status_code=503, detail={"code": "durable_state_required", "message": "V2 cycles require configured local SQLite state"})
        try:
            cycle = v2_cycle_service.get(cycle_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail={"code": "v2_cycle_not_found", "message": str(error)}) from error
        def security(item): return {"ticker": item.ticker, "security_type": item.security_type, "exchange": item.exchange, "currency": item.currency}
        def portfolio(item): return {"portfolio_id": str(item.portfolio_id), "cash": format(item.cash_balance.amount, "f"), "positions": tuple({"security": security(p.security), "quantity": format(p.quantity, "f"), "cost_basis": format(p.total_cost_basis, "f")} for p in item.positions)}
        target = {"portfolio_id": str(cycle.target.portfolio_id), "total_weight": "1.000000", "rationale": cycle.target.overall_rationale, "risk_commentary": cycle.target.risk_commentary, "cash": {"weight": format(cycle.target.cash_target.weight, "f"), "classification": cycle.target.cash_target.classification.value, "rationale": cycle.target.cash_target.rationale}, "positions": tuple({"security": security(p.security), "weight": format(p.target_weight, "f"), "disposition": p.existing_holding_disposition.value, "role": p.role, "thesis": p.thesis, "confidence": p.confidence, "evidence": tuple({"evidence_id": e.evidence_id, "source": e.source_title, "date": e.source_date.isoformat(), "claim": e.claim_supported} for e in p.evidence)} for p in cycle.target.positions)}
        execution = None if cycle.execution is None else {"execution_id": str(cycle.execution.execution_id), "backend": cycle.execution_backend, "executed_at": cycle.execution.executed_at.isoformat()}
        return V2CycleResponse(cycle_id=str(cycle.cycle_id), readiness=cycle.readiness(), current_portfolio=portfolio(cycle.original_portfolio), target=target,
            screening={"screening_run_id": str(cycle.screening.screening_run_id), "universe_snapshot_id": cycle.screening.universe_snapshot_id},
            research={"batch_id": cycle.research.batch_id, "screening_run_id": str(cycle.research.screening_run_id), "snapshot_id": cycle.research.snapshot_id},
            plan={"plan_id": str(cycle.plan.plan_id), "identity": cycle.plan.identity, "legs": tuple({"security": security(x.security), "action": x.action.value, "quantity": format(x.quantity, "f"), "price": format(x.price, "f"), "target_weight": format(x.target_weight, "f")} for x in cycle.plan.legs)},
            system_safety={"passed": cycle.system_safety.passed, "identity": cycle.system_safety.identity, "reason": cycle.system_safety.reason, "source": "V2 System Safety validator"}, manager_risk={"status": cycle.manager_risk.status.value, "constitution_version": cycle.manager_risk.constitution.risk_constitution_version.value, "target_identity": cycle.manager_risk.target_identity, "plan_identity": cycle.manager_risk.plan_identity, "findings": cycle.manager_risk.findings, "rationale": cycle.manager_risk.rationale, "provider_identity": cycle.manager_risk.provider_identity}, ai_reviewer=None if cycle.reviewer is None else {"status": cycle.reviewer.status.value, "target_identity": cycle.reviewer.target_identity, "plan_identity": cycle.reviewer.plan_identity, "findings": cycle.reviewer.findings, "rationale": cycle.reviewer.rationale, "reviewer_identity": cycle.reviewer.reviewer_identity, "reviewer_version": cycle.reviewer.reviewer_version, "provider_identity": cycle.reviewer.provider_identity, "model": cycle.reviewer.model},
            approval=None if cycle.approval is None else {"approval_id": str(cycle.approval.approval_id), "binding": cycle.approval.binding, "decision_maker_id": cycle.approval.decision_maker_id, "decided_at": cycle.approval.decided_at.isoformat()}, execution=execution,
            rejection=None if cycle.rejection is None else {"rejection_id": str(cycle.rejection.rejection_id), "binding": cycle.rejection.binding, "decision_maker_id": cycle.rejection.decision_maker_id, "decided_at": cycle.rejection.decided_at.isoformat(), "reason": cycle.rejection.reason},
            reconciliation=None if cycle.execution is None else {"resulting_portfolio": portfolio(cycle.execution.resulting_portfolio), "reconciled_at": cycle.reconciled_at.isoformat() if cycle.reconciled_at else None}, performance=None if service().performance() is None else service().performance().model_dump(), audit={"universe_snapshot_id": cycle.universe_snapshot_id, "target_identity": cycle.plan.target_identity, "plan_identity": cycle.plan.identity})

    @router.get("/v2/cycles/{cycle_id}", response_model=V2CycleResponse)
    def get_v2_cycle(cycle_id: UUID) -> V2CycleResponse:
        return v2_response(cycle_id)

    @router.get("/v2/cycles/latest", response_model=V2CycleResponse)
    def latest_v2_cycle() -> V2CycleResponse:
        if v2_cycle_service is None: raise HTTPException(status_code=503, detail="V2 cycles require configured local SQLite state")
        state = v2_cycle_service._state()
        if not state.v2_cycles: raise HTTPException(status_code=404, detail={"code": "v2_cycle_not_found", "message": "no V2 cycle has been prepared"})
        return v2_response(state.v2_cycles[-1].cycle_id)

    @router.post("/v2/cycles", response_model=V2CycleResponse)
    def prepare_v2_cycle() -> V2CycleResponse:
        if v2_preparation_service is None:
            raise HTTPException(status_code=503, detail={"code": "v2_preparation_unconfigured", "message": "V2 preparation requires configured universe, market-data, research, manager, and advisory services"})
        try:
            cycle = v2_preparation_service.prepare()
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=503, detail={"code": "v2_preparation_unavailable", "message": str(error)}) from error
        return v2_response(cycle.cycle_id)

    @router.get("/v2/readiness")
    def v2_readiness() -> dict[str, object]:
        return {"ready": v2_preparation_service is not None, "reason_code": None if v2_preparation_service is not None else (v2_readiness_reason or "V2_PREPARATION_UNCONFIGURED")}

    @router.post("/v2/cycles/{cycle_id}/approve", response_model=V2CycleResponse)
    def approve_v2_cycle(cycle_id: UUID, command: V2ApprovalCommand) -> V2CycleResponse:
        if v2_cycle_service is None: raise HTTPException(status_code=503, detail="V2 cycles require configured local SQLite state")
        try: v2_cycle_service.approve(cycle_id, decision_maker_id=command.decision_maker_id, decided_at=command.decided_at)
        except ValueError as error: raise HTTPException(status_code=409, detail={"code": "v2_approval_ineligible", "message": str(error)}) from error
        return v2_response(cycle_id)

    @router.post("/v2/cycles/{cycle_id}/reject", response_model=V2CycleResponse)
    def reject_v2_cycle(cycle_id: UUID, command: V2RejectionCommand) -> V2CycleResponse:
        if v2_cycle_service is None: raise HTTPException(status_code=503, detail="V2 cycles require configured local SQLite state")
        try: v2_cycle_service.reject(cycle_id, decision_maker_id=command.decision_maker_id, decided_at=command.decided_at, reason=command.reason)
        except ValueError as error: raise HTTPException(status_code=409, detail={"code": "v2_rejection_ineligible", "message": str(error)}) from error
        return v2_response(cycle_id)

    @router.post("/v2/cycles/{cycle_id}/execute", response_model=V2CycleResponse)
    def execute_v2_cycle(cycle_id: UUID, executed_at: datetime) -> V2CycleResponse:
        if v2_cycle_service is None: raise HTTPException(status_code=503, detail="V2 cycles require configured local SQLite state")
        try: v2_cycle_service.execute(cycle_id, executed_at=executed_at)
        except ValueError as error: raise HTTPException(status_code=409, detail={"code": "v2_execution_ineligible", "message": str(error)}) from error
        return v2_response(cycle_id)

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return service().health()

    @router.post("/commands/refresh-prices", response_model=PriceRefreshResponse)
    def refresh_prices() -> PriceRefreshResponse:
        try:
            result = refresh_service.refresh(service().held_securities())
        except PriceRefreshConflict as error:
            raise HTTPException(status_code=409, detail={"code": "price_refresh_in_progress", "message": str(error)}) from error
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

    @router.get("/price-refresh/latest", response_model=PriceRefreshStatusResponse)
    def latest_price_refresh() -> PriceRefreshStatusResponse:
        return _query_or_unavailable(service().latest_price_refresh)

    @router.post("/commands/recover-price-refresh", response_model=PriceRefreshStatusResponse)
    def recover_price_refresh(command: PriceRefreshRecoveryCommand) -> PriceRefreshStatusResponse:
        try:
            refresh_service.recover_interrupted(command.operation_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail={"code": "price_refresh_recovery_unavailable", "message": str(error)}) from error
        return _query_or_unavailable(service().latest_price_refresh)

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
        return _query_or_unavailable(service().latest_decision)

    @router.post("/commands/decisions/{decision_cycle_id}/review", response_model=DecisionMemoResponse)
    def review_decision(decision_cycle_id: UUID) -> DecisionMemoResponse:
        if review_decision_service is None:
            raise HTTPException(status_code=503, detail={"code": "durable_state_required", "message": "AI review requires configured local SQLite state"})
        try:
            result = review_decision_service.review(decision_cycle_id=decision_cycle_id)
        except DecisionCommandConflict as error:
            raise HTTPException(status_code=409, detail={"code": "decision_conflict", "message": str(error)}) from error
        except RuntimeError as error:
            raise HTTPException(status_code=502, detail={"code": "reviewer_unavailable", "message": str(error)}) from error
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail={"code": "reviewer_invalid", "message": str(error)}) from error
        return _query_or_unavailable(service().latest_decision)

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
        return _query_or_unavailable(lambda: service().decision_for_approval(approval.decision_cycle_id))

    @router.post("/commands/decisions/{decision_cycle_id}/approve", response_model=DecisionMemoResponse)
    def approve_decision(decision_cycle_id: str, command: DecisionApprovalCommand) -> DecisionMemoResponse:
        return _record_human_decision(decision_cycle_id, command, ApprovalDecision.APPROVED)

    @router.post("/commands/decisions/{decision_cycle_id}/reject", response_model=DecisionMemoResponse)
    def reject_decision(decision_cycle_id: str, command: DecisionApprovalCommand) -> DecisionMemoResponse:
        return _record_human_decision(decision_cycle_id, command, ApprovalDecision.REJECTED)

    @router.post("/commands/decisions/{decision_cycle_id}/revise", response_model=RevisionDecisionResponse)
    def revise_decision(decision_cycle_id: UUID, command: RevisionDecisionCommand) -> RevisionDecisionResponse:
        if revision_service is None:
            raise HTTPException(status_code=503, detail={"code": "durable_state_required", "message": "decision revisions require configured local SQLite state"})
        try:
            batch = revision_service.create(decision_cycle_id=decision_cycle_id, occurred_at=command.occurred_at)
        except DecisionCommandConflict as error:
            raise HTTPException(status_code=409, detail={"code": "decision_conflict", "message": str(error)}) from error
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail={"code": "decision_revision_invalid", "message": str(error)}) from error
        assert batch.revision_of_decision_cycle_id is not None
        return RevisionDecisionResponse(batch_id=batch.batch_id, decision_cycle_id=str(batch.decision_cycle_id), revision_of_decision_cycle_id=str(batch.revision_of_decision_cycle_id))

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

    @router.get("/decisions/{decision_cycle_id}/audit", response_model=DecisionCycleAuditResponse)
    def decision_cycle_audit(decision_cycle_id: UUID) -> DecisionCycleAuditResponse:
        return _query_or_unavailable(lambda: service().decision_cycle_audit(decision_cycle_id))

    @router.get("/decisions", response_model=HistoryResponse)
    def decisions() -> HistoryResponse:
        return _query_or_unavailable(service().decisions)

    @router.get("/research/latest", response_model=ResearchBatchResponse)
    def research_latest() -> ResearchBatchResponse:
        return _query_or_unavailable(service().research_latest)

    @router.get("/dashboard", response_model=DashboardResponse)
    def dashboard() -> DashboardResponse:
        return _query_or_unavailable(service().dashboard)

    @router.get("/weekly-run/readiness", response_model=WeeklyRunReadinessResponse)
    def weekly_run_readiness() -> WeeklyRunReadinessResponse:
        return _query_or_unavailable(service().weekly_run_readiness)

    return router
