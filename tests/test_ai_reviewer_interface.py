"""Tests for the framework-independent AI reviewer boundary."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio, SecurityIdentity
from agentic_portfolio_lab.domain.recommendations import (
    PortfolioRecommendation,
    RecommendationEvidenceReference,
    ReviewTrigger,
)
from agentic_portfolio_lab.domain.research import EvidenceItem, ResearchBatch, ResearchPacket, ResearchSection
from agentic_portfolio_lab.domain.reviewer import (
    AIReviewer,
    AIReviewerReviewContext,
    ReviewDecision,
    ReviewFinding,
    ReviewFindingCategory,
    ReviewFindingSeverity,
    ReviewerResult,
)
from agentic_portfolio_lab.domain.risk_validation import (
    DeterministicRiskValidator,
    RiskRuleResult,
    RiskValidationResult,
    RiskValidationStatus,
)
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.domain.value_manager import ValueManagerDecisionContext
from agentic_portfolio_lab.domain.value_manager_workflow import ValueManagerDecisionResult


UTC = timezone.utc
CREATED_AT = datetime(2026, 8, 10, 13, tzinfo=UTC)
VALIDATED_AT = datetime(2026, 8, 10, 14, tzinfo=UTC)
REVIEWED_AT = datetime(2026, 8, 10, 15, tzinfo=UTC)


def _portfolio() -> Portfolio:
    return Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Value Portfolio",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance(currency="USD", amount=Decimal("1000")),
        created_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
    )


def _evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev_aapl_001",
        source_type="FILING",
        source_title="Quarterly Report",
        source_date=date(2026, 8, 9),
        claim_supported="Operating cash flow remained positive.",
    )


def _decision_result(portfolio: Portfolio, *, action: str = "BUY") -> ValueManagerDecisionResult:
    evidence = _evidence()
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
    context = ValueManagerDecisionContext(
        portfolio=portfolio,
        research_batch=batch,
        constitution=ConstitutionLoader.load_value_manager_constitution(),
    )
    recommendation = PortfolioRecommendation(
        action=action,
        ticker="AAPL" if action == "BUY" else None,
        target_weight=Decimal("0.10") if action == "BUY" else None,
        decision_rationale="The evidence supports a durable, attractive business.",
        investment_thesis="Cash generation can compound over time." if action == "BUY" else None,
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
    return ValueManagerDecisionResult(context=context, recommendation=recommendation, produced_at=CREATED_AT)


def _price_observation() -> PriceObservation:
    return PriceObservation(
        security=SecurityIdentity(ticker="AAPL", security_type="EQUITY", exchange="NASDAQ", currency="USD"),
        observed_price=Decimal("100"),
        market_date=VALIDATED_AT.date(),
        observed_at=VALIDATED_AT,
        currency="USD",
        source_provider_identity="test-provider",
        price_convention="regular-session-close",
    )


def _review_context(*, action: str = "BUY") -> AIReviewerReviewContext:
    decision_result = _decision_result(_portfolio(), action=action)
    risk_validation_result = DeterministicRiskValidator().validate(
        decision_result,
        validation_timestamp=VALIDATED_AT,
        price_observation=_price_observation() if action == "BUY" else None,
    )
    return AIReviewerReviewContext(
        decision_result=decision_result,
        risk_validation_result=risk_validation_result,
        constitution=decision_result.context.constitution,
    )


def _finding(**overrides: object) -> ReviewFinding:
    fields = {
        "severity": "WARNING",
        "category": "EVIDENCE_USAGE",
        "message": "Explain the relationship between the cited evidence and the valuation.",
        "related_evidence_ids": ("ev_aapl_001",),
        "related_recommendation_field": "valuation",
    }
    fields.update(overrides)
    return ReviewFinding(**fields)  # type: ignore[arg-type]


class StubReviewer:
    def __init__(self, result: ReviewerResult) -> None:
        self.result = result
        self.calls = 0

    def review(self, context: AIReviewerReviewContext) -> ReviewerResult:
        self.calls += 1
        assert context is self.result.context
        return self.result


def test_stub_reviewer_satisfies_protocol_and_returns_one_result() -> None:
    context = _review_context()
    expected = ReviewerResult(context=context, decision="APPROVE", findings=(), reviewed_at=REVIEWED_AT)
    reviewer = StubReviewer(expected)

    assert isinstance(reviewer, AIReviewer)
    assert reviewer.review(context) is expected
    assert reviewer.calls == 1


def test_reviewer_result_preserves_decision_findings_and_derived_lineage() -> None:
    context = _review_context()
    result = ReviewerResult(
        context=context,
        decision="REQUEST_CHANGES",
        findings=[_finding()],
        reviewed_at=REVIEWED_AT,
    )

    assert result.decision is ReviewDecision.REQUEST_CHANGES
    assert result.findings == (_finding(),)
    assert result.decision_cycle_id == context.decision_cycle_id
    assert result.portfolio_id == context.portfolio_id
    assert result.constitution_version == "value-v1.0.0"


def test_review_models_are_effectively_immutable() -> None:
    context = _review_context()
    finding = _finding()
    source_findings = [finding]
    result = ReviewerResult(context=context, decision="REQUEST_CHANGES", findings=source_findings, reviewed_at=REVIEWED_AT)
    source_findings.clear()

    assert result.findings == (_finding(),)
    with pytest.raises(FrozenInstanceError):
        finding.message = "A different message."  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.decision = ReviewDecision.APPROVE  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        context.constitution = ConstitutionLoader.load_value_manager_constitution()  # type: ignore[misc]


def test_context_rejects_mismatched_risk_result_and_constitution() -> None:
    context = _review_context()
    other_context = _review_context()

    with pytest.raises(ValueError, match="decision_result"):
        AIReviewerReviewContext(
            decision_result=context.decision_result,
            risk_validation_result=other_context.risk_validation_result,
            constitution=context.constitution,
        )
    with pytest.raises(ValueError, match="constitution"):
        AIReviewerReviewContext(
            decision_result=context.decision_result,
            risk_validation_result=context.risk_validation_result,
            constitution=replace(other_context.constitution, description="A different constitution artifact."),
        )


def test_finding_normalizes_and_rejects_malformed_values() -> None:
    finding = _finding(severity=" warning ", category=" evidence_usage ")

    assert finding.severity is ReviewFindingSeverity.WARNING
    assert finding.category is ReviewFindingCategory.EVIDENCE_USAGE
    assert finding.related_evidence_ids == ("ev_aapl_001",)
    with pytest.raises(ValueError, match="message"):
        _finding(message="   ")
    with pytest.raises(ValueError, match="duplicates"):
        _finding(related_evidence_ids=("ev_aapl_001", "ev_aapl_001"))
    with pytest.raises(TypeError, match="tuple or list"):
        _finding(related_evidence_ids="ev_aapl_001")


def test_result_requires_findings_for_request_changes_and_known_evidence() -> None:
    context = _review_context()

    with pytest.raises(ValueError, match="at least one"):
        ReviewerResult(context=context, decision="REQUEST_CHANGES", findings=(), reviewed_at=REVIEWED_AT)
    with pytest.raises(ValueError, match="must exist"):
        ReviewerResult(
            context=context,
            decision="REQUEST_CHANGES",
            findings=(_finding(related_evidence_ids=("unknown",)),),
            reviewed_at=REVIEWED_AT,
        )


def test_review_time_is_aware_and_not_before_validation() -> None:
    context = _review_context()

    ReviewerResult(context=context, decision="APPROVE", findings=(), reviewed_at=VALIDATED_AT)
    with pytest.raises(ValueError, match="validation_timestamp"):
        ReviewerResult(
            context=context,
            decision="APPROVE",
            findings=(),
            reviewed_at=VALIDATED_AT - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        ReviewerResult(
            context=context,
            decision="APPROVE",
            findings=(),
            reviewed_at=REVIEWED_AT.replace(tzinfo=None),
        )


def test_reviewer_boundary_does_not_expose_execution_or_accounting_fields() -> None:
    context = _review_context()
    result = ReviewerResult(context=context, decision="APPROVE", findings=(), reviewed_at=REVIEWED_AT)
    reviewer_field_names = {field.name for field in fields(AIReviewerReviewContext)} | {
        field.name for field in fields(ReviewerResult)
    }
    prohibited_names = {"cash", "quantity", "dollars", "shares", "execution_price", "trade", "portfolio"}

    assert reviewer_field_names.isdisjoint(prohibited_names)
    assert context.decision_result.context.portfolio.cash_balance.amount == Decimal("1000")
    assert result.context.decision_result.context.portfolio.positions == ()


def test_passed_buy_and_hold_validation_results_are_accepted_for_review() -> None:
    buy_context = _review_context()
    hold_context = _review_context(action="HOLD")

    assert buy_context.risk_validation_result.passed
    assert hold_context.risk_validation_result.passed


def test_failed_deterministic_validation_is_rejected_before_reviewer_invocation() -> None:
    context = _review_context()
    failed = RiskValidationResult(
        decision_result=context.decision_result,
        validation_timestamp=VALIDATED_AT,
        status=RiskValidationStatus.FAILED,
        rule_results=(
            RiskRuleResult(
                rule_id="EXAMPLE_COMPLETED_RULE",
                status=RiskValidationStatus.FAILED,
                reason="A deterministic validation rule already failed.",
            ),
        ),
    )
    assert not failed.passed
    with pytest.raises(ValueError, match="must have passed"):
        AIReviewerReviewContext(
            decision_result=context.decision_result,
            risk_validation_result=failed,
            constitution=context.constitution,
        )


def test_reviewer_decision_and_finding_severity_are_consistent() -> None:
    context = _review_context()
    advisory_finding = _finding(severity="WARNING")
    critical_finding = _finding(severity="CRITICAL")

    ReviewerResult(context=context, decision="APPROVE", findings=(), reviewed_at=REVIEWED_AT)
    ReviewerResult(context=context, decision="APPROVE", findings=(advisory_finding,), reviewed_at=REVIEWED_AT)
    with pytest.raises(ValueError, match="CRITICAL"):
        ReviewerResult(context=context, decision="APPROVE", findings=(critical_finding,), reviewed_at=REVIEWED_AT)
    ReviewerResult(
        context=context,
        decision="REQUEST_CHANGES",
        findings=(critical_finding,),
        reviewed_at=REVIEWED_AT,
    )
    with pytest.raises(ValueError, match="at least one"):
        ReviewerResult(context=context, decision="REQUEST_CHANGES", findings=(), reviewed_at=REVIEWED_AT)
