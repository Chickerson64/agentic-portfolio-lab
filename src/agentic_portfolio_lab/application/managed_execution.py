"""Durable boundary for one approved managed-paper BUY execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from agentic_portfolio_lab.application.local_state import PersistedRunState
from agentic_portfolio_lab.dashboard import DecisionHistoryArtifacts
from agentic_portfolio_lab.domain.approval import ApprovalDecision
from agentic_portfolio_lab.domain.recommendations import RecommendationAction
from agentic_portfolio_lab.domain.simulated_execution import SimulatedExecutionResult, SimulatedExecutionWorkflow
from agentic_portfolio_lab.domain.valuation import PortfolioValuation, PriceObservation


class ManagedPaperExecutionError(ValueError):
    """The persisted decision graph is not eligible for paper execution."""


@dataclass(frozen=True, slots=True)
class ManagedPaperExecutionResult:
    execution: SimulatedExecutionResult
    comparison_refreshed: bool


class ManagedPaperExecutionService:
    """Resolve canonical state artifacts, execute once, then persist atomically."""

    def __init__(self, store) -> None:
        self._store = store

    def execute(self, *, decision_cycle_id: UUID, executed_at: datetime) -> ManagedPaperExecutionResult:
        if not isinstance(executed_at, datetime) or executed_at.tzinfo is None or executed_at.utcoffset() is None:
            raise ManagedPaperExecutionError("executed_at must be timezone-aware")
        state = self._require_state()
        journal = self._one(state.journal_entries, lambda item: item.decision_cycle_id == decision_cycle_id, "journal")
        approval = self._one(state.approvals, lambda item: item.decision_cycle_id == decision_cycle_id, "approval")
        if approval.journal_entry is not journal:
            raise ManagedPaperExecutionError("approval does not reference the canonical journal")
        if approval.decision is not ApprovalDecision.APPROVED:
            raise ManagedPaperExecutionError("paper execution requires an APPROVED approval")
        recommendation = journal.decision_result.recommendation
        validation = journal.risk_validation_result
        if recommendation.action is not RecommendationAction.BUY:
            raise ManagedPaperExecutionError("paper execution requires a BUY recommendation")
        if not validation.passed:
            raise ManagedPaperExecutionError("paper execution requires passed deterministic validation")
        if validation.validated_trade is None:
            raise ManagedPaperExecutionError("paper execution requires a canonical ValidatedTrade")
        if journal.portfolio_id != state.managed_portfolio.portfolio_id:
            raise ManagedPaperExecutionError("journal portfolio does not match the current managed portfolio")
        if any(item.decision_cycle_id == decision_cycle_id for item in state.executions):
            raise ManagedPaperExecutionError("decision cycle has already been executed")
        observation = self._latest_observation(state, validation.validated_trade.security, approval.decided_at, executed_at)
        try:
            execution = SimulatedExecutionWorkflow.execute(approval, state.managed_portfolio, observation, executed_at=executed_at)
        except (TypeError, ValueError) as error:
            raise ManagedPaperExecutionError(str(error)) from error
        managed_valuation = self._valuation(state, execution.updated_portfolio, observation, executed_at)
        history_entries = self._history_with_execution(state, journal, approval, execution)
        proposed = replace(
            state,
            managed_portfolio=execution.updated_portfolio,
            managed_history=state.managed_history.append(execution.updated_portfolio, managed_valuation),
            executions=(*state.executions, execution),
            history_entries=history_entries,
        )
        self._store.save_transition(proposed)
        # The reviewed benchmark lane owns benchmark valuations and fulfillment.
        # Without a new authoritative benchmark valuation, appending managed-only
        # history cannot form a truthful synchronized PerformanceComparison.
        return ManagedPaperExecutionResult(execution, comparison_refreshed=False)

    def _require_state(self) -> PersistedRunState:
        state = self._store.open_run()
        if state is None:
            raise ManagedPaperExecutionError("local SQLite run has not been initialized")
        return state

    @staticmethod
    def _one(items, predicate, name: str):
        matches = tuple(item for item in items if predicate(item))
        if not matches:
            raise ManagedPaperExecutionError(f"no matching {name} exists for decision cycle")
        if len(matches) != 1:
            raise ManagedPaperExecutionError(f"ambiguous matching {name} records for decision cycle")
        return matches[0]

    @staticmethod
    def _latest_observation(state, security, decided_at: datetime, executed_at: datetime) -> PriceObservation:
        candidates = tuple(
            item for item in state.price_observations
            if item.security == security and decided_at <= item.observed_at <= executed_at
        )
        if not candidates:
            raise ManagedPaperExecutionError("no eligible persisted PriceObservation exists for execution")
        latest_at = max(item.observed_at for item in candidates)
        latest = tuple(item for item in candidates if item.observed_at == latest_at)
        if len({item for item in latest}) != 1:
            raise ManagedPaperExecutionError("conflicting persisted PriceObservations share the latest timestamp")
        return latest[0]

    @staticmethod
    def _valuation(state, portfolio, observation: PriceObservation, executed_at: datetime) -> PortfolioValuation:
        securities = {position.security for position in portfolio.positions}
        observations = tuple(
            item for item in state.price_observations
            if item.security in securities
            and item.observed_at == observation.observed_at
            and item.market_date == observation.market_date
            and item.source_provider_identity == observation.source_provider_identity
            and item.price_convention == observation.price_convention
        )
        try:
            return PortfolioValuation.from_portfolio(
                portfolio, observations, as_of_timestamp=executed_at, market_date=observation.market_date,
                source_price_timestamp=observation.observed_at,
                source_provider_identity=observation.source_provider_identity,
                price_convention=observation.price_convention,
            )
        except (TypeError, ValueError) as error:
            raise ManagedPaperExecutionError(f"managed post-execution valuation requires synchronized observations: {error}") from error

    @staticmethod
    def _history_with_execution(state, journal, approval, execution):
        existing = tuple(item for item in state.history_entries if item.journal_entry.decision_cycle_id == journal.decision_cycle_id)
        artifact = DecisionHistoryArtifacts(journal, approval, execution.executed_trade)
        if not existing:
            return (*state.history_entries, artifact)
        if len(existing) != 1 or existing[0].journal_entry is not journal or existing[0].approval is not approval:
            raise ManagedPaperExecutionError("ambiguous or non-canonical decision history linkage")
        if existing[0].executed_trade is not None:
            raise ManagedPaperExecutionError("decision history already has an execution")
        return tuple(artifact if item is existing[0] else item for item in state.history_entries)
