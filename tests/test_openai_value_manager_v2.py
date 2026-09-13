from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain import OpenAIValueManager, ValueManagerDecisionContext
from agentic_portfolio_lab.application.local_state_codec import decode, encode
from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.policy import InvestmentConstitutionReference, PolicyLoader
from agentic_portfolio_lab.domain.openai_value_manager import V2_PROMPT_VERSION, V2_SCHEMA_VERSION
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio, Position, SecurityIdentity
from agentic_portfolio_lab.domain.research_v3 import (
    ResearchBatchV3,
    ResearchSubjectRole,
    ResearchV3Evidence,
    ResearchV3Subject,
    ScreeningEvidenceContext,
)
from agentic_portfolio_lab.domain.screening_v2 import ScreeningFeatures, ScreeningProfileIdentity


UTC = timezone.utc
NOW = datetime(2026, 9, 13, tzinfo=UTC)


class _Responses:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(id="response-v2", _request_id="request-v2", status="completed", output_text=json.dumps(self.payload))


class _Client:
    def __init__(self, responses: _Responses) -> None:
        self.responses = responses


def _security(ticker: str) -> SecurityIdentity:
    return SecurityIdentity(ticker, "EQUITY", "NASDAQ", "USD")


def _context(*held: str, starting_capital: str = "100000") -> ValueManagerDecisionContext:
    holdings = tuple(Position(_security(ticker), Decimal("1"), Decimal("100"), Decimal("100")) for ticker in held)
    portfolio = Portfolio(uuid4(), "Value", "USD", Decimal(starting_capital), CashBalance("USD", Decimal(starting_capital)), NOW, holdings)
    profile = ScreeningProfileIdentity("value-manager", "value-screen", "v2")
    run_id = uuid4()
    subjects = []
    for ticker in dict.fromkeys(("AAPL", "MSFT", "GOOG", *held)):
        security = _security(ticker)
        role = ResearchSubjectRole.EXISTING_HOLDING if ticker in held else ResearchSubjectRole.NEW_CANDIDATE
        screening = None if role is ResearchSubjectRole.EXISTING_HOLDING else ScreeningEvidenceContext("universe-v2", profile, run_id, 1, ScreeningFeatures(Decimal("1"), Decimal("1"), Decimal("1"), None, Decimal("1")))
        subjects.append(ResearchV3Subject(
            ticker.lower(), security, role, NOW,
            (ResearchV3Evidence(f"evidence-{ticker}", "offline", "FILING", f"{ticker} filing", date(2026, 9, 12), f"ref-{ticker}", "CURRENT"),),
            "offline", screening,
        ))
    research = ResearchBatchV3("research-v3", run_id, "universe-v2", profile, NOW, tuple(subjects))
    return ValueManagerDecisionContext(
        portfolio=portfolio,
        research_batch=research,
        constitution=ConstitutionLoader.load_value_manager_constitution_v2(),
        manager_risk_constitution=PolicyLoader.load_value_manager_risk_constitution_v2(
            compatible_investment_constitution=InvestmentConstitutionReference.from_constitution(
                ConstitutionLoader.load_value_manager_constitution_v2()
            )
        ),
        market_context={"benchmark": "SPY"},
        prior_decision_lineage={"prior_decision_id": "decision-previous"},
    )


def _position(ticker: str, weight: str, disposition: str) -> dict[str, object]:
    return {
        "ticker": ticker, "security_type": "EQUITY", "exchange": "NASDAQ", "currency": "USD",
        "target_weight": float(weight), "role": "durable compounder", "thesis": f"{ticker} has durable cash generation.",
        "confidence": 80,
        "evidence": [{"evidence_id": f"evidence-{ticker}", "source_type": "FILING", "source_title": f"{ticker} filing", "source_date": "2026-09-12", "claim_supported": "Supports the stated thesis."}],
        "invalidation_conditions": ["Cash generation deteriorates materially."],
        "review_triggers": [{"trigger_type": "SCHEDULED", "description": "Review next quarter."}],
        "existing_holding_disposition": disposition, "research_supported": True,
    }


def _payload(context: ValueManagerDecisionContext, cash: str, *positions: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": V2_SCHEMA_VERSION, "portfolio_id": str(context.portfolio.portfolio_id), "construction_mode": "INITIAL" if not context.portfolio.positions else "REBALANCE",
        "overall_rationale": "Allocate only to researched durable businesses while retaining optionality.",
        "risk_commentary": "Company-specific risk is reviewed against the supplied evidence.",
        "concentration_commentary": "Weights reflect differentiated conviction without forced turnover.",
        "benchmark_active_risk_commentary": "Active risk versus SPY is limited to evidence-backed holdings and explicit cash.",
        "cash_target": {"weight": float(cash), "classification": "STRATEGIC", "rationale": "Preserve optionality."},
        "positions": list(positions),
    }


def _decide(context: ValueManagerDecisionContext, payload: dict[str, object]) -> tuple[object, _Responses]:
    responses = _Responses(payload)
    return OpenAIValueManager(client=_Client(responses)).decide_v2(context), responses


@pytest.mark.parametrize(
    ("held", "cash", "positions", "expected_dispositions"),
    [
        ((), "0.10", (_position("AAPL", "0.35", "INITIATE"), _position("MSFT", "0.30", "INITIATE"), _position("GOOG", "0.25", "INITIATE")), {"INITIATE"}),
        (("AAPL", "MSFT", "GOOG"), "0.10", (_position("AAPL", "0.30", "RETAIN"), _position("MSFT", "0.30", "RETAIN"), _position("GOOG", "0.30", "RETAIN")), {"RETAIN"}),
        (("AAPL", "MSFT"), "0.20", (_position("AAPL", "0.50", "INCREASE"), _position("MSFT", "0.30", "REDUCE")), {"INCREASE", "REDUCE"}),
        (("AAPL", "MSFT"), "0.30", (_position("AAPL", "0.70", "RETAIN"), _position("MSFT", "0.00", "REMOVE")), {"RETAIN", "REMOVE"}),
        (("AAPL",), "0.20", (_position("AAPL", "0.45", "RETAIN"), _position("MSFT", "0.35", "INITIATE")), {"RETAIN", "INITIATE"}),
        (("AAPL", "MSFT"), "0.50", (_position("AAPL", "0.25", "REDUCE"), _position("MSFT", "0.25", "REDUCE")), {"REDUCE"}),
        (("AAPL", "MSFT"), "0.10", (_position("AAPL", "0.45", "RETAIN"), _position("MSFT", "0.45", "RETAIN")), {"RETAIN"}),
    ],
    ids=["initial-deployment", "weekly-maintenance", "add-and-trim", "full-exit", "new-holding", "raise-cash", "no-new-names"],
)
def test_v2_adapter_returns_complete_auditable_targets(held: tuple[str, ...], cash: str, positions: tuple[dict[str, object], ...], expected_dispositions: set[str]) -> None:
    context = _context(*held)
    target, responses = _decide(context, _payload(context, cash, *positions))

    assert target.cash_target.weight == Decimal(cash)
    assert {position.existing_holding_disposition.value for position in target.positions} == expected_dispositions
    assert {position.security for position in target.positions if position.security in {item.security for item in context.portfolio.positions}} == {item.security for item in context.portfolio.positions}
    assert responses.calls[0]["store"] is False


def test_v2_adapter_preserves_versioned_prompt_model_and_research_provenance() -> None:
    context = _context("AAPL")
    manager = OpenAIValueManager(client=_Client(_Responses(_payload(context, "0.20", _position("AAPL", "0.80", "RETAIN")))))
    manager.decide_v2(context)

    assert manager.last_metadata.schema_version == V2_SCHEMA_VERSION
    assert manager.last_metadata.prompt_version == V2_PROMPT_VERSION
    assert ("screening_run_id", str(context.research_v3_batch.screening_run_id)) in manager.last_metadata.provenance
    assert manager.last_metadata.response_id == "response-v2"
    target = manager.decide_v2(context)
    assert target.decision_provenance is not None
    assert decode(encode(target)).decision_provenance == target.decision_provenance


def test_v2_adapter_fails_closed_for_ineligible_new_name_without_mutating_context() -> None:
    context = _context("AAPL")
    payload = _payload(context, "0.20", _position("AAPL", "0.80", "RETAIN"))
    payload["positions"].append(_position("TSLA", "0.00", "INITIATE"))  # type: ignore[index]
    original_portfolio = context.portfolio

    with pytest.raises(ValueError, match="could not be converted"):
        _decide(context, payload)

    assert context.portfolio == original_portfolio


@pytest.mark.parametrize("field", ["source_title", "target_weight", "unexpected"])
def test_v2_adapter_fails_closed_for_tampered_evidence_or_malformed_json_shape(field: str) -> None:
    context = _context("AAPL")
    payload = _payload(context, "0.20", _position("AAPL", "0.80", "RETAIN"))
    position = payload["positions"][0]  # type: ignore[index]
    if field == "source_title":
        position["evidence"][0]["source_title"] = "Invented source"  # type: ignore[index]
    elif field == "target_weight":
        position["target_weight"] = "0.80"
    else:
        payload["unexpected"] = True

    with pytest.raises(ValueError, match="could not be converted"):
        _decide(context, payload)


def test_context_fails_closed_when_explicit_v3_and_compatibility_batch_diverge() -> None:
    context = _context("AAPL")
    mismatched_batch = replace(context.research_batch, batch_id="other-research-batch")

    with pytest.raises(ValueError, match="exactly match"):
        ValueManagerDecisionContext(
            portfolio=context.portfolio,
            research_batch=mismatched_batch,
            research_v3_batch=context.research_v3_batch,
            constitution=context.constitution,
        )
