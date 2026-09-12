from datetime import date
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain import (
    CashClassification, CashTarget, ExistingHoldingDisposition, PortfolioRecommendation,
    PortfolioTargetAllocation, PortfolioTargetPosition, RecommendationEvidenceReference, ReviewTrigger,
)
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity


def evidence(identifier: str = "ev-1") -> RecommendationEvidenceReference:
    return RecommendationEvidenceReference(identifier, "filing", "Annual report", date(2026, 1, 1), "Supports thesis")


def position(ticker: str, weight: str, disposition: str = "INITIATE") -> PortfolioTargetPosition:
    return PortfolioTargetPosition(SecurityIdentity(ticker, "EQUITY", "NASDAQ", "USD"), Decimal(weight), "compounder", "Durable cash generation.", 80, [evidence(ticker)], ["Cash generation fails."], [ReviewTrigger("scheduled", "Review quarterly.")], disposition)


def target(*positions: PortfolioTargetPosition, cash: str = "0.200000", classification: str = "STRATEGIC") -> PortfolioTargetAllocation:
    return PortfolioTargetAllocation(uuid4(), "Balanced target", "Moderate risk", "Diversified exposures", "Active risk is intentional", CashTarget(Decimal(cash), classification, "Reserve for optionality."), list(positions))


def test_complete_target_is_immutable_and_exactly_accounted_for() -> None:
    result = target(position("AAPL", "0.400000"), position("MSFT", "0.400000"))
    assert result.cash_target.classification is CashClassification.STRATEGIC
    assert result.positions[0].existing_holding_disposition is ExistingHoldingDisposition.INITIATE
    with pytest.raises(AttributeError):
        result.positions.append(position("IBM", "0.1"))  # type: ignore[attr-defined]


@pytest.mark.parametrize("disposition", ["RETAIN", "INCREASE", "REDUCE"])
def test_existing_position_dispositions_are_explicit(disposition: str) -> None:
    assert target(position("AAPL", "0.800000", disposition)).positions[0].existing_holding_disposition.value == disposition


def test_remove_and_zero_targets_are_supported() -> None:
    assert target(position("AAPL", "0", "REMOVE"), cash="1.000000").positions[0].target_weight == Decimal("0")


def test_validation_rejects_duplicate_unsupported_missing_evidence_and_bad_weights() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        target(position("AAPL", "0.4"), position(" aapl ", "0.4"))
    with pytest.raises(ValueError, match="unsupported"):
        PortfolioTargetPosition(SecurityIdentity("BOND", "MUTUAL_FUND", "NASDAQ", "USD"), Decimal("0.1"), "role", "thesis", 50, [evidence()], [], [], "INITIATE")
    with pytest.raises(ValueError, match="require evidence"):
        PortfolioTargetPosition(SecurityIdentity("AAPL", "EQUITY", "NASDAQ", "USD"), Decimal("0.1"), "role", "thesis", 50, [], [], [], "INITIATE", True)
    with pytest.raises(ValueError, match="at most 6"):
        position("AAPL", "0.1000001")


@pytest.mark.parametrize("identity", [
    SecurityIdentity("AAPL!", "EQUITY", "NASDAQ", "USD"),
    SecurityIdentity("AAPL", "EQUITY", "NASDAQ-1", "USD"),
])
def test_validation_rejects_malformed_security_identity(identity: SecurityIdentity) -> None:
    with pytest.raises(ValueError, match="malformed"):
        PortfolioTargetPosition(identity, Decimal("0.1"), "role", "thesis", 50, [evidence()], [], [], "INITIATE")


def test_validation_rejects_string_invalidation_conditions() -> None:
    with pytest.raises(TypeError, match="tuple or list"):
        PortfolioTargetPosition(SecurityIdentity("AAPL", "EQUITY", "NASDAQ", "USD"), Decimal("0.1"), "role", "thesis", 50, [evidence()], "abc", [], "INITIATE")  # type: ignore[arg-type]


@pytest.mark.parametrize("disposition", ["INITIATE", "RETAIN", "INCREASE", "REDUCE"])
def test_zero_target_requires_remove_disposition(disposition: str) -> None:
    with pytest.raises(ValueError, match="requires REMOVE"):
        position("AAPL", "0", disposition)


def test_target_total_ignores_ambient_decimal_precision() -> None:
    with localcontext() as context:
        context.prec = 1
        with pytest.raises(ValueError, match="equal exactly"):
            target(position("AAPL", "0.44"), position("MSFT", "0.44"), cash="0.200000")


def test_invalid_totals_and_remove_semantics_are_rejected() -> None:
    with pytest.raises(ValueError, match="equal exactly"):
        target(position("AAPL", "0.400000"), cash="0.400000")
    with pytest.raises(ValueError, match="zero target"):
        position("AAPL", "0.100000", "REMOVE")


def test_v1_contract_remains_unchanged_and_constructible() -> None:
    recommendation = PortfolioRecommendation("HOLD", None, None, "No opportunity.", None, "Insufficient valuation.", ["Risk"], 50, [evidence()], "SPY remains preferable.", [], [])
    assert recommendation.action.value == "HOLD"
