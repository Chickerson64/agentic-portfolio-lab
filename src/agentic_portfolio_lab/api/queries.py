"""Read-only application queries over injectable immutable MVP state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from datetime import datetime, timezone
from uuid import UUID

from agentic_portfolio_lab.dashboard import DashboardView, DecisionHistoryArtifacts, build_dashboard_view
from agentic_portfolio_lab.dashboard_demo import DashboardDemoData
from agentic_portfolio_lab.domain.approval import DecisionApproval
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
from agentic_portfolio_lab.domain.reviewer import ReviewerResult
from agentic_portfolio_lab.domain.performance import BenchmarkPerformanceHistory, PerformanceComparison, PortfolioPerformanceHistory
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.benchmark_fulfillment import PassiveIndexFulfillment
from agentic_portfolio_lab.domain.research import ResearchBatch
from agentic_portfolio_lab.domain.screening import ScreeningRun
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.application.research_selection import latest_authoritative_research_batch

from .models import (
    BenchmarkSnapshotResponse,
    DashboardResponse,
    DecisionMemoResponse,
    HealthResponse,
    HistoryResponse,
    PerformanceResponse,
    PortfolioSnapshotResponse,
    ResearchBatchResponse,
    PriceRefreshStatusResponse,
    benchmark_snapshot_response,
    decision_memo_response,
    history_response,
    performance_response,
    portfolio_snapshot_response,
    research_batch_response,
    WorkflowChecklistArtifactResponse,
    WorkflowChecklistAuditFieldResponse,
    WorkflowChecklistResponse,
    WorkflowChecklistStepResponse,
    WeeklyRunReadinessResponse,
    WeeklyRunResponse,
    ReadinessBlockerResponse,
)


@dataclass(frozen=True, slots=True)
class StateSourceMetadata:
    """Truthful metadata describing an injected read-state source."""

    mode: str
    persisted: bool
    synthetic: bool


@dataclass(frozen=True, slots=True)
class MvpReadStateSnapshot:
    """Application-owned immutable state adapter for the read API."""

    managed_history: PortfolioPerformanceHistory
    benchmark_history: BenchmarkPerformanceHistory
    comparison: PerformanceComparison | None
    latest_journal_entry: DecisionJournalEntry | None
    latest_approval: DecisionApproval | None
    history_entries: tuple[DecisionHistoryArtifacts, ...]
    source_metadata: StateSourceMetadata
    research_batches: tuple = ()
    screening_runs: tuple[ScreeningRun, ...] = ()
    benchmark_fulfillments: tuple[PassiveIndexFulfillment, ...] = ()
    benchmark_fulfillment_status: str = "PENDING_NO_ELIGIBLE_PRICE"
    price_observations: tuple[PriceObservation, ...] = ()
    latest_price_refresh_operation: object | None = None
    reviewer_results: tuple[ReviewerResult, ...] = ()
    run_id: UUID | None = None
    run_status: str | None = None
    run_initialized_at: datetime | None = None

    @classmethod
    def from_dashboard_demo(cls, data: DashboardDemoData) -> "MvpReadStateSnapshot":
        return cls(
            managed_history=data.managed_history,
            benchmark_history=data.benchmark_history,
            comparison=data.comparison,
            latest_journal_entry=data.journal_entry,
            latest_approval=data.approval,
            history_entries=data.history_entries,
            source_metadata=StateSourceMetadata(
                mode="synthetic-in-memory",
                persisted=False,
                synthetic=True,
            ),
            research_batches=(),
            screening_runs=(),
            benchmark_fulfillments=(),
            benchmark_fulfillment_status="PENDING_NO_ELIGIBLE_PRICE",
        )


class MvpReadState(Protocol):
    """The replaceable immutable source required by the Phase 2 read API."""

    managed_history: PortfolioPerformanceHistory
    benchmark_history: BenchmarkPerformanceHistory
    comparison: PerformanceComparison | None
    latest_journal_entry: DecisionJournalEntry | None
    latest_approval: DecisionApproval | None
    history_entries: tuple[DecisionHistoryArtifacts, ...]
    source_metadata: StateSourceMetadata
    benchmark_fulfillment_status: str
    benchmark_fulfillments: tuple[PassiveIndexFulfillment, ...]
    price_observations: tuple[PriceObservation, ...]
    latest_price_refresh_operation: object | None
    reviewer_results: tuple[ReviewerResult, ...]


class LatestResourceNotFound(ValueError):
    """An explicitly absent optional latest resource, not an invalid state."""

    def __init__(self, resource: str) -> None:
        super().__init__(f"no latest {resource} is available")
        self.resource = resource


class MvpQueryService:
    """Compose existing immutable state into explicit API response models.

    The dependency is injected rather than constructed here, so a future local
    persistence-backed current-run source can replace the demo fixture without
    changing FastAPI routes or response contracts.
    """

    def __init__(self, state: MvpReadState) -> None:
        # Durable sources may load a fresh immutable aggregate for each HTTP
        # query. Keep that aggregate coherent for the complete query response.
        snapshot = getattr(state, "snapshot", None)
        self._state = snapshot() if callable(snapshot) else state

    def _dashboard_view(self) -> DashboardView:
        return build_dashboard_view(
            managed_history=self._state.managed_history,
            benchmark_history=self._state.benchmark_history,
            comparison=self._state.comparison,
            journal_entry=self._state.latest_journal_entry,
            approval=self._state.latest_approval,
            history_entries=self._state.history_entries,
            reviewer_results=getattr(self._state, "reviewer_results", ()),
        )

    def health(self) -> HealthResponse:
        metadata = self._state.source_metadata
        return HealthResponse(
            status="ok",
            state_mode=metadata.mode,
            persisted=metadata.persisted,
            synthetic=metadata.synthetic,
        )

    def latest_price_refresh(self) -> PriceRefreshStatusResponse:
        operation = getattr(self._state, "latest_price_refresh_operation", None)
        if operation is None:
            raise LatestResourceNotFound("price refresh operation")
        reported_at = datetime.now(timezone.utc)
        freshness = None if operation.latest_source_timestamp is None else max(0, int((reported_at - operation.latest_source_timestamp).total_seconds()))
        return PriceRefreshStatusResponse(
            operation_id=str(operation.operation_id), status=operation.status.value,
            started_at=operation.started_at.isoformat(), completed_at=None if operation.completed_at is None else operation.completed_at.isoformat(),
            provider_identity=operation.provider_identity, expected_security_count=operation.expected_security_count,
            persisted_observation_count=operation.persisted_observation_count,
            latest_source_timestamp=None if operation.latest_source_timestamp is None else operation.latest_source_timestamp.isoformat(),
            failure_code=operation.failure_code, failure_message=operation.failure_message,
            reported_at=reported_at.isoformat(), freshness_seconds=freshness,
        )

    def held_securities(self) -> tuple[SecurityIdentity, ...]:
        """Expose current managed holdings to command orchestration only."""
        return tuple(position.security for position in self._state.managed_history.snapshots[-1].portfolio.positions)

    def managed_portfolio_id(self):
        return self._state.managed_history.snapshots[-1].portfolio.portfolio_id

    def portfolio(self) -> PortfolioSnapshotResponse:
        return portfolio_snapshot_response(self._state.managed_history.snapshots[-1])

    def benchmark(self) -> BenchmarkSnapshotResponse:
        return benchmark_snapshot_response(
            self._state.benchmark_history.snapshots[-1],
            self._state.benchmark_history.benchmark_security,
        )

    def performance(self) -> PerformanceResponse | None:
        return None if self._state.comparison is None else performance_response(self._state.comparison)

    def _execution_for_journal(self, journal: DecisionJournalEntry):
        for entry in self._state.history_entries:
            if entry.journal_entry is journal:
                return entry.executed_trade
        return None

    def _latest_journal_and_approval(self) -> tuple[DecisionJournalEntry, DecisionApproval | None]:
        journal = self._state.latest_journal_entry
        approval = self._state.latest_approval
        if journal is None:
            if approval is not None:
                raise ValueError("latest approval cannot exist without a latest journal entry")
            raise LatestResourceNotFound("decision")
        if approval is not None and approval.journal_entry is not journal:
            raise ValueError("latest approval must reference the exact latest journal entry")
        return journal, approval

    def latest_decision(self) -> DecisionMemoResponse:
        journal, approval = self._latest_journal_and_approval()
        return decision_memo_response(
            journal,
            approval,
            self._execution_for_journal(journal),
            price_observations=self._state.price_observations, reviewer_result=self._reviewer_for(journal),
        )

    def decision_for_approval(self, decision_cycle_id: UUID) -> DecisionMemoResponse:
        matches = tuple(
            item for item in self._state.history_entries
            if item.journal_entry.decision_cycle_id == decision_cycle_id
        )
        if len(matches) != 1:
            raise ValueError("decision cycle must identify exactly one canonical history entry")
        artifact = matches[0]
        if artifact.approval is None:
            raise ValueError("decision outcome must retain its canonical approval")
        return decision_memo_response(
            artifact.journal_entry,
            artifact.approval,
            artifact.executed_trade,
            price_observations=self._state.price_observations, reviewer_result=self._reviewer_for(artifact.journal_entry),
        )

    def _reviewer_for(self, journal: DecisionJournalEntry) -> ReviewerResult | None:
        matches = tuple(item for item in getattr(self._state, "reviewer_results", ()) if item.decision_cycle_id == journal.decision_cycle_id)
        if len(matches) > 1:
            raise ValueError("decision cycle has ambiguous reviewer artifacts")
        return matches[0] if matches else None

    def _screening_run_for(self, batch: ResearchBatch) -> ScreeningRun | None:
        if batch.screening_run_id is None:
            return None
        runs = tuple(getattr(self._state, "screening_runs", ()))
        matches = tuple(run for run in runs if run.screening_run_id == batch.screening_run_id)
        if len(matches) != 1:
            return None
        return matches[0]

    def research_latest(self) -> ResearchBatchResponse:
        persisted_batches = getattr(self._state, "research_batches", ())
        if persisted_batches:
            batch = latest_authoritative_research_batch(persisted_batches)
        else:
            journal, _ = self._latest_journal_and_approval()
            batch = journal.decision_result.context.research_batch
        return research_batch_response(batch, self._screening_run_for(batch))

    def decisions(self) -> HistoryResponse:
        history = self._dashboard_view().history
        if history is None:
            raise ValueError("decision history is unavailable")
        artifacts_by_entry_id = {str(entry.history_entry_id): entry for entry in self._state.history_entries}
        if {entry.history_entry_id for entry in history.entries_newest_first} != set(artifacts_by_entry_id):
            raise ValueError("decision history panels must match supplied immutable history artifacts")
        return history_response(history, artifacts_by_entry_id, price_observations=self._state.price_observations)

    def dashboard(self) -> DashboardResponse:
        latest_decision = None
        research = None
        if self._state.latest_journal_entry is not None:
            latest_decision = self.latest_decision()
            research = self.research_latest()
        elif self._state.latest_approval is not None:
            self._latest_journal_and_approval()
        return DashboardResponse(
            portfolio=self.portfolio(),
            benchmark=self.benchmark(),
            performance=self.performance(),
            latest_decision=latest_decision,
            research=research,
            history=self.decisions(),
            benchmark_fulfillment_status=getattr(self._state, "benchmark_fulfillment_status", "PENDING_NO_ELIGIBLE_PRICE"),
        )

    def workflow_checklist(self) -> WorkflowChecklistResponse:
        """Project the operator checklist without changing, refreshing, or pricing state.

        This deliberately reads the operation and artifact timestamps directly;
        unlike ``latest_price_refresh`` it does not introduce a reporting-time
        clock value into the projection.
        """
        operation = getattr(self._state, "latest_price_refresh_operation", None)
        refresh = WorkflowChecklistStepResponse(
            step_id="price_refresh",
            label="Price refresh",
            status=None if operation is None else operation.status.value,
            reason_code=None if operation is None else operation.failure_code,
            completed=operation is not None and operation.status.value == "COMPLETED",
            terminal=False,
            artifact=None if operation is None else self._artifact(
                "price_refresh_operation", operation.operation_id, operation.completed_at or operation.started_at,
                provider_identity=operation.provider_identity,
                expected_security_count=operation.expected_security_count,
                persisted_observation_count=operation.persisted_observation_count,
                latest_source_timestamp=operation.latest_source_timestamp,
            ),
        )

        fulfillment_status = getattr(self._state, "benchmark_fulfillment_status", "PENDING_NO_ELIGIBLE_PRICE")
        fulfillments = tuple(getattr(self._state, "benchmark_fulfillments", ()))
        fulfillment = fulfillments[-1] if fulfillments else None
        benchmark = WorkflowChecklistStepResponse(
            step_id="spy_benchmark",
            label="SPY benchmark",
            status=fulfillment_status,
            reason_code=None,
            completed=fulfillment_status != "PENDING_NO_ELIGIBLE_PRICE",
            terminal=False,
            artifact=None if fulfillment is None else self._artifact(
                "benchmark_fulfillment", fulfillment.fulfillment_id, fulfillment.fulfilled_at,
                provider_identity=fulfillment.provider_identity,
                observed_at=fulfillment.price_observation.observed_at,
                decision_cycle_id=None,
            ),
        )

        batch = self._authoritative_research_or_none()
        research = WorkflowChecklistStepResponse(
            step_id="research",
            label="Research",
            status=None if batch is None else "AVAILABLE",
            reason_code=None,
            completed=batch is not None,
            terminal=False,
            artifact=None if batch is None else self._artifact(
                "research_batch", batch.batch_id, batch.created_at,
                decision_cycle_id=batch.decision_cycle_id, as_of_timestamp=batch.as_of_timestamp,
            ),
        )

        journal = self._state.latest_journal_entry
        approval = self._state.latest_approval
        execution = None
        reviewer = None
        readiness = None
        if journal is not None:
            execution = self._execution_for_journal(journal)
            reviewer = self._reviewer_for(journal)
            readiness = decision_memo_response(
                journal, approval, execution, price_observations=self._state.price_observations,
                reviewer_result=reviewer,
            ).execution_readiness

        decision = WorkflowChecklistStepResponse(
            step_id="value_manager_decision_validation",
            label="Value Manager decision and validation",
            status=None if journal is None else journal.risk_validation_result.status.value,
            reason_code=None if journal is None else journal.decision_result.recommendation.action.value,
            completed=journal is not None,
            terminal=journal is not None and (journal.decision_result.recommendation.action.value == "HOLD" or not journal.risk_validation_result.passed),
            artifact=None if journal is None else self._artifact(
                "decision_journal", journal.decision_cycle_id, journal.journaled_at,
                decision_cycle_id=journal.decision_cycle_id,
                produced_at=journal.decision_result.produced_at,
                action=journal.decision_result.recommendation.action.value,
                validation_status=journal.risk_validation_result.status.value,
                validated_trade_id=None if journal.risk_validation_result.validated_trade is None else journal.risk_validation_result.validated_trade.validated_trade_id,
            ),
        )
        review = WorkflowChecklistStepResponse(
            step_id="ai_reviewer",
            label="AI Reviewer",
            status=None if reviewer is None else reviewer.decision.value,
            reason_code=None,
            completed=reviewer is not None,
            terminal=False,
            artifact=None if reviewer is None else self._artifact(
                "ai_reviewer_result", reviewer.decision_cycle_id, reviewer.reviewed_at,
                decision_cycle_id=reviewer.decision_cycle_id,
                finding_count=len(reviewer.findings),
            ),
        )
        approval_step = WorkflowChecklistStepResponse(
            step_id="human_approval",
            label="Human approval",
            status=None if approval is None else approval.decision.value,
            reason_code=None if readiness is None else readiness.reason_code,
            completed=approval is not None,
            terminal=approval is not None and approval.decision.value != "APPROVED",
            artifact=None if approval is None else self._artifact(
                "decision_approval", approval.decision_cycle_id, approval.decided_at,
                decision_cycle_id=approval.decision_cycle_id,
                decision_maker_id=approval.decision_maker_id,
            ),
        )
        execution_step = WorkflowChecklistStepResponse(
            step_id="paper_execution",
            label="Paper execution",
            status=None if readiness is None else readiness.reason_code,
            reason_code=None if readiness is None else readiness.reason_code,
            completed=execution is not None,
            terminal=readiness is not None and readiness.reason_code in {"HOLD", "VALIDATION_FAILED", "REJECTED", "ALREADY_EXECUTED"},
            artifact=None if execution is None else self._artifact(
                "executed_trade", execution.executed_trade_id, execution.executed_at,
                decision_cycle_id=journal.decision_cycle_id if journal is not None else None,
                validated_trade_id=execution.validated_trade_id,
                ticker=execution.security.ticker,
            ),
            # ``executable`` is the existing authoritative readiness contract;
            # no command eligibility is reimplemented here.
            available_action=None if readiness is None or not readiness.executable else "EXECUTE_PAPER_TRADE",
        )
        return WorkflowChecklistResponse(steps=(refresh, benchmark, research, decision, review, approval_step, execution_step))

    def weekly_run_readiness(self) -> WeeklyRunReadinessResponse:
        """Return the current run's authoritative, non-mutating readiness view."""
        checklist = self.workflow_checklist()
        execution = checklist.steps[-1]
        blockers: list[ReadinessBlockerResponse] = []
        for step in checklist.steps:
            # Price-refresh failures are operation-owned blockers. Execution
            # readiness is calculated by the established decision contract.
            if step.step_id == "price_refresh" and step.status == "FAILED":
                blockers.append(ReadinessBlockerResponse(
                    step_id=step.step_id,
                    reason_code=step.reason_code or step.status,
                    artifact=step.artifact,
                ))
        if execution.reason_code is not None and execution.reason_code != "READY":
            blockers.append(ReadinessBlockerResponse(
                step_id=execution.step_id,
                reason_code=execution.reason_code,
                artifact=execution.artifact,
            ))
        current_run = None
        if self._state.run_id is not None:
            assert self._state.run_status is not None
            assert self._state.run_initialized_at is not None
            current_run = WeeklyRunResponse(
                run_id=str(self._state.run_id),
                status=self._state.run_status,
                initialized_at=self._state.run_initialized_at.isoformat(),
            )
        return WeeklyRunReadinessResponse(
            current_run=current_run,
            steps=checklist.steps,
            next_action=execution.available_action,
            blockers=tuple(blockers),
        )

    def _authoritative_research_or_none(self) -> ResearchBatch | None:
        batches = tuple(getattr(self._state, "research_batches", ()))
        if batches:
            return latest_authoritative_research_batch(batches)
        journal = self._state.latest_journal_entry
        # Older persisted snapshots predate standalone research batches.  Their
        # journal context remains the authoritative, representable lineage.
        return None if journal is None else journal.decision_result.context.research_batch

    @staticmethod
    def _artifact(artifact_type: str, artifact_id, occurred_at: datetime, *, decision_cycle_id=None, **fields) -> WorkflowChecklistArtifactResponse:
        return WorkflowChecklistArtifactResponse(
            artifact_type=artifact_type,
            artifact_id=str(artifact_id),
            occurred_at=occurred_at.isoformat(),
            decision_cycle_id=None if decision_cycle_id is None else str(decision_cycle_id),
            audit_fields=tuple(
                WorkflowChecklistAuditFieldResponse(name=name, value=value.isoformat() if isinstance(value, datetime) else str(value))
                for name, value in fields.items() if value is not None
            ),
        )
