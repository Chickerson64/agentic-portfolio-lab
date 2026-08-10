"""Tests for immutable decision-cycle audit linkage."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
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
from agentic_portfolio_lab.domain.risk_validation import DeterministicRiskValidator, RiskValidationResult
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.domain.value_manager import ValueManagerDecisionContext
from agentic_portfolio_lab.domain.value_manager_workflow import ValueManagerDecisionResult


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


def _evidence(evidence_id: str = "ev_aapl_001") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_type="FILING",
        source_title="Quarterly Report",
        source_date=date(2026, 8, 9),
        claim_supported="Operating cash flow remained positive.",
    )


def _packet() -> ResearchPacket:
    evidence = _evidence()
    return ResearchPacket(
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


def _decision_result(portfolio: Portfolio, *, action: str = "BUY") -> ValueManagerDecisionResult:
    evidence = _evidence()
    batch = ResearchBatch(
        batch_id="batch_001",
        decision_cycle_id=uuid4(),
        portfolio_id=portfolio.portfolio_id,
        manager_type="VALUE",
        created_at=CREATED_AT,
        as_of_timestamp=datetime(2026, 8, 10, 12, tzinfo=UTC),
        packets=(_packet(),),
    )
    context = ValueManagerDecisionContext(
        portfolio=portfolio,
        research_batch=batch,
        constitution=ConstitutionLoader.load_value_manager_constitution(),
    )
    recommendation = PortfolioRecommendation(
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
                evidence_id=evidence.evidence_id,
                source_type=evidence.source_type,
                source_title=evidence.source_title,
                source_date=evidence.source_date,
                claim_supported="The filing supports positive operating cash flow.",
            ),
        ),
        why_not_spy="This evidence-backed opportunity is more compelling than incremental SPY exposure.",
        thesis_invalidation=("Cash generation deteriorates materially.",) if action == "BUY" else (),
        review_triggers=(ReviewTrigger("EVENT_BASED", "Review after a material earnings miss."),),
    )
    return ValueManagerDecisionResult(context=context, recommendation=recommendation, produced_at=PRODUCED_AT)


def _risk_result(decision_result: ValueManagerDecisionResult) -> RiskValidationResult:
    if decision_result.recommendation.action.value == "HOLD":
        return DeterministicRiskValidator().validate(decision_result, validation_timestamp=VALIDATED_AT)
    security = SecurityIdentity(ticker="AAPL", security_type="EQUITY", exchange="NASDAQ", currency="USD")
    observation = PriceObservation(
        security=security,
        observed_price=Decimal("100"),
        market_date=VALIDATED_AT.date(),
        observed_at=VALIDATED_AT,
        currency="USD",
        source_provider_identity="test-provider",
        price_convention="regular-session-close",
    )
    return DeterministicRiskValidator().validate(
        decision_result,
        validation_timestamp=VALIDATED_AT,
        price_observation=observation,
    )


def _reviewer_result(
    decision_result: ValueManagerDecisionResult,
    risk_result: RiskValidationResult,
    *,
    decision: ReviewDecision = ReviewDecision.APPROVE,
) -> ReviewerResult:
    context = AIReviewerReviewContext(
        decision_result=decision_result,
        risk_validation_result=risk_result,
        constitution=decision_result.context.constitution,
    )
    findings = ()
    if decision is ReviewDecision.REQUEST_CHANGES:
        findings = (
            ReviewFinding(
                severity="WARNING",
                category="EVIDENCE_USAGE",
                message="Clarify the downside case.",
                related_evidence_ids=("ev_aapl_001",),
                related_recommendation_field="risks",
            ),
        )
    return ReviewerResult(context=context, decision=decision, findings=findings, reviewed_at=REVIEWED_AT)


def test_valid_hold_entry_preserves_references_without_a_reviewer() -> None:
    decision = _decision_result(_portfolio(), action="HOLD")
    risk = _risk_result(decision)

    entry = DecisionJournalEntry(
        decision_result=decision,
        risk_validation_result=risk,
        journaled_at=JOURNALED_AT,
    )

    assert entry.decision_cycle_id == decision.decision_cycle_id
    assert entry.portfolio_id == decision.portfolio_id
    assert entry.manager_type == "VALUE"
    assert entry.constitution_version == "value-v1.0.0"
    assert entry.research_batch_id == "batch_001"
    assert entry.research_packet_ids == ("packet_aapl",)
    assert entry.cited_evidence_ids == ("ev_aapl_001",)
    assert entry.reviewer_evidence_ids == ()
    assert entry.reviewer_result is None


def test_failed_deterministic_validation_can_be_journaled_without_a_reviewer() -> None:
    decision = _decision_result(_portfolio())
    failed_risk = DeterministicRiskValidator().validate(
        decision,
        validation_timestamp=VALIDATED_AT,
    )

    entry = DecisionJournalEntry(
        decision_result=decision,
        risk_validation_result=failed_risk,
        journaled_at=JOURNALED_AT,
    )

    assert not entry.risk_validation_result.passed
    assert entry.reviewer_result is None


def test_failed_deterministic_validation_cannot_be_journaled_with_a_reviewer() -> None:
    decision = _decision_result(_portfolio())
    failed_risk = DeterministicRiskValidator().validate(
        decision,
        validation_timestamp=VALIDATED_AT,
    )

    with pytest.raises(ValueError, match="must have passed"):
        AIReviewerReviewContext(
            decision_result=decision,
            risk_validation_result=failed_risk,
            constitution=decision.context.constitution,
        )

    passed_risk = _risk_result(decision)
    reviewer = _reviewer_result(decision, passed_risk)
    with pytest.raises(ValueError, match="risk_validation_result"):
        DecisionJournalEntry(
            decision_result=decision,
            risk_validation_result=failed_risk,
            reviewer_result=reviewer,
            journaled_at=JOURNALED_AT,
        )


def test_passed_hold_entry_can_preserve_a_reviewer_result() -> None:
    decision = _decision_result(_portfolio(), action="HOLD")
    risk = _risk_result(decision)
    reviewer = _reviewer_result(decision, risk)

    entry = DecisionJournalEntry(
        decision_result=decision,
        risk_validation_result=risk,
        reviewer_result=reviewer,
        journaled_at=JOURNALED_AT,
    )

    assert entry.risk_validation_result.passed
    assert entry.reviewer_result is reviewer


def test_valid_buy_entries_support_approve_and_request_changes() -> None:
    decision = _decision_result(_portfolio())
    risk = _risk_result(decision)

    approved = DecisionJournalEntry(
        decision_result=decision,
        risk_validation_result=risk,
        reviewer_result=_reviewer_result(decision, risk),
        journaled_at=JOURNALED_AT,
    )
    requested_changes = DecisionJournalEntry(
        decision_result=decision,
        risk_validation_result=risk,
        reviewer_result=_reviewer_result(decision, risk, decision=ReviewDecision.REQUEST_CHANGES),
        journaled_at=JOURNALED_AT,
    )

    assert approved.reviewer_result is not None
    assert approved.reviewer_result.decision is ReviewDecision.APPROVE
    assert requested_changes.reviewer_result is not None
    assert requested_changes.reviewer_result.decision is ReviewDecision.REQUEST_CHANGES
    assert requested_changes.reviewer_evidence_ids == ("ev_aapl_001",)


def test_journal_rejects_decision_cycle_and_portfolio_mismatches() -> None:
    portfolio = _portfolio()
    decision = _decision_result(portfolio)
    risk = _risk_result(decision)
    other_cycle_risk = _risk_result(_decision_result(portfolio))
    other_portfolio_decision = _decision_result(_portfolio())
    other_portfolio_risk = _risk_result(other_portfolio_decision)

    with pytest.raises(ValueError, match="risk_validation_result must belong"):
        DecisionJournalEntry(decision, other_cycle_risk, JOURNALED_AT)
    with pytest.raises(ValueError, match="risk_validation_result must belong"):
        DecisionJournalEntry(decision, other_portfolio_risk, JOURNALED_AT)


def test_journal_rejects_an_unrelated_reviewer_artifact() -> None:
    decision = _decision_result(_portfolio())
    risk = _risk_result(decision)
    other_decision = _decision_result(_portfolio())
    other_risk = _risk_result(other_decision)

    with pytest.raises(ValueError, match="reviewer_result must belong to decision_result"):
        DecisionJournalEntry(
            decision,
            risk,
            JOURNALED_AT,
            reviewer_result=_reviewer_result(other_decision, other_risk),
        )


def test_journal_timestamp_is_aware_and_after_every_included_artifact() -> None:
    decision = _decision_result(_portfolio())
    risk = _risk_result(decision)
    reviewer = _reviewer_result(decision, risk)

    assert DecisionJournalEntry(decision, risk, REVIEWED_AT, reviewer_result=reviewer).journaled_at == REVIEWED_AT
    with pytest.raises(ValueError, match="timezone-aware"):
        DecisionJournalEntry(decision, risk, JOURNALED_AT.replace(tzinfo=None))
    with pytest.raises(ValueError, match="latest included"):
        DecisionJournalEntry(decision, risk, REVIEWED_AT - timedelta(seconds=1), reviewer_result=reviewer)


def test_no_review_journal_uses_validation_timestamp_as_its_chronology_boundary() -> None:
    decision = _decision_result(_portfolio())
    risk = _risk_result(decision)

    assert DecisionJournalEntry(
        decision_result=decision,
        risk_validation_result=risk,
        journaled_at=risk.validation_timestamp,
    ).journaled_at == risk.validation_timestamp
    with pytest.raises(ValueError, match="latest included"):
        DecisionJournalEntry(
            decision_result=decision,
            risk_validation_result=risk,
            journaled_at=risk.validation_timestamp - timedelta(seconds=1),
        )


def test_journal_is_immutable_and_does_not_duplicate_raw_research_content() -> None:
    decision = _decision_result(_portfolio())
    risk = _risk_result(decision)
    entry = DecisionJournalEntry(decision, risk, JOURNALED_AT)

    with pytest.raises(FrozenInstanceError):
        entry.journaled_at = JOURNALED_AT + timedelta(seconds=1)  # type: ignore[misc]
    assert {field.name for field in fields(DecisionJournalEntry)} == {
        "decision_result",
        "risk_validation_result",
        "journaled_at",
        "reviewer_result",
    }
    assert "sections" not in {field.name for field in fields(DecisionJournalEntry)}
    assert "evidence_items" not in {field.name for field in fields(DecisionJournalEntry)}
