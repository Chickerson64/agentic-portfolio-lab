"""Tests for deterministic composition of the pre-approval decision cycle."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.decision_cycle import (
    DecisionCycleOrchestrator,
    DecisionCycleResult,
    DecisionCycleStage,
)
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio, SecurityIdentity
from agentic_portfolio_lab.domain.recommendations import (
    PortfolioRecommendation,
    RecommendationEvidenceReference,
    ReviewTrigger,
)
from agentic_portfolio_lab.domain.research import EvidenceItem, ResearchBatch, ResearchPacket, ResearchSection
from agentic_portfolio_lab.domain.reviewer import (
    AIReviewerReviewContext,
    ReviewDecision,
    ReviewFinding,
    ReviewerResult,
)
from agentic_portfolio_lab.domain.risk_validation import DeterministicRiskValidator
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.domain.value_manager import ValueManagerDecisionContext
from agentic_portfolio_lab.domain.value_manager_workflow import ValueManagerDecisionWorkflow


UTC = timezone.utc
CREATED_AT = datetime(2026, 8, 10, 13, tzinfo=UTC)
PRODUCED_AT = datetime(2026, 8, 10, 14, tzinfo=UTC)
VALIDATED_AT = datetime(2026, 8, 10, 15, tzinfo=UTC)
REVIEWED_AT = datetime(2026, 8, 10, 16, tzinfo=UTC)
JOURNALED_AT = datetime(2026, 8, 10, 17, tzinfo=UTC)


def _portfolio() -> Portfolio:
    return Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Value Portfolio",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance(currency="USD", amount=Decimal("1000")),
        created_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
    )


def _context(portfolio: Portfolio) -> ValueManagerDecisionContext:
    evidence = EvidenceItem(
        evidence_id="ev_aapl_001",
        source_type="FILING",
        source_title="Quarterly Report",
        source_date=date(2026, 8, 9),
        claim_supported="Operating cash flow remained positive.",
    )
    packet = ResearchPacket(
        packet_id="packet_aapl",
        candidate_id="candidate_aapl",
        ticker="AAPL",
        security_type="EQUITY",
        exchange="NASDAQ",
        currency="USD",
        as_of_timestamp=datetime(2026, 8, 10, 12, tzinfo=UTC),
        evidence_items=(evidence,),
        sections=(
            ResearchSection(
                section_id="BUSINESS_OVERVIEW",
                content="The company sells devices and services.",
                evidence_ids=(evidence.evidence_id,),
            ),
        ),
    )
    batch = ResearchBatch(
        batch_id="batch_001",
        decision_cycle_id=uuid4(),
        portfolio_id=portfolio.portfolio_id,
        manager_type="VALUE",
        created_at=CREATED_AT,
        as_of_timestamp=datetime(2026, 8, 10, 12, tzinfo=UTC),
        packets=(packet,),
    )
    return ValueManagerDecisionContext(
        portfolio=portfolio,
        research_batch=batch,
        constitution=ConstitutionLoader.load_value_manager_constitution(),
    )


def _recommendation(action: str = "BUY") -> PortfolioRecommendation:
    return PortfolioRecommendation(
        action=action,
        ticker="AAPL" if action == "BUY" else None,
        target_weight=Decimal("0.10") if action == "BUY" else None,
        decision_rationale="The supplied evidence supports this decision.",
        investment_thesis="Durable cash generation can compound." if action == "BUY" else None,
        valuation="The valuation is reasonable relative to cash generation.",
        risks=("Demand could weaken.",),
        confidence_score=72,
        evidence=(
            RecommendationEvidenceReference(
                evidence_id="ev_aapl_001",
                source_type="FILING",
                source_title="Quarterly Report",
                source_date=date(2026, 8, 9),
                claim_supported="The filing supports positive operating cash flow.",
            ),
        ),
        why_not_spy="This evidence-backed opportunity is more compelling than incremental SPY exposure.",
        thesis_invalidation=("Cash generation deteriorates materially.",) if action == "BUY" else (),
        review_triggers=(ReviewTrigger("EVENT_BASED", "Review after a material earnings miss."),),
    )


def _price() -> PriceObservation:
    return PriceObservation(
        security=SecurityIdentity(ticker="AAPL", security_type="EQUITY", exchange="NASDAQ", currency="USD"),
        observed_price=Decimal("100"),
        market_date=VALIDATED_AT.date(),
        observed_at=VALIDATED_AT,
        currency="USD",
        source_provider_identity="test-provider",
        price_convention="regular-session-close",
    )


class StubManager:
    def __init__(self, recommendation: PortfolioRecommendation) -> None:
        self.recommendation = recommendation
        self.calls = 0

    def decide(self, context: ValueManagerDecisionContext) -> PortfolioRecommendation:
        self.calls += 1
        return self.recommendation


class StubReviewer:
    def __init__(self, decision: ReviewDecision = ReviewDecision.APPROVE) -> None:
        self.decision = decision
        self.calls = 0

    def review(self, context: AIReviewerReviewContext) -> ReviewerResult:
        self.calls += 1
        findings = ()
        if self.decision is ReviewDecision.REQUEST_CHANGES:
            findings = (
                ReviewFinding(
                    severity="WARNING",
                    category="EVIDENCE_USAGE",
                    message="Clarify the downside case.",
                    related_evidence_ids=("ev_aapl_001",),
                ),
            )
        return ReviewerResult(context=context, decision=self.decision, findings=findings, reviewed_at=REVIEWED_AT)


def _orchestrator(recommendation: PortfolioRecommendation, reviewer: StubReviewer | None = None) -> tuple[DecisionCycleOrchestrator, StubManager, StubReviewer]:
    manager = StubManager(recommendation)
    reviewer = reviewer or StubReviewer()
    return (
        DecisionCycleOrchestrator(
            decision_workflow=ValueManagerDecisionWorkflow(manager),
            risk_validator=DeterministicRiskValidator(),
            reviewer=reviewer,
        ),
        manager,
        reviewer,
    )


def test_successful_buy_runs_full_pre_approval_cycle_once() -> None:
    orchestrator, manager, reviewer = _orchestrator(_recommendation())
    portfolio = _portfolio()

    result = orchestrator.run(
        _context(portfolio),
        produced_at=PRODUCED_AT,
        validation_timestamp=VALIDATED_AT,
        reviewed_at=REVIEWED_AT,
        journaled_at=JOURNALED_AT,
        price_observation=_price(),
    )

    assert result.stage is DecisionCycleStage.REVIEWED
    assert result.deterministic_validation_passed
    assert result.qualitative_review_occurred
    assert result.journal_entry.risk_validation_result.validated_trade is not None
    assert result.journal_entry.reviewer_result is not None
    assert manager.calls == 1
    assert reviewer.calls == 1
    assert portfolio.cash_balance.amount == Decimal("1000")
    assert portfolio.positions == ()


def test_successful_hold_is_reviewed_without_price_or_trade() -> None:
    orchestrator, manager, reviewer = _orchestrator(_recommendation("HOLD"))

    result = orchestrator.run(
        _context(_portfolio()),
        produced_at=PRODUCED_AT,
        validation_timestamp=VALIDATED_AT,
        reviewed_at=REVIEWED_AT,
        journaled_at=JOURNALED_AT,
    )

    assert result.stage is DecisionCycleStage.REVIEWED
    assert result.journal_entry.risk_validation_result.validated_trade is None
    assert manager.calls == 1
    assert reviewer.calls == 1


def test_failed_buy_stops_and_journals_without_reviewer() -> None:
    orchestrator, manager, reviewer = _orchestrator(_recommendation())

    result = orchestrator.run(
        _context(_portfolio()),
        produced_at=PRODUCED_AT,
        validation_timestamp=VALIDATED_AT,
        journaled_at=JOURNALED_AT,
    )

    assert result.stage is DecisionCycleStage.STOPPED_AT_RISK_VALIDATION
    assert not result.deterministic_validation_passed
    assert not result.qualitative_review_occurred
    assert result.journal_entry.reviewer_result is None
    assert manager.calls == 1
    assert reviewer.calls == 0


@pytest.mark.parametrize("decision", [ReviewDecision.APPROVE, ReviewDecision.REQUEST_CHANGES])
def test_reviewer_outcomes_are_journaled_without_retry(decision: ReviewDecision) -> None:
    reviewer = StubReviewer(decision)
    orchestrator, manager, returned_reviewer = _orchestrator(_recommendation(), reviewer)

    result = orchestrator.run(
        _context(_portfolio()),
        produced_at=PRODUCED_AT,
        validation_timestamp=VALIDATED_AT,
        reviewed_at=REVIEWED_AT,
        journaled_at=JOURNALED_AT,
        price_observation=_price(),
    )

    assert result.journal_entry.reviewer_result is not None
    assert result.journal_entry.reviewer_result.decision is decision
    assert manager.calls == 1
    assert returned_reviewer.calls == 1


def test_reviewed_path_requires_matching_caller_supplied_review_timestamp() -> None:
    orchestrator, _, _ = _orchestrator(_recommendation())

    with pytest.raises(ValueError, match="reviewed_at"):
        orchestrator.run(
            _context(_portfolio()),
            produced_at=PRODUCED_AT,
            validation_timestamp=VALIDATED_AT,
            reviewed_at=REVIEWED_AT + timedelta(seconds=1),
            journaled_at=JOURNALED_AT,
            price_observation=_price(),
        )


def test_existing_timestamp_invariants_reject_invalid_chronology() -> None:
    orchestrator, _, _ = _orchestrator(_recommendation("HOLD"))

    with pytest.raises(ValueError, match="validation_timestamp"):
        orchestrator.run(
            _context(_portfolio()),
            produced_at=PRODUCED_AT,
            validation_timestamp=PRODUCED_AT - timedelta(seconds=1),
            journaled_at=JOURNALED_AT,
        )

    with pytest.raises(ValueError, match="journaled_at"):
        orchestrator.run(
            _context(_portfolio()),
            produced_at=PRODUCED_AT,
            validation_timestamp=VALIDATED_AT,
            reviewed_at=REVIEWED_AT,
            journaled_at=REVIEWED_AT - timedelta(seconds=1),
        )


def test_result_is_immutable_and_rejects_impossible_stage_combinations() -> None:
    orchestrator, _, _ = _orchestrator(_recommendation())
    reviewed = orchestrator.run(
        _context(_portfolio()),
        produced_at=PRODUCED_AT,
        validation_timestamp=VALIDATED_AT,
        reviewed_at=REVIEWED_AT,
        journaled_at=JOURNALED_AT,
        price_observation=_price(),
    )

    with pytest.raises(FrozenInstanceError):
        reviewed.stage = DecisionCycleStage.STOPPED_AT_RISK_VALIDATION  # type: ignore[misc]
    with pytest.raises(ValueError, match="STOPPED_AT_RISK_VALIDATION"):
        DecisionCycleResult(
            journal_entry=reviewed.journal_entry,
            stage=DecisionCycleStage.STOPPED_AT_RISK_VALIDATION,
        )

    prohibited = {"approval", "execution", "executed_trade", "portfolio", "cash", "shares"}
    assert {field.name for field in fields(DecisionCycleResult)}.isdisjoint(prohibited)
