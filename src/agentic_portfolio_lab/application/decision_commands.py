"""Durable commands for the managed pre-execution decision lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from agentic_portfolio_lab.dashboard import DecisionHistoryArtifacts
from agentic_portfolio_lab.domain.approval import ApprovalDecision, DecisionApproval
from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity, _require_aware_datetime
from agentic_portfolio_lab.domain.recommendations import RecommendationAction
from agentic_portfolio_lab.domain.research import MissingData, ResearchBatch, ResearchPacket
from agentic_portfolio_lab.domain.risk_validation import DeterministicRiskValidator
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.domain.value_manager import ValueManager, ValueManagerDecisionContext
from agentic_portfolio_lab.domain.value_manager_workflow import ValueManagerDecisionWorkflow

from .local_state import PersistedRunState
from .research_selection import latest_authoritative_research_batch


class DecisionCommandConflict(ValueError):
    """A requested immutable decision transition already exists or conflicts."""


@dataclass(frozen=True, slots=True)
class RunValueManagerResult:
    journal_entry: DecisionJournalEntry


class RunValueManagerService:
    """Run, validate, and journal exactly one persisted ResearchBatch cycle."""

    def __init__(self, store, *, manager: ValueManager) -> None:
        if not isinstance(manager, ValueManager) or not callable(getattr(manager, "decide", None)):
            raise TypeError("manager must implement ValueManager")
        self._store = store
        self._workflow = ValueManagerDecisionWorkflow(manager)
        self._validator = DeterministicRiskValidator()

    def run(self, *, occurred_at: datetime) -> RunValueManagerResult:
        occurred_at = _require_aware_datetime(occurred_at, field_name="occurred_at")
        state = _require_state(self._store)
        batch = latest_authoritative_research_batch(state.research_batches)
        if any(journal.decision_cycle_id == batch.decision_cycle_id for journal in state.journal_entries):
            raise DecisionCommandConflict("a journal already exists for the authoritative ResearchBatch decision_cycle_id")
        context = ValueManagerDecisionContext(
            portfolio=state.managed_portfolio,
            research_batch=batch,
            constitution=ConstitutionLoader.load_value_manager_constitution(),
        )
        decision_result = self._workflow.run(context, produced_at=occurred_at)
        observation = _eligible_buy_observation(state, decision_result.recommendation, batch, occurred_at)
        validation = self._validator.validate(
            decision_result,
            validation_timestamp=occurred_at,
            price_observation=observation,
        )
        # Reviewer output is truthfully absent until a real reviewer adapter is
        # supplied; deterministic validation is never presented as AI review.
        journal = DecisionJournalEntry(
            decision_result=decision_result,
            risk_validation_result=validation,
            journaled_at=occurred_at,
            reviewer_result=None,
        )
        self._store.save_transition(replace(state, journal_entries=(*state.journal_entries, journal)))
        return RunValueManagerResult(journal)


class DecisionApprovalService:
    """Append one immutable human outcome over a canonical persisted journal."""

    def __init__(self, store) -> None:
        self._store = store

    def decide(
        self,
        *,
        decision_cycle_id: UUID,
        decision: ApprovalDecision,
        decision_maker_id: str,
        decided_at: datetime,
        comment: str | None = None,
    ) -> DecisionApproval:
        if not isinstance(decision_cycle_id, UUID):
            raise TypeError("decision_cycle_id must be a UUID")
        if not isinstance(decision, ApprovalDecision):
            raise TypeError("decision must be an ApprovalDecision")
        state = _require_state(self._store)
        journal = next((item for item in state.journal_entries if item.decision_cycle_id == decision_cycle_id), None)
        if journal is None:
            raise ValueError("no canonical persisted journal exists for decision_cycle_id")
        existing = next((item for item in state.approvals if item.decision_cycle_id == decision_cycle_id), None)
        if existing is not None:
            raise DecisionCommandConflict(f"decision_cycle_id already has immutable {existing.decision.value} outcome")
        approval = DecisionApproval(
            journal_entry=journal,
            decision_maker_id=decision_maker_id,
            decision=decision,
            decided_at=decided_at,
            comment=comment,
        )
        entry = DecisionHistoryArtifacts(journal_entry=journal, approval=approval, executed_trade=None)
        self._store.save_transition(
            replace(
                state,
                approvals=(*state.approvals, approval),
                history_entries=(*state.history_entries, entry),
            )
        )
        return approval


def _require_state(store) -> PersistedRunState:
    state = store.open_run()
    if state is None:
        raise ValueError("local SQLite run has not been initialized")
    return state


def _packet_security(packet: ResearchPacket) -> SecurityIdentity | None:
    if isinstance(packet.exchange, MissingData) or isinstance(packet.currency, MissingData):
        return None
    return SecurityIdentity(packet.ticker, packet.security_type, packet.exchange, packet.currency)


def _eligible_buy_observation(
    state: PersistedRunState,
    recommendation,
    batch: ResearchBatch,
    occurred_at: datetime,
) -> PriceObservation | None:
    if recommendation.action is RecommendationAction.HOLD:
        return None
    assert recommendation.ticker is not None
    packets = tuple(packet for packet in batch.packets if packet.ticker == recommendation.ticker)
    if len(packets) != 1:
        raise ValueError("BUY recommendation must identify exactly one authoritative research packet")
    security = _packet_security(packets[0])
    if security is None:
        return None
    candidates = tuple(
        observation for observation in state.price_observations
        if observation.security == security
        and observation.currency == state.managed_portfolio.base_currency
        and observation.observed_at <= occurred_at
        and observation.market_date <= occurred_at.date()
    )
    if not candidates:
        return None
    latest_at = max(observation.observed_at for observation in candidates)
    latest = tuple(observation for observation in candidates if observation.observed_at == latest_at)
    if len(latest) != 1:
        raise ValueError("latest eligible PriceObservation is ambiguous")
    return latest[0]
