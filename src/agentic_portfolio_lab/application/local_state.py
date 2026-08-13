"""Immutable aggregate state for one local paper-trading run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from typing import Protocol

from agentic_portfolio_lab.dashboard import DecisionHistoryArtifacts
from agentic_portfolio_lab.domain.approval import DecisionApproval
from agentic_portfolio_lab.domain.benchmark_fulfillment import PassiveIndexFulfillment
from agentic_portfolio_lab.domain.cash_events import CashEvent, CashEventFundingResult
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
from agentic_portfolio_lab.domain.performance import BenchmarkPerformanceHistory, PortfolioPerformanceHistory
from agentic_portfolio_lab.domain.research import ResearchBatch
from agentic_portfolio_lab.domain.simulated_execution import SimulatedExecutionResult
from agentic_portfolio_lab.domain.valuation import BenchmarkPortfolio, PriceObservation
from agentic_portfolio_lab.domain.portfolio import Portfolio
from agentic_portfolio_lab.domain.portfolio_service import PortfolioService
from decimal import Decimal


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
    benchmark_fulfillments: tuple[PassiveIndexFulfillment, ...] = ()
    benchmark_fulfillment_status: str = "PENDING_NO_ELIGIBLE_PRICE"

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
        for name in ("funding_results", "price_observations", "research_batches", "journal_entries", "approvals", "executions", "history_entries", "benchmark_fulfillments"):
            value = getattr(self, name, ())
            if not isinstance(value, tuple):
                raise TypeError(f"{name} must be a tuple")
        self._validate_current_history()
        self._validate_funding()
        self._validate_decision_graph()
        self._validate_benchmark_fulfillments()
        if getattr(self, "benchmark_fulfillment_status", "PENDING_NO_ELIGIBLE_PRICE") not in {
            "FULFILLED", "NO_ACTION_ZERO_CASH", "NO_ACTION_INSUFFICIENT_BUYING_POWER", "PENDING_NO_ELIGIBLE_PRICE",
        }:
            raise ValueError("benchmark_fulfillment_status is invalid")
        self._validate_benchmark_status()

    def _validate_benchmark_fulfillments(self) -> None:
        fulfillments = tuple(getattr(self, "benchmark_fulfillments", ()))
        fulfillment_ids = tuple(item.fulfillment_id for item in fulfillments)
        if len(set(fulfillment_ids)) != len(fulfillment_ids):
            raise ValueError("benchmark_fulfillments must not contain duplicate identities")
        observations = {
            (item.security, item.observed_at): item
            for item in self.price_observations
        }
        previous_timestamp: datetime | None = None
        fulfillment_transitions: dict[int, PassiveIndexFulfillment] = {}
        for fulfillment in fulfillments:
            canonical_observation = observations.get((fulfillment.price_observation.security, fulfillment.price_observation.observed_at))
            if canonical_observation is None:
                raise ValueError("benchmark fulfillment price observation must be persisted")
            if fulfillment.price_observation is not canonical_observation:
                raise ValueError("benchmark fulfillment must reuse the canonical persisted price observation")
            if previous_timestamp is not None and fulfillment.fulfilled_at <= previous_timestamp:
                raise ValueError("benchmark fulfillments must be in strictly increasing fulfilled_at order")
            original_index, updated_index = self._fulfillment_history_occurrence(fulfillment)
            if original_index in fulfillment_transitions:
                raise ValueError("benchmark history transition must not have multiple fulfillments")
            fulfillment_transitions[original_index] = fulfillment
            previous_timestamp = fulfillment.fulfilled_at
        self._validate_benchmark_history_transitions(fulfillment_transitions)

    def _fulfillment_history_occurrence(self, fulfillment: PassiveIndexFulfillment) -> tuple[int, int]:
        matches = tuple(
            (index, index + 1)
            for index in range(len(self.benchmark_history.snapshots) - 1)
            if self.benchmark_history.snapshots[index].portfolio == fulfillment.original_benchmark_portfolio.portfolio
            and self.benchmark_history.snapshots[index + 1].portfolio == fulfillment.fulfilled_benchmark_portfolio.portfolio
            and self.benchmark_history.snapshots[index + 1].timestamp == fulfillment.fulfilled_at
        )
        if not matches:
            raise ValueError("benchmark fulfillment must match an authoritative adjacent history occurrence at fulfilled_at")
        if len(matches) != 1:
            raise ValueError("benchmark fulfillment history occurrence is ambiguous")
        return matches[0]

    def _validate_benchmark_history_transitions(self, fulfillments_by_index: dict[int, PassiveIndexFulfillment]) -> None:
        snapshots = self.benchmark_history.snapshots
        by_event = {result.cash_event.event_id: result for result in self.funding_results}
        for index in range(len(snapshots) - 1):
            before, after = snapshots[index], snapshots[index + 1]
            fulfillment = fulfillments_by_index.get(index)
            if after.cash_events:
                if fulfillment is not None or len(after.cash_events) != 1:
                    raise ValueError("benchmark history transition must have exactly one authoritative cause")
                event = after.cash_events[0]
                result = by_event.get(event.event_id)
                if result is None or result.cash_event is not event:
                    raise ValueError("benchmark CashEvent transition must reuse an exact persisted funding result")
                if before.portfolio != result.original_benchmark_portfolio.portfolio or after.portfolio != result.funded_benchmark_portfolio.portfolio:
                    raise ValueError("benchmark history funding transition must exactly match its funding result")
            elif fulfillment is not None:
                if before.portfolio != fulfillment.original_benchmark_portfolio.portfolio or after.portfolio != fulfillment.fulfilled_benchmark_portfolio.portfolio:
                    raise ValueError("benchmark history fulfillment transition must exactly match its fulfillment")
            elif before.portfolio != after.portfolio:
                raise ValueError("benchmark history contains an unexplained portfolio-state transition")

    def _validate_benchmark_status(self) -> None:
        status = getattr(self, "benchmark_fulfillment_status", "PENDING_NO_ELIGIBLE_PRICE")
        cash = self.benchmark_portfolio.portfolio.cash_balance.amount
        fulfillments = tuple(getattr(self, "benchmark_fulfillments", ()))
        if status == "FULFILLED":
            if not fulfillments or fulfillments[-1].fulfilled_benchmark_portfolio != self.benchmark_portfolio:
                raise ValueError("FULFILLED status requires the current state to match the latest fulfillment")
        elif status == "NO_ACTION_ZERO_CASH":
            if not cash.is_zero():
                raise ValueError("NO_ACTION_ZERO_CASH requires zero current benchmark cash")
        elif status == "NO_ACTION_INSUFFICIENT_BUYING_POWER":
            if cash.is_zero():
                raise ValueError("NO_ACTION_INSUFFICIENT_BUYING_POWER requires positive benchmark cash")
            funding_boundary = max(result.cash_event.effective_at for result in self.funding_results)
            eligible = tuple(item for item in self.price_observations if item.security == self.benchmark_portfolio.benchmark_security and item.observed_at >= funding_boundary)
            if not eligible or not PortfolioService.calculate_target_purchase(self.benchmark_portfolio.portfolio, self.benchmark_portfolio.benchmark_security, Decimal("1"), max(eligible, key=lambda item: item.observed_at).observed_price).purchasable_quantity.is_zero():
                raise ValueError("NO_ACTION_INSUFFICIENT_BUYING_POWER requires an eligible quote with zero feasible quantity")
        elif status == "PENDING_NO_ELIGIBLE_PRICE":
            if cash.is_zero():
                raise ValueError("PENDING_NO_ELIGIBLE_PRICE requires positive current benchmark cash")
            if fulfillments and fulfillments[-1].fulfilled_benchmark_portfolio == self.benchmark_portfolio:
                raise ValueError("PENDING_NO_ELIGIBLE_PRICE cannot relabel residual cash after the latest fulfillment")

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
        self._validate_benchmark_fulfillments()
        self._validate_benchmark_status()

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
