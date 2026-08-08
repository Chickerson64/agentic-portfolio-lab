from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from agentic_portfolio_lab.domain.recommendations import (
    PortfolioRecommendation,
    RecommendationAction,
    RecommendationEvidenceReference,
    ReviewTrigger,
    ReviewTriggerType,
)


def _evidence(evidence_id: str = "ev_001") -> RecommendationEvidenceReference:
    return RecommendationEvidenceReference(
        evidence_id=evidence_id,
        source_type="filing",
        source_title="Quarterly Report",
        source_date=date(2026, 8, 1),
        claim_supported="Free cash flow remained positive.",
    )


def _buy(**overrides: object) -> PortfolioRecommendation:
    arguments: dict[str, object] = {
        "action": " buy ",
        "ticker": " aapl ",
        "target_weight": Decimal("0.125"),
        "decision_rationale": "The evidence supports a durable and attractively valued business.",
        "investment_thesis": "Cash generation and durable demand can compound over time.",
        "valuation": "The current valuation is reasonable relative to cash generation.",
        "risks": ["Demand could weaken."],
        "confidence_score": 72,
        "evidence": [_evidence()],
        "why_not_spy": "The evidence supports greater expected long-term value than passive SPY exposure.",
        "thesis_invalidation": ["Cash generation deteriorates materially."],
        "review_triggers": [ReviewTrigger("event_based", "Review after a material earnings miss.")],
    }
    arguments.update(overrides)
    return PortfolioRecommendation(**arguments)  # type: ignore[arg-type]


def _hold(**overrides: object) -> PortfolioRecommendation:
    arguments: dict[str, object] = {
        "action": RecommendationAction.HOLD,
        "ticker": None,
        "target_weight": None,
        "decision_rationale": "No supplied candidate currently clears the evidence and valuation bar.",
        "investment_thesis": None,
        "valuation": "The supplied valuations do not provide a sufficient margin of safety.",
        "risks": ["Evidence may be incomplete."],
        "confidence_score": 65,
        "evidence": [_evidence()],
        "why_not_spy": "No active opportunity clears the bar relative to adding capital to SPY.",
        "thesis_invalidation": [],
        "review_triggers": [ReviewTrigger(ReviewTriggerType.SCHEDULED, "Review at the next scheduled decision cycle.")],
    }
    arguments.update(overrides)
    return PortfolioRecommendation(**arguments)  # type: ignore[arg-type]


def test_buy_recommendation_normalizes_intent_fields_and_uses_immutable_collections() -> None:
    recommendation = _buy()

    assert recommendation.action is RecommendationAction.BUY
    assert recommendation.ticker == "AAPL"
    assert recommendation.target_weight == Decimal("0.125")
    assert recommendation.evidence[0].source_type == "FILING"
    assert recommendation.risks == ("Demand could weaken.",)
    assert recommendation.thesis_invalidation == ("Cash generation deteriorates materially.",)
    assert isinstance(recommendation.evidence, tuple)
    assert isinstance(recommendation.review_triggers, tuple)
    with pytest.raises(FrozenInstanceError):
        recommendation.ticker = "MSFT"  # type: ignore[misc]


def test_hold_recommendation_uses_portfolio_level_null_security_and_weight() -> None:
    recommendation = _hold()

    assert recommendation.action is RecommendationAction.HOLD
    assert recommendation.ticker is None
    assert recommendation.target_weight is None
    assert recommendation.investment_thesis is None
    assert recommendation.thesis_invalidation == tuple()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ticker", None, "ticker is required"),
        ("target_weight", None, "target_weight is required"),
        ("target_weight", Decimal("0"), "greater than zero"),
        ("target_weight", Decimal("-0.000001"), "greater than zero"),
        ("target_weight", Decimal("1.000001"), "must not exceed 1"),
        ("target_weight", Decimal("0.1234567"), "at most 6 decimal places"),
        ("investment_thesis", None, "investment_thesis is required"),
    ],
)
def test_buy_recommendation_enforces_conditional_fields(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _buy(**{field: value})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ticker", "AAPL", "ticker must be null"),
        ("target_weight", Decimal("0.1"), "target_weight must be null"),
        ("investment_thesis", "A thesis", "investment_thesis must be null"),
    ],
)
def test_hold_recommendation_rejects_directional_fields(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _hold(**{field: value})


@pytest.mark.parametrize("score", [-1, 101])
def test_confidence_score_requires_the_settled_integer_bounds(score: int) -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        _buy(confidence_score=score)


@pytest.mark.parametrize("score", [True, 72.0, "72"])
def test_confidence_score_rejects_non_integer_values(score: object) -> None:
    with pytest.raises(TypeError, match="integer"):
        _buy(confidence_score=score)


@pytest.mark.parametrize(
    "arguments",
    [
        {"evidence_id": "", "source_type": "FILING", "source_title": "Report", "source_date": date(2026, 8, 1), "claim_supported": "Claim"},
        {"evidence_id": "ev_001", "source_type": "", "source_title": "Report", "source_date": date(2026, 8, 1), "claim_supported": "Claim"},
        {"evidence_id": "ev_001", "source_type": "FILING", "source_title": "", "source_date": date(2026, 8, 1), "claim_supported": "Claim"},
        {"evidence_id": "ev_001", "source_type": "FILING", "source_title": "Report", "source_date": date(2026, 8, 1), "claim_supported": ""},
    ],
)
def test_evidence_references_reject_malformed_required_values(arguments: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        RecommendationEvidenceReference(**arguments)  # type: ignore[arg-type]


def test_evidence_reference_enforces_date_only_source_dates() -> None:
    with pytest.raises(TypeError, match="date, not a datetime"):
        RecommendationEvidenceReference(
            evidence_id="ev_001",
            source_type="FILING",
            source_title="Report",
            source_date=datetime(2026, 8, 1, tzinfo=timezone.utc),  # type: ignore[arg-type]
            claim_supported="Claim",
        )


def test_evidence_collections_are_immutable_and_reject_duplicate_or_malformed_items() -> None:
    with pytest.raises(ValueError, match="duplicate evidence_id"):
        _buy(evidence=[_evidence("ev_001"), _evidence(" ev_001 ")])
    with pytest.raises(TypeError, match="RecommendationEvidenceReference"):
        _buy(evidence=["ev_001"])
    with pytest.raises(TypeError, match="tuple or list"):
        _buy(evidence="ev_001")


def test_event_based_and_scheduled_review_triggers_are_supported() -> None:
    event_based = ReviewTrigger(" event_based ", "Review after a material earnings miss.")
    scheduled = ReviewTrigger(ReviewTriggerType.SCHEDULED, "Review at the next scheduled decision cycle.")

    assert event_based.trigger_type is ReviewTriggerType.EVENT_BASED
    assert scheduled.trigger_type is ReviewTriggerType.SCHEDULED
    assert _buy(review_triggers=[event_based, scheduled]).review_triggers == (event_based, scheduled)


def test_recommendation_models_do_not_include_execution_or_accounting_fields() -> None:
    recommendation_fields = set(PortfolioRecommendation.__dataclass_fields__)

    assert recommendation_fields.isdisjoint(
        {"dollars", "shares", "quantity", "cash", "execution_price", "executed_at", "portfolio", "trade"}
    )
