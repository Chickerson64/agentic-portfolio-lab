"""Durable commands for the managed pre-execution decision lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID, uuid4

from agentic_portfolio_lab.dashboard import DecisionHistoryArtifacts
from agentic_portfolio_lab.domain.approval import ApprovalDecision, DecisionApproval
from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
from agentic_portfolio_lab.domain.policy import CurrentPolicyReference, EvidenceCoverageAssessment, RiskEvaluationSnapshot
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity, _require_aware_datetime
from agentic_portfolio_lab.domain.recommendations import RecommendationAction
from agentic_portfolio_lab.domain.research import MissingData, ResearchBatch, ResearchPacket
from agentic_portfolio_lab.domain.risk_validation import TwoLayerRiskEvaluator
from agentic_portfolio_lab.domain.reviewer import AIReviewer, AIReviewerReviewContext, ReviewerResult
from agentic_portfolio_lab.domain.valuation import PortfolioValuation, PriceObservation
from agentic_portfolio_lab.domain.value_manager import ValueManager, ValueManagerDecisionContext
from agentic_portfolio_lab.domain.value_manager_workflow import ValueManagerDecisionWorkflow

from .local_state import PersistedRunState
from .research_selection import latest_authoritative_research_batch
from .active_policy import load_active_value_policy


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
        self._evaluator = TwoLayerRiskEvaluator()

    def run(self, *, occurred_at: datetime) -> RunValueManagerResult:
        occurred_at = _require_aware_datetime(occurred_at, field_name="occurred_at")
        state = _require_state(self._store)
        batch = latest_authoritative_research_batch(state.research_batches)
        if any(journal.decision_cycle_id == batch.decision_cycle_id for journal in state.journal_entries):
            raise DecisionCommandConflict("a journal already exists for the authoritative ResearchBatch decision_cycle_id")
        policy = load_active_value_policy()
        context = ValueManagerDecisionContext(
            portfolio=state.managed_portfolio,
            research_batch=batch,
            constitution=ConstitutionLoader.load_value_manager_constitution_v2(),
            manager_risk_constitution=policy.manager_risk_constitution,
        )
        decision_result = self._workflow.run(context, produced_at=occurred_at)
        observation = _eligible_buy_observation(state, decision_result.recommendation, batch, occurred_at)
        snapshot = _risk_snapshot(state, decision_result, observation, policy, occurred_at)
        evaluation = self._evaluator.evaluate(
            decision_result,
            validation_timestamp=occurred_at,
            price_observation=observation,
            system_safety_envelope=policy.system_safety_envelope,
            manager_risk_constitution=(
                policy.manager_risk_constitution
                if snapshot is not None or decision_result.recommendation.action is RecommendationAction.HOLD
                else None
            ),
            risk_evaluation_snapshot=snapshot,
        )
        # Reviewer output is truthfully absent until a real reviewer adapter is
        # supplied; deterministic validation is never presented as AI review.
        journal = DecisionJournalEntry(
            decision_result=decision_result,
            risk_validation_result=evaluation.safety_validation,
            journaled_at=occurred_at,
            reviewer_result=None,
            policy_reference=policy,
            two_layer_evaluation=evaluation,
        )
        self._store.save_transition(replace(state, journal_entries=(*state.journal_entries, journal)))
        return RunValueManagerResult(journal)


@dataclass(frozen=True, slots=True)
class ReviewDecisionResult:
    reviewer_result: ReviewerResult


class ReviewDecisionService:
    """Append one advisory AI review to an exact, already-journaled decision."""

    def __init__(self, store, *, reviewer: AIReviewer) -> None:
        if not isinstance(reviewer, AIReviewer) or not callable(getattr(reviewer, "review", None)):
            raise TypeError("reviewer must implement AIReviewer")
        self._store = store
        self._reviewer = reviewer

    def review(self, *, decision_cycle_id: UUID) -> ReviewDecisionResult:
        if not isinstance(decision_cycle_id, UUID):
            raise TypeError("decision_cycle_id must be a UUID")
        state = _require_state(self._store)
        journal = next((item for item in state.journal_entries if item.decision_cycle_id == decision_cycle_id), None)
        if journal is None:
            raise ValueError("no canonical persisted journal exists for decision_cycle_id")
        if not journal.risk_validation_result.passed:
            raise DecisionCommandConflict("System Safety must pass before AI review")
        if journal.two_layer_evaluation is None or journal.two_layer_evaluation.manager_assessment is None:
            raise DecisionCommandConflict("current Manager Risk assessment is required before AI review")
        if not isinstance(journal.policy_reference, CurrentPolicyReference):
            raise DecisionCommandConflict("current policy lineage is required before AI review")
        if any(item.decision_cycle_id == decision_cycle_id for item in state.reviewer_results):
            raise DecisionCommandConflict("decision_cycle_id already has an immutable reviewer result")
        context = AIReviewerReviewContext(
            decision_result=journal.decision_result,
            risk_validation_result=journal.risk_validation_result,
            constitution=journal.decision_result.context.constitution,
            policy_reference=journal.policy_reference,
            manager_assessment=journal.two_layer_evaluation.manager_assessment,
        )
        result = self._reviewer.review(context)
        if not isinstance(result, ReviewerResult):
            raise TypeError("reviewer must return a ReviewerResult")
        if result.context != context:
            raise ValueError("reviewer result must retain the exact supplied decision lineage")
        if result.metadata is None:
            raise ValueError("production reviewer result requires reviewer metadata")
        self._store.save_transition(replace(state, reviewer_results=(*state.reviewer_results, result)))
        return ReviewDecisionResult(result)


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


class ReviseDecisionCycleService:
    """Create one explicit, immutable next cycle from a terminal decision."""

    def __init__(self, store) -> None:
        self._store = store

    def create(self, *, decision_cycle_id: UUID, occurred_at: datetime) -> ResearchBatch:
        occurred_at = _require_aware_datetime(occurred_at, field_name="occurred_at")
        state = _require_state(self._store)
        original = next((item for item in state.journal_entries if item.decision_cycle_id == decision_cycle_id), None)
        if original is None:
            raise ValueError("no canonical persisted journal exists for decision_cycle_id")
        approval = next((item for item in state.approvals if item.decision_cycle_id == decision_cycle_id), None)
        if approval is None or approval.decision is not ApprovalDecision.REJECTED:
            raise DecisionCommandConflict("only a terminal non-executable rejected decision may be revised")
        if any(item.decision_cycle_id == decision_cycle_id for item in state.executions):
            raise DecisionCommandConflict("an executed decision cycle may not be revised")
        if occurred_at <= max(original.journaled_at, approval.decided_at):
            raise ValueError("revision occurred_at must be after the predecessor terminal chronology")
        if any(item.revision_of_decision_cycle_id == decision_cycle_id for item in state.research_batches):
            raise DecisionCommandConflict("decision_cycle_id already has a direct revision child")
        source = next(item for item in state.research_batches if item.batch_id == original.research_batch_id)
        revised = replace(
            source, batch_id=f"revision-{uuid4()}", decision_cycle_id=uuid4(), created_at=occurred_at,
            revision_of_decision_cycle_id=decision_cycle_id,
        )
        self._store.save_transition(replace(state, research_batches=(*state.research_batches, revised)))
        return revised


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


def _risk_snapshot(state, decision_result, observation, policy, occurred_at):
    """Build the exact advisory input after the single manager proposal exists."""
    if decision_result.recommendation.action is RecommendationAction.HOLD:
        return None
    if observation is None:
        return None
    packet = next(packet for packet in decision_result.context.research_batch.packets if packet.ticker == decision_result.recommendation.ticker)
    coverage = EvidenceCoverageAssessment.evaluate(
        packet, security=observation.security, band_definitions=policy.manager_risk_constitution.evidence_bands
    )
    valuation = PortfolioValuation.from_portfolio(
        state.managed_portfolio,
        tuple(
            item for item in state.price_observations
            if item.security in {position.security for position in state.managed_portfolio.positions}
            and item.observed_at == observation.observed_at
            and item.market_date == observation.market_date
            and item.source_provider_identity == observation.source_provider_identity
            and item.price_convention == observation.price_convention
        ),
        as_of_timestamp=occurred_at, market_date=observation.market_date,
        source_price_timestamp=observation.observed_at, source_provider_identity=observation.source_provider_identity,
        price_convention=observation.price_convention,
    )
    return RiskEvaluationSnapshot.from_state(
        portfolio=state.managed_portfolio, valuation=valuation, security=observation.security,
        price_observation=observation, evidence_coverage=coverage,
        proposed_target_weight=decision_result.recommendation.target_weight,
    )
