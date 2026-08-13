"""Immutable aggregate state for one local paper-trading run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from typing import Protocol

from agentic_portfolio_lab.dashboard import DecisionHistoryArtifacts
from agentic_portfolio_lab.domain.approval import DecisionApproval
from agentic_portfolio_lab.domain.cash_events import CashEvent, CashEventFundingResult
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
from agentic_portfolio_lab.domain.performance import BenchmarkPerformanceHistory, PortfolioPerformanceHistory
from agentic_portfolio_lab.domain.research import ResearchBatch
from agentic_portfolio_lab.domain.simulated_execution import SimulatedExecutionResult
from agentic_portfolio_lab.domain.valuation import BenchmarkPortfolio, PriceObservation
from agentic_portfolio_lab.domain.portfolio import Portfolio


@dataclass(frozen=True, slots=True)
class LocalRunMetadata:
    run_id: UUID
    status: str
    initialized_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, UUID):
            raise TypeError("run_id must be a UUID")
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError("status must be non-empty")
        if not isinstance(self.initialized_at, datetime) or self.initialized_at.tzinfo is None or self.initialized_at.utcoffset() is None:
            raise ValueError("initialized_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class PersistedRunState:
    """One coherent durable state graph, composed solely of existing artifacts."""

    metadata: LocalRunMetadata
    managed_portfolio: Portfolio
    benchmark_portfolio: BenchmarkPortfolio
    managed_history: PortfolioPerformanceHistory
    benchmark_history: BenchmarkPerformanceHistory
    funding_results: tuple[CashEventFundingResult, ...] = ()
    price_observations: tuple[PriceObservation, ...] = ()
    research_batches: tuple[ResearchBatch, ...] = ()
    journal_entries: tuple[DecisionJournalEntry, ...] = ()
    approvals: tuple[DecisionApproval, ...] = ()
    executions: tuple[SimulatedExecutionResult, ...] = ()
    history_entries: tuple[DecisionHistoryArtifacts, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, LocalRunMetadata):
            raise TypeError("metadata must be LocalRunMetadata")
        if not isinstance(self.managed_portfolio, Portfolio):
            raise TypeError("managed_portfolio must be a Portfolio")
        if not isinstance(self.benchmark_portfolio, BenchmarkPortfolio):
            raise TypeError("benchmark_portfolio must be a BenchmarkPortfolio")
        if not isinstance(self.managed_history, PortfolioPerformanceHistory):
            raise TypeError("managed_history must be a PortfolioPerformanceHistory")
        if not isinstance(self.benchmark_history, BenchmarkPerformanceHistory):
            raise TypeError("benchmark_history must be a BenchmarkPerformanceHistory")
        for name in ("funding_results", "price_observations", "research_batches", "journal_entries", "approvals", "executions", "history_entries"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                raise TypeError(f"{name} must be a tuple")
        self._validate_current_history()
        self._validate_funding()
        self._validate_decision_graph()

    def _validate_current_history(self) -> None:
        if self.managed_history.snapshots:
            latest = self.managed_history.snapshots[-1].portfolio
            if latest != self.managed_portfolio:
                raise ValueError("current managed portfolio must match the latest managed history portfolio")
        if self.benchmark_history.snapshots:
            latest = self.benchmark_history.snapshots[-1].portfolio
            if latest != self.benchmark_portfolio.portfolio:
                raise ValueError("current benchmark portfolio must match the latest benchmark history portfolio")
        if self.managed_history.portfolio_id != self.managed_portfolio.portfolio_id:
            raise ValueError("managed history identity must match current managed portfolio")
        if self.benchmark_history.benchmark_portfolio_id != self.benchmark_portfolio.portfolio.portfolio_id:
            raise ValueError("benchmark history identity must match current benchmark portfolio")

    def _validate_funding(self) -> None:
        event_ids = tuple(result.cash_event.event_id for result in self.funding_results)
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("funding_results must not contain duplicate CashEvent identities")
        known_events = set(event_ids)
        for history in (self.managed_history, self.benchmark_history):
            for snapshot in history.snapshots:
                if any(event.event_id not in known_events for event in snapshot.cash_events):
                    raise ValueError("performance history CashEvents must be present in funding_results")

    def _validate_decision_graph(self) -> None:
        journals = {journal.decision_cycle_id: journal for journal in self.journal_entries}
        if len(journals) != len(self.journal_entries):
            raise ValueError("journal_entries must not contain duplicate decision cycles")
        for journal in self.journal_entries:
            if journal.portfolio_id != self.managed_portfolio.portfolio_id:
                raise ValueError("journal portfolio lineage must match the current managed portfolio")
            matching_batches = tuple(batch for batch in self.research_batches if batch.batch_id == journal.research_batch_id)
            if matching_batches and matching_batches[0] != journal.decision_result.context.research_batch:
                raise ValueError("journal research batch must match the persisted research batch")
        approvals = {approval.decision_cycle_id: approval for approval in self.approvals}
        if len(approvals) != len(self.approvals):
            raise ValueError("approvals must not contain duplicate decision cycles")
        for approval in self.approvals:
            journal = journals.get(approval.decision_cycle_id)
            if journal is None or approval.journal_entry is not journal:
                raise ValueError("approval must reference an exact canonical persisted journal")
        executions = {execution.decision_cycle_id: execution for execution in self.executions}
        if len(executions) != len(self.executions):
            raise ValueError("executions must not contain duplicate decision cycles")
        execution_ids = {execution.executed_trade.executed_trade_id for execution in self.executions}
        if len(execution_ids) != len(self.executions):
            raise ValueError("executions must not contain duplicate executed trade identities")
        for cycle_id, execution in executions.items():
            journal = journals.get(cycle_id)
            approval = approvals.get(cycle_id)
            if journal is None or approval is None or execution.approval is not approval:
                raise ValueError("execution must belong to a canonical persisted journal and approval")
            if execution.executed_trade.portfolio_id != journal.portfolio_id:
                raise ValueError("execution portfolio lineage must match its journal")
            if execution.executed_trade.validated_trade is not journal.risk_validation_result.validated_trade:
                raise ValueError("execution must use the journal's exact authoritative validated trade")
        history_by_cycle = {entry.journal_entry.decision_cycle_id: entry for entry in self.history_entries}
        if len(history_by_cycle) != len(self.history_entries):
            raise ValueError("history_entries must not contain duplicate decision cycles")
        for entry in self.history_entries:
            journal = journals.get(entry.journal_entry.decision_cycle_id)
            if journal is None or entry.journal_entry is not journal:
                raise ValueError("history entry must reference an exact canonical persisted journal")
            approval = approvals.get(journal.decision_cycle_id)
            if entry.approval is not approval:
                raise ValueError("history entry approval must reference the canonical persisted approval")
            execution = executions.get(journal.decision_cycle_id)
            if entry.executed_trade is not None and execution is None:
                raise ValueError("history execution requires a canonical persisted execution artifact")
            if entry.executed_trade is not None and entry.executed_trade is not execution.executed_trade:
                raise ValueError("history execution must reuse the canonical persisted executed trade")
            if execution is not None and entry.executed_trade is None:
                raise ValueError("canonical persisted execution must not be omitted from history")
        for cycle_id, execution in executions.items():
            entry = history_by_cycle.get(cycle_id)
            if entry is None or entry.executed_trade is not execution.executed_trade:
                raise ValueError("every persisted execution must appear in one canonical history entry")

    def validate(self) -> None:
        """Validate aggregate coherence before a persistence transaction."""
        self._validate_current_history()
        self._validate_funding()
        self._validate_decision_graph()

    @property
    def cash_events(self) -> tuple[CashEvent, ...]:
        return tuple(result.cash_event for result in self.funding_results)

    @property
    def latest_journal_entry(self) -> DecisionJournalEntry | None:
        return self.journal_entries[-1] if self.journal_entries else None

    @property
    def latest_approval(self) -> DecisionApproval | None:
        journal = self.latest_journal_entry
        if journal is None:
            return None
        return next((item for item in reversed(self.approvals) if item.journal_entry is journal), None)


class LocalRunStateStore(Protocol):
    """The deliberately small persistence boundary for one local run."""

    def initialize_run(self, *, initialized_at: datetime) -> PersistedRunState: ...

    def open_run(self) -> PersistedRunState | None: ...

    def save_transition(self, state: PersistedRunState) -> None: ...
