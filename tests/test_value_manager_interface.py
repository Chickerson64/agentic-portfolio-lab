from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio
from agentic_portfolio_lab.domain.recommendations import (
    PortfolioRecommendation,
    RecommendationEvidenceReference,
    ReviewTrigger,
)
from agentic_portfolio_lab.domain.research import EvidenceItem, ResearchBatch, ResearchPacket, ResearchSection
from agentic_portfolio_lab.domain.value_manager import ValueManager, ValueManagerDecisionContext


def _portfolio() -> Portfolio:
    return Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Value Portfolio",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance(currency="USD", amount=Decimal("1000")),
        created_at=datetime(2026, 8, 8, 12, tzinfo=timezone.utc),
    )


def _packet() -> ResearchPacket:
    evidence = EvidenceItem(
        evidence_id="ev_aapl_001",
        source_type="FILING",
        source_title="Quarterly Report",
        source_date=date(2026, 8, 7),
        claim_supported="Operating cash flow remained positive.",
    )
    return ResearchPacket(
        packet_id="packet_aapl",
        candidate_id="candidate_aapl",
        ticker="AAPL",
        security_type="EQUITY",
        as_of_timestamp=datetime(2026, 8, 8, 12, tzinfo=timezone.utc),
        evidence_items=(evidence,),
        sections=(
            ResearchSection(
                section_id="BUSINESS_OVERVIEW",
                content="The company sells devices and services.",
                evidence_ids=(evidence.evidence_id,),
            ),
        ),
    )


def _batch(portfolio: Portfolio, **overrides: object) -> ResearchBatch:
    arguments: dict[str, object] = {
        "batch_id": "batch_001",
        "decision_cycle_id": uuid4(),
        "portfolio_id": portfolio.portfolio_id,
        "manager_type": " value ",
        "created_at": datetime(2026, 8, 8, 13, tzinfo=timezone.utc),
        "as_of_timestamp": datetime(2026, 8, 8, 12, tzinfo=timezone.utc),
        "packets": (_packet(),),
    }
    arguments.update(overrides)
    return ResearchBatch(**arguments)  # type: ignore[arg-type]


def _recommendation() -> PortfolioRecommendation:
    evidence = RecommendationEvidenceReference(
        evidence_id="ev_aapl_001",
        source_type="FILING",
        source_title="Quarterly Report",
        source_date=date(2026, 8, 7),
        claim_supported="Operating cash flow remained positive.",
    )
    return PortfolioRecommendation(
        action="HOLD",
        ticker=None,
        target_weight=None,
        decision_rationale="The supplied evidence does not justify active risk.",
        investment_thesis=None,
        valuation="The current evidence does not establish an attractive valuation.",
        risks=("Evidence may be incomplete.",),
        confidence_score=65,
        evidence=(evidence,),
        why_not_spy="No active opportunity clears the bar relative to SPY.",
        thesis_invalidation=(),
        review_triggers=(ReviewTrigger("SCHEDULED", "Review at the next decision cycle."),),
    )


class StubValueManager:
    """A dependency-free implementation used only to verify the protocol."""

    def decide(self, context: ValueManagerDecisionContext) -> PortfolioRecommendation:
        assert context.research_batch.packets
        return _recommendation()


def test_value_manager_protocol_accepts_a_dependency_free_stub_returning_one_recommendation() -> None:
    portfolio = _portfolio()
    context = ValueManagerDecisionContext(
        portfolio=portfolio,
        research_batch=_batch(portfolio),
        constitution_version=" value-v1.0.0 ",
    )
    manager = StubValueManager()

    assert isinstance(manager, ValueManager)
    assert isinstance(manager.decide(context), PortfolioRecommendation)


def test_decision_context_is_immutable_and_derives_decision_lineage_from_the_batch() -> None:
    portfolio = _portfolio()
    batch = _batch(portfolio)
    context = ValueManagerDecisionContext(
        portfolio=portfolio,
        research_batch=batch,
        constitution_version=" value-v1.0.0 ",
        prior_reviewer_feedback=[" Clarify the valuation rationale. "],
    )

    assert context.constitution_version == "value-v1.0.0"
    assert context.prior_reviewer_feedback == ("Clarify the valuation rationale.",)
    assert context.decision_cycle_id == batch.decision_cycle_id
    assert isinstance(context.prior_reviewer_feedback, tuple)
    with pytest.raises(FrozenInstanceError):
        context.constitution_version = "value-v2.0.0"  # type: ignore[misc]


def test_decision_context_rejects_mismatched_batch_portfolio_lineage() -> None:
    with pytest.raises(ValueError, match="portfolio_id"):
        ValueManagerDecisionContext(
            portfolio=_portfolio(),
            research_batch=_batch(_portfolio()),
            constitution_version="value-v1.0.0",
        )


def test_decision_context_requires_a_value_batch_and_explicit_constitution_version() -> None:
    portfolio = _portfolio()

    with pytest.raises(ValueError, match="manager_type"):
        ValueManagerDecisionContext(
            portfolio=portfolio,
            research_batch=_batch(portfolio, manager_type="GROWTH"),
            constitution_version="value-v1.0.0",
        )
    with pytest.raises(ValueError, match="constitution_version"):
        ValueManagerDecisionContext(
            portfolio=portfolio,
            research_batch=_batch(portfolio),
            constitution_version=" ",
        )


def test_decision_context_contains_no_execution_or_accounting_fields() -> None:
    context_fields = set(ValueManagerDecisionContext.__dataclass_fields__)

    assert context_fields.isdisjoint(
        {"dollars", "shares", "quantity", "execution_price", "executed_at", "trade", "cash_feasibility"}
    )


@pytest.mark.parametrize("feedback", ["review note", ("",), ("valid", 1)])
def test_decision_context_rejects_malformed_reviewer_feedback(feedback: object) -> None:
    portfolio = _portfolio()

    with pytest.raises((TypeError, ValueError), match="prior_reviewer_feedback"):
        ValueManagerDecisionContext(
            portfolio=portfolio,
            research_batch=_batch(portfolio),
            constitution_version="value-v1.0.0",
            prior_reviewer_feedback=feedback,  # type: ignore[arg-type]
        )
