"""Read-only application queries over injectable immutable MVP state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agentic_portfolio_lab.dashboard import DashboardView, DecisionHistoryArtifacts, build_dashboard_view
from agentic_portfolio_lab.dashboard_demo import DashboardDemoData
from agentic_portfolio_lab.domain.approval import DecisionApproval
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
from agentic_portfolio_lab.domain.performance import BenchmarkPerformanceHistory, PerformanceComparison, PortfolioPerformanceHistory
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.benchmark_fulfillment import PassiveIndexFulfillment
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
    benchmark_snapshot_response,
    decision_memo_response,
    history_response,
    performance_response,
    portfolio_snapshot_response,
    research_batch_response,
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
    comparison: PerformanceComparison
    latest_journal_entry: DecisionJournalEntry | None
    latest_approval: DecisionApproval | None
    history_entries: tuple[DecisionHistoryArtifacts, ...]
    source_metadata: StateSourceMetadata
    research_batches: tuple = ()
    benchmark_fulfillments: tuple[PassiveIndexFulfillment, ...] = ()
    benchmark_fulfillment_status: str = "PENDING_NO_ELIGIBLE_PRICE"

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
            benchmark_fulfillments=(),
            benchmark_fulfillment_status="PENDING_NO_ELIGIBLE_PRICE",
        )


class MvpReadState(Protocol):
    """The replaceable immutable source required by the Phase 2 read API."""

    managed_history: PortfolioPerformanceHistory
    benchmark_history: BenchmarkPerformanceHistory
    comparison: PerformanceComparison
    latest_journal_entry: DecisionJournalEntry | None
    latest_approval: DecisionApproval | None
    history_entries: tuple[DecisionHistoryArtifacts, ...]
    source_metadata: StateSourceMetadata
    benchmark_fulfillment_status: str
    benchmark_fulfillments: tuple[PassiveIndexFulfillment, ...]


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
        )

    def health(self) -> HealthResponse:
        metadata = self._state.source_metadata
        return HealthResponse(
            status="ok",
            state_mode=metadata.mode,
            persisted=metadata.persisted,
            synthetic=metadata.synthetic,
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

    def performance(self) -> PerformanceResponse:
        return performance_response(self._state.comparison)

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
        )

    def research_latest(self) -> ResearchBatchResponse:
        persisted_batches = getattr(self._state, "research_batches", ())
        if persisted_batches:
            return research_batch_response(latest_authoritative_research_batch(persisted_batches))
        journal, _ = self._latest_journal_and_approval()
        return research_batch_response(journal.decision_result.context.research_batch)

    def decisions(self) -> HistoryResponse:
        history = self._dashboard_view().history
        if history is None:
            raise ValueError("decision history is unavailable")
        artifacts_by_entry_id = {
            str(entry.history_entry_id): entry.executed_trade for entry in self._state.history_entries
        }
        if {entry.history_entry_id for entry in history.entries_newest_first} != set(artifacts_by_entry_id):
            raise ValueError("decision history panels must match supplied immutable history artifacts")
        return history_response(history, artifacts_by_entry_id)

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
