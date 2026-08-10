from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio
from agentic_portfolio_lab.domain.recommendations import (
    PortfolioRecommendation,
    RecommendationEvidenceReference,
    ReviewTrigger,
)
from agentic_portfolio_lab.domain.research import EvidenceItem, ResearchBatch, ResearchPacket, ResearchSection
from agentic_portfolio_lab.domain.value_manager import ValueManager, ValueManagerDecisionContext
from agentic_portfolio_lab.domain.value_manager_workflow import (
    ValueManagerDecisionResult,
    ValueManagerDecisionWorkflow,
)


def _portfolio() -> Portfolio:
    return Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Value Portfolio",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance(currency="USD", amount=Decimal("1000")),
        created_at=datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
    )


def _evidence(
    evidence_id: str = "ev_aapl_001",
    *,
    source_title: str = "Quarterly Report",
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        source_type="FILING",
        source_title=source_title,
        source_date=date(2026, 8, 9),
        claim_supported="Operating cash flow remained positive.",
    )


def _packet(
    *,
    packet_id: str = "packet_aapl",
    candidate_id: str = "candidate_aapl",
    ticker: str = "AAPL",
    security_type: str = "EQUITY",
    evidence: EvidenceItem | None = None,
) -> ResearchPacket:
    evidence = evidence or _evidence()
    return ResearchPacket(
        packet_id=packet_id,
        candidate_id=candidate_id,
        ticker=ticker,
        security_type=security_type,
        as_of_timestamp=datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
        evidence_items=(evidence,),
        sections=(
            ResearchSection(
                section_id="BUSINESS_OVERVIEW",
                content="The company sells devices and services.",
                evidence_ids=(evidence.evidence_id,),
            ),
        ),
    )


def _batch(portfolio: Portfolio, *, packets: tuple[ResearchPacket, ...] | None = None) -> ResearchBatch:
    return ResearchBatch(
        batch_id="batch_001",
        decision_cycle_id=uuid4(),
        portfolio_id=portfolio.portfolio_id,
        manager_type="VALUE",
        created_at=datetime(2026, 8, 10, 13, tzinfo=timezone.utc),
        as_of_timestamp=datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
        packets=packets or (_packet(),),
    )


def _reference(evidence: EvidenceItem | None = None, **overrides: object) -> RecommendationEvidenceReference:
    evidence = evidence or _evidence()
    arguments: dict[str, object] = {
        "evidence_id": evidence.evidence_id,
        "source_type": evidence.source_type,
        "source_title": evidence.source_title,
        "source_date": evidence.source_date,
        "claim_supported": "The filing supports positive operating cash flow.",
    }
    arguments.update(overrides)
    return RecommendationEvidenceReference(**arguments)  # type: ignore[arg-type]


def _recommendation(
    *,
    action: str = "BUY",
    source_evidence: EvidenceItem | None = None,
    **overrides: object,
) -> PortfolioRecommendation:
    arguments: dict[str, object] = {
        "action": action,
        "ticker": "AAPL" if action == "BUY" else None,
        "target_weight": Decimal("0.10") if action == "BUY" else None,
        "decision_rationale": "The evidence supports a durable, attractive business.",
        "investment_thesis": "Cash generation and durable demand can compound over time." if action == "BUY" else None,
        "valuation": "The valuation is reasonable relative to durable cash generation.",
        "risks": ("Demand could weaken.",),
        "confidence_score": 72,
        "evidence": (_reference(source_evidence),),
        "why_not_spy": "This evidence-backed opportunity is more compelling than incremental SPY exposure.",
        "thesis_invalidation": ("Cash generation deteriorates materially.",) if action == "BUY" else (),
        "review_triggers": (ReviewTrigger("EVENT_BASED", "Review after a material earnings miss."),),
    }
    arguments.update(overrides)
    return PortfolioRecommendation(**arguments)  # type: ignore[arg-type]


def _context(portfolio: Portfolio, *, batch: ResearchBatch | None = None) -> ValueManagerDecisionContext:
    return ValueManagerDecisionContext(
        portfolio=portfolio,
        research_batch=batch or _batch(portfolio),
        constitution=ConstitutionLoader.load_value_manager_constitution(),
    )


class StubValueManager:
    def __init__(self, result: object) -> None:
        self.result = result
        self.call_count = 0

    def decide(self, context: ValueManagerDecisionContext) -> object:
        self.call_count += 1
        return self.result


def _workflow(recommendation: object) -> ValueManagerDecisionWorkflow:
    return ValueManagerDecisionWorkflow(StubValueManager(recommendation))


def test_workflow_runs_a_stub_manager_and_preserves_buy_lineage() -> None:
    portfolio = _portfolio()
    context = _context(portfolio)
    recommendation = _recommendation()
    workflow = _workflow(recommendation)

    assert isinstance(workflow.manager, ValueManager)
    result = workflow.run(context, produced_at=datetime(2026, 8, 10, 14, tzinfo=timezone.utc))

    assert result.recommendation is recommendation
    assert result.decision_cycle_id == context.research_batch.decision_cycle_id
    assert result.portfolio_id == portfolio.portfolio_id
    assert result.manager_type == "VALUE"
    assert result.constitution_version == "value-v1.0.0"
    assert result.research_batch_id == context.research_batch.batch_id
    assert workflow.manager.call_count == 1


def test_workflow_allows_a_portfolio_level_hold_without_ticker_lookup() -> None:
    portfolio = _portfolio()
    context = _context(portfolio)

    result = _workflow(_recommendation(action="HOLD")).run(
        context,
        produced_at=datetime(2026, 8, 10, 14, tzinfo=timezone.utc),
    )

    assert result.recommendation.ticker is None


def test_workflow_rejects_a_manager_that_returns_a_non_recommendation() -> None:
    with pytest.raises(TypeError, match="PortfolioRecommendation"):
        _workflow("BUY").run(_context(_portfolio()), produced_at=datetime(2026, 8, 10, 14, tzinfo=timezone.utc))


def test_workflow_rejects_a_buy_ticker_absent_from_the_batch() -> None:
    with pytest.raises(ValueError, match="ticker must exist"):
        _workflow(_recommendation(ticker="MSFT")).run(
            _context(_portfolio()),
            produced_at=datetime(2026, 8, 10, 14, tzinfo=timezone.utc),
        )


def test_workflow_rejects_a_buy_ticker_matching_multiple_packets() -> None:
    portfolio = _portfolio()
    first = _packet()
    second = _packet(
        packet_id="packet_aapl_adr",
        candidate_id="candidate_aapl_adr",
        security_type="ADR",
    )
    context = _context(portfolio, batch=_batch(portfolio, packets=(first, second)))

    with pytest.raises(ValueError, match="exactly one"):
        _workflow(_recommendation()).run(
            context,
            produced_at=datetime(2026, 8, 10, 14, tzinfo=timezone.utc),
        )


def test_workflow_rejects_missing_evidence_and_evidence_metadata_mismatches() -> None:
    context = _context(_portfolio())
    missing_reference = _reference(evidence_id="missing")
    with pytest.raises(ValueError, match="evidence_id must exist"):
        _workflow(_recommendation(evidence=(missing_reference,))).run(
            context,
            produced_at=datetime(2026, 8, 10, 14, tzinfo=timezone.utc),
        )

    mismatched_reference = _reference(source_title="Different Report")
    with pytest.raises(ValueError, match="metadata must match"):
        _workflow(_recommendation(evidence=(mismatched_reference,))).run(
            context,
            produced_at=datetime(2026, 8, 10, 14, tzinfo=timezone.utc),
        )


def test_workflow_rejects_duplicate_evidence_id_ambiguity_across_packets() -> None:
    portfolio = _portfolio()
    first = _packet(evidence=_evidence("ev_shared", source_title="First Report"))
    second = _packet(
        packet_id="packet_msft",
        candidate_id="candidate_msft",
        ticker="MSFT",
        evidence=_evidence("ev_shared", source_title="Second Report"),
    )
    context = _context(portfolio, batch=_batch(portfolio, packets=(first, second)))

    with pytest.raises(ValueError, match="ambiguous"):
        _workflow(_recommendation(source_evidence=first.evidence_items[0])).run(
            context,
            produced_at=datetime(2026, 8, 10, 14, tzinfo=timezone.utc),
        )


def test_workflow_requires_timezone_aware_produced_at_and_keeps_inputs_immutable() -> None:
    portfolio = _portfolio()
    context = _context(portfolio)
    workflow = _workflow(_recommendation())

    with pytest.raises(ValueError, match="timezone-aware"):
        workflow.run(context, produced_at=datetime(2026, 8, 10, 14))

    result = workflow.run(context, produced_at=datetime(2026, 8, 10, 14, tzinfo=timezone.utc))
    with pytest.raises(FrozenInstanceError):
        result.produced_at = datetime(2026, 8, 10, 15, tzinfo=timezone.utc)  # type: ignore[misc]
    assert context.portfolio is portfolio
    assert context.research_batch.packets == (_packet(),)


def test_result_direct_construction_verifies_recommendation_against_context() -> None:
    context = _context(_portfolio())
    with pytest.raises(ValueError, match="ticker must exist"):
        ValueManagerDecisionResult(
            context=context,
            recommendation=_recommendation(ticker="MSFT"),
            produced_at=datetime(2026, 8, 10, 14, tzinfo=timezone.utc),
        )
    with pytest.raises(ValueError, match="evidence_id must exist"):
        ValueManagerDecisionResult(
            context=context,
            recommendation=_recommendation(evidence=(_reference(evidence_id="missing"),)),
            produced_at=datetime(2026, 8, 10, 14, tzinfo=timezone.utc),
        )


def test_workflow_requires_produced_at_to_not_precede_batch_creation() -> None:
    context = _context(_portfolio())
    workflow = _workflow(_recommendation())

    result = workflow.run(context, produced_at=context.research_batch.created_at)
    assert result.produced_at == context.research_batch.created_at

    with pytest.raises(ValueError, match="must not precede"):
        workflow.run(
            context,
            produced_at=datetime(2026, 8, 10, 12, 59, tzinfo=timezone.utc),
        )


def test_workflow_propagates_manager_exceptions_unchanged() -> None:
    class ManagerFailure(Exception):
        pass

    failure = ManagerFailure("manager failed")

    class SameFailureValueManager:
        def decide(self, context: ValueManagerDecisionContext) -> PortfolioRecommendation:
            raise failure

    with pytest.raises(ManagerFailure) as raised:
        ValueManagerDecisionWorkflow(SameFailureValueManager()).run(
            _context(_portfolio()),
            produced_at=datetime(2026, 8, 10, 14, tzinfo=timezone.utc),
        )

    assert raised.value is failure


def test_result_derives_lineage_to_prevent_conflicting_direct_fields() -> None:
    context = _context(_portfolio())
    result = ValueManagerDecisionResult(
        context=context,
        recommendation=_recommendation(),
        produced_at=datetime(2026, 8, 10, 14, tzinfo=timezone.utc),
    )

    assert "decision_cycle_id" not in ValueManagerDecisionResult.__dataclass_fields__
    assert result.decision_cycle_id == context.decision_cycle_id
