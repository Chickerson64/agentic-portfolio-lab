from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain import (
    OpenAIValueManager,
    PortfolioRecommendation,
    RecommendationAction,
    RecommendationEvidenceReference,
    ReviewTrigger,
    ValueManager,
    ValueManagerDecisionContext,
    ValueManagerDecisionWorkflow,
)
from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.openai_value_manager import _recommendation_schema, _serialize_section
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio, Position, SecurityIdentity
from agentic_portfolio_lab.domain.research import EvidenceItem, MissingData, MissingDataReason, ResearchBatch, ResearchPacket, ResearchSection


UTC = timezone.utc


def _portfolio() -> Portfolio:
    apple = SecurityIdentity(ticker="AAPL", security_type="EQUITY", exchange="NASDAQ", currency="USD")
    return Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Value Portfolio",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance(currency="USD", amount=Decimal("1000")),
        created_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
        positions=(Position(apple, Decimal("2"), Decimal("100"), Decimal("90")),),
    )


def _evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev_aapl_001",
        source_type="FILING",
        source_title="Quarterly Report",
        source_date=date(2026, 8, 9),
        claim_supported="Operating cash flow remained positive.",
    )


def _batch(portfolio: Portfolio, *, packets: tuple[ResearchPacket, ...] | None = None) -> ResearchBatch:
    evidence = _evidence()
    packet = ResearchPacket(
        packet_id="packet_aapl",
        candidate_id="candidate_aapl",
        ticker="AAPL",
        security_type="EQUITY",
        exchange="NASDAQ",
        currency="USD",
        company_name="Apple Inc.",
        sector="Technology",
        industry="Consumer Electronics",
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
    return ResearchBatch(
        batch_id="batch_001",
        decision_cycle_id=uuid4(),
        portfolio_id=portfolio.portfolio_id,
        manager_type="VALUE",
        created_at=datetime(2026, 8, 10, 13, tzinfo=UTC),
        as_of_timestamp=datetime(2026, 8, 10, 12, tzinfo=UTC),
        packets=packets or (packet,),
    )


def _context(*, feedback: tuple[str, ...] = ()) -> ValueManagerDecisionContext:
    portfolio = _portfolio()
    return ValueManagerDecisionContext(
        portfolio=portfolio,
        research_batch=_batch(portfolio),
        constitution=ConstitutionLoader.load_value_manager_constitution(),
        prior_reviewer_feedback=feedback,
    )


def _buy_payload() -> dict[str, object]:
    evidence = _evidence()
    return {
        "action": "BUY",
        "ticker": "AAPL",
        "target_weight": 0.25,
        "decision_rationale": "The business is durable and the valuation is reasonable.",
        "investment_thesis": "Strong cash generation can compound over time.",
        "valuation": "The current price leaves room for compounding.",
        "risks": ["Demand could soften."],
        "confidence_score": 74,
        "evidence": [
            {
                "evidence_id": evidence.evidence_id,
                "source_type": evidence.source_type,
                "source_title": evidence.source_title,
                "source_date": evidence.source_date.isoformat(),
                "claim_supported": "The filing supports positive operating cash flow.",
            }
        ],
        "why_not_spy": "The opportunity appears more compelling than incremental SPY exposure.",
        "thesis_invalidation": ["Cash generation deteriorates materially."],
        "review_triggers": [
            {"trigger_type": "EVENT_BASED", "description": "Review after a material earnings miss."}
        ],
    }


def _hold_payload() -> dict[str, object]:
    return {
        "action": "HOLD",
        "ticker": None,
        "target_weight": None,
        "decision_rationale": "No candidate clears the constitution bar.",
        "investment_thesis": None,
        "valuation": "No current opportunity is attractive enough.",
        "risks": ["Evidence is insufficient."],
        "confidence_score": 51,
        "evidence": [
            {
                "evidence_id": _evidence().evidence_id,
                "source_type": "FILING",
                "source_title": "Quarterly Report",
                "source_date": "2026-08-09",
                "claim_supported": "The filing supports positive operating cash flow.",
            }
        ],
        "why_not_spy": "HOLD is preferable to forcing active risk.",
        "thesis_invalidation": [],
        "review_triggers": [],
    }


class FakeResponses:
    def __init__(self, *, output_text: str | None = None, raise_exc: Exception | None = None, status: str = "completed") -> None:
        self.output_text = output_text
        self.raise_exc = raise_exc
        self.status = status
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.raise_exc is not None:
            raise self.raise_exc
        return SimpleNamespace(id="resp_123", _request_id="req_456", output_text=self.output_text, status=self.status)


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def _manager(payload: dict[str, object]) -> tuple[OpenAIValueManager, FakeResponses]:
    responses = FakeResponses(output_text=json.dumps(payload))
    return OpenAIValueManager(client=FakeClient(responses)), responses


def test_openai_value_manager_returns_buy_recommendation() -> None:
    context = _context()
    manager, responses = _manager(_buy_payload())

    recommendation = manager.decide(context)

    assert isinstance(manager, ValueManager)
    assert recommendation.action is RecommendationAction.BUY
    assert recommendation.ticker == "AAPL"
    assert recommendation.target_weight == Decimal("0.25")
    assert recommendation.evidence[0].evidence_id == "ev_aapl_001"
    assert manager.last_metadata.response_id == "resp_123"
    assert manager.last_metadata.request_id == "req_456"
    assert responses.calls and responses.calls[0]["model"] == "gpt-5.6-terra"
    assert responses.calls[0]["store"] is False


def test_openai_value_manager_returns_hold_recommendation() -> None:
    context = _context()
    manager, _ = _manager(_hold_payload())

    recommendation = manager.decide(context)

    assert recommendation.action is RecommendationAction.HOLD
    assert recommendation.ticker is None
    assert recommendation.target_weight is None
    assert recommendation.investment_thesis is None


def test_openai_value_manager_includes_constitution_portfolio_batch_and_feedback() -> None:
    context = _context(feedback=("Please tie the thesis to cash flow.",))
    manager, responses = _manager(_buy_payload())

    manager.decide(context)

    call = responses.calls[0]
    prompt = "\n".join(
        json.dumps(item, sort_keys=True) if isinstance(item, dict) else str(item)
        for item in call["input"]  # type: ignore[index]
    )
    assert "Value Manager Constitution" in prompt
    assert "Operating cash flow remained positive." in prompt
    assert "Please tie the thesis to cash flow." in prompt
    assert "research_batch" in prompt
    assert "portfolio_id" in prompt
    assert "AAPL" in prompt


@pytest.mark.parametrize(
    ("needle", "description"),
    [
        ("Value Manager Constitution", "constitution text"),
        ("portfolio_id", "portfolio identity"),
        ("research_batch", "research batch"),
        ("batch_id", "batch id"),
        ("decision_cycle_id", "decision cycle"),
        ("ticker", "ticker"),
        ("currency", "currency"),
        ("evidence_items", "evidence items"),
        ("output_contract", "output contract"),
    ],
)
def test_openai_value_manager_prompt_includes_expected_review_boundaries(needle: str, description: str) -> None:
    context = _context(feedback=("Please keep the thesis grounded in evidence.",))
    manager, responses = _manager(_buy_payload())

    manager.decide(context)

    prompt = json.dumps(responses.calls[0], sort_keys=True, default=str)
    assert needle in prompt, description


@pytest.mark.parametrize(
    ("field", "value", "expected", "payload_factory"),
    [
        ("action", "BUY", RecommendationAction.BUY, _buy_payload),
        ("ticker", "AAPL", "AAPL", _buy_payload),
        ("target_weight", 0.25, Decimal("0.25"), _buy_payload),
        ("decision_rationale", "The business is durable.", "The business is durable.", _buy_payload),
        ("investment_thesis", "Strong cash generation can compound.", "Strong cash generation can compound.", _buy_payload),
        ("valuation", "Reasonable relative to quality.", "Reasonable relative to quality.", _buy_payload),
        ("risks", ["Demand could soften."], ("Demand could soften.",), _buy_payload),
        ("confidence_score", 74, 74, _buy_payload),
        ("evidence", [{"evidence_id": "ev_aapl_001", "source_type": "FILING", "source_title": "Quarterly Report", "source_date": "2026-08-09", "claim_supported": "The filing supports positive operating cash flow."}], None, _buy_payload),
        ("why_not_spy", "The opportunity is better than incremental SPY exposure.", "The opportunity is better than incremental SPY exposure.", _buy_payload),
        ("thesis_invalidation", ["Cash generation deteriorates materially."], ("Cash generation deteriorates materially.",), _buy_payload),
        ("review_triggers", [{"trigger_type": "EVENT_BASED", "description": "Review after a material earnings miss."}], (ReviewTrigger("EVENT_BASED", "Review after a material earnings miss."),), _buy_payload),
        ("action", "HOLD", RecommendationAction.HOLD, _hold_payload),
        ("ticker", None, None, _hold_payload),
        ("target_weight", None, None, _hold_payload),
        ("investment_thesis", None, None, _hold_payload),
        ("confidence_score", 51, 51, _hold_payload),
    ],
)
def test_openai_value_manager_structured_output_contains_domain_owned_values(
    field: str,
    value: object,
    expected: object,
    payload_factory,
) -> None:
    payload = payload_factory()
    payload[field] = value
    manager, _ = _manager(payload)

    recommendation = manager.decide(_context())

    actual = getattr(recommendation, field)
    if field == "evidence":
        assert actual[0].evidence_id == "ev_aapl_001"
        assert actual[0].source_type == "FILING"
    else:
        assert actual == expected
