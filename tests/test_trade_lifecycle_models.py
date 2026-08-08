from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.trades import (
    ExecutedTrade,
    RejectedProposalValidationRecord,
    TradeProposal,
    ValidatedTrade,
)


def _proposal() -> TradeProposal:
    return TradeProposal(
        decision_cycle_id=uuid4(),
        portfolio_id=uuid4(),
        security=SecurityIdentity(ticker=" aapl ", security_type=" equity ", exchange=" nasdaq ", currency=" usd "),
        action="buy",
        target_weight=Decimal("0.125"),
        proposed_notional_amount=Decimal("125.9876"),
        proposed_quantity=Decimal("1.23456789"),
        price_source_timestamp=datetime(2026, 8, 10, 20, tzinfo=timezone.utc),
        reason_reference="manager-decision-1",
    )


def _validated_trade() -> ValidatedTrade:
    return ValidatedTrade(
        proposal=_proposal(),
        validation_timestamp=datetime(2026, 8, 10, 20, 1, tzinfo=timezone.utc),
        validation_results=("cash-feasibility", "ticker-eligibility"),
    )


def test_trade_proposal_constructs_a_normalized_buy_only_candidate() -> None:
    proposal = _proposal()

    assert proposal.action == "BUY"
    assert proposal.status == "PROPOSED"
    assert proposal.security.ticker == "AAPL"
    assert proposal.target_weight == Decimal("0.125")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_weight", Decimal("0")),
        ("target_weight", Decimal("1.000001")),
        ("target_weight", Decimal("0.1234567")),
        ("proposed_notional_amount", Decimal("0")),
        ("proposed_notional_amount", Decimal("-0.00001")),
        ("proposed_quantity", Decimal("0")),
        ("proposed_quantity", Decimal("1.234567891")),
    ],
)
def test_trade_proposal_rejects_invalid_financial_values(field: str, value: Decimal) -> None:
    arguments = {
        "decision_cycle_id": uuid4(),
        "portfolio_id": uuid4(),
        "security": SecurityIdentity(ticker="AAPL", security_type="EQUITY", exchange="NASDAQ", currency="USD"),
        "action": "BUY",
        "target_weight": Decimal("0.1"),
        "proposed_notional_amount": Decimal("100"),
        "proposed_quantity": Decimal("1"),
        "price_source_timestamp": datetime(2026, 8, 10, 20, tzinfo=timezone.utc),
        "reason_reference": "manager-decision-1",
    }
    arguments[field] = value

    with pytest.raises(ValueError):
        TradeProposal(**arguments)


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_trade_proposal_rejects_non_finite_financial_values(value: Decimal) -> None:
    with pytest.raises(ValueError):
        TradeProposal(
            decision_cycle_id=uuid4(),
            portfolio_id=uuid4(),
            security=SecurityIdentity(ticker="AAPL", security_type="EQUITY", exchange="NASDAQ", currency="USD"),
            action="BUY",
            target_weight=Decimal("0.1"),
            proposed_notional_amount=value,
            proposed_quantity=Decimal("1"),
            price_source_timestamp=datetime(2026, 8, 10, 20, tzinfo=timezone.utc),
            reason_reference="manager-decision-1",
        )


def test_trade_proposal_rejects_non_buy_actions_and_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="BUY"):
        TradeProposal(
            decision_cycle_id=uuid4(), portfolio_id=uuid4(), security=_proposal().security, action="HOLD",
            target_weight=Decimal("0.1"), proposed_notional_amount=Decimal("100"), proposed_quantity=Decimal("1"),
            price_source_timestamp=datetime(2026, 8, 10, 20, tzinfo=timezone.utc), reason_reference="decision",
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        TradeProposal(
            decision_cycle_id=uuid4(), portfolio_id=uuid4(), security=_proposal().security, action="BUY",
            target_weight=Decimal("0.1"), proposed_notional_amount=Decimal("100"), proposed_quantity=Decimal("1"),
            price_source_timestamp=datetime(2026, 8, 10, 20), reason_reference="decision",
        )


def test_validated_trade_preserves_proposal_lineage_without_copying_values() -> None:
    proposal = _proposal()
    validated = ValidatedTrade(
        proposal=proposal,
        validation_timestamp=datetime(2026, 8, 10, 20, 1, tzinfo=timezone.utc),
        validation_results=("cash-feasibility",),
    )

    assert validated.trade_proposal_id == proposal.trade_proposal_id
    assert validated.decision_cycle_id == proposal.decision_cycle_id
    assert validated.validated_quantity == proposal.proposed_quantity
    assert validated.validated_notional_amount == proposal.proposed_notional_amount
    assert validated.action == "BUY"

    with pytest.raises(ValueError, match="VALIDATED"):
        ValidatedTrade(
            proposal=proposal,
            validation_timestamp=datetime(2026, 8, 10, 20, 1, tzinfo=timezone.utc),
            validation_status="rejected",
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        ValidatedTrade(
            proposal=proposal,
            validation_timestamp=datetime(2026, 8, 10, 20, 1),
        )


def test_validation_results_accepts_tuples_and_lists_but_rejects_malformed_containers() -> None:
    proposal = _proposal()
    validated = ValidatedTrade(
        proposal=proposal,
        validation_timestamp=datetime(2026, 8, 10, 20, 1, tzinfo=timezone.utc),
        validation_results=["cash-feasibility"],
    )

    assert validated.validation_results == ("cash-feasibility",)

    with pytest.raises(TypeError, match="tuple or list"):
        ValidatedTrade(
            proposal=proposal,
            validation_timestamp=datetime(2026, 8, 10, 20, 1, tzinfo=timezone.utc),
            validation_results="cash-feasibility",  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="string"):
        ValidatedTrade(
            proposal=proposal,
            validation_timestamp=datetime(2026, 8, 10, 20, 1, tzinfo=timezone.utc),
            validation_results=(1,),  # type: ignore[list-item]
        )
    with pytest.raises(ValueError, match="must not be empty"):
        ValidatedTrade(
            proposal=proposal,
            validation_timestamp=datetime(2026, 8, 10, 20, 1, tzinfo=timezone.utc),
            validation_results=("",),
        )


def test_rejected_validation_record_preserves_settled_audit_fields() -> None:
    proposal = _proposal()
    record = RejectedProposalValidationRecord(
        proposal=proposal,
        rule_id="cash-feasibility",
        reason="Proposed amount exceeds available cash.",
        actual_value=Decimal("101"),
        allowed_threshold=Decimal("100"),
        validated_at=datetime(2026, 8, 10, 20, 1, tzinfo=timezone.utc),
    )

    assert record.validation_status == "REJECTED"
    assert record.proposal_id == proposal.trade_proposal_id
    assert record.decision_cycle_id == proposal.decision_cycle_id
    assert record.actual_value == Decimal("101")
    assert record.allowed_threshold == Decimal("100")

    with pytest.raises(ValueError, match="REJECTED"):
        RejectedProposalValidationRecord(
            proposal=proposal, rule_id="cash-feasibility", reason="No cash",
            validated_at=datetime(2026, 8, 10, 20, 1, tzinfo=timezone.utc), validation_status="validated",
        )
    with pytest.raises(ValueError, match="finite"):
        RejectedProposalValidationRecord(
            proposal=proposal, rule_id="cash-feasibility", reason="No cash",
            actual_value=Decimal("NaN"), validated_at=datetime(2026, 8, 10, 20, 1, tzinfo=timezone.utc),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        RejectedProposalValidationRecord(
            proposal=proposal, rule_id="cash-feasibility", reason="No cash",
            validated_at=datetime(2026, 8, 10, 20, 1),
        )


def test_rejected_validation_record_cannot_accept_mismatched_lineage_ids() -> None:
    proposal = _proposal()

    with pytest.raises(TypeError, match="unexpected keyword"):
        RejectedProposalValidationRecord(
            proposal=proposal,
            decision_cycle_id=uuid4(),  # type: ignore[call-arg]
            rule_id="cash-feasibility",
            reason="No cash",
            validated_at=datetime(2026, 8, 10, 20, 1, tzinfo=timezone.utc),
        )


def test_executed_trade_is_a_single_simulated_fill_with_validated_lineage() -> None:
    validated = _validated_trade()
    executed = ExecutedTrade(
        validated_trade=validated,
        executed_quantity=Decimal("1.23456789"),
        execution_price=Decimal("102.345678"),
        source_provider_identity="approved-provider",
        market_date=date(2026, 8, 10),
        currency="usd",
        price_convention="regular-session-close",
        executed_at=datetime(2026, 8, 11, 20, tzinfo=timezone.utc),
    )

    assert executed.validated_trade_id == validated.validated_trade_id
    assert executed.trade_proposal_id == validated.trade_proposal_id
    assert executed.action == "BUY"
    assert executed.execution_source == "SIMULATED"
    assert executed.executed_notional == Decimal("126.35268773907942")


def test_executed_trade_rejects_partial_fills_currency_mismatches_and_invalid_time_fields() -> None:
    validated = _validated_trade()
    common_arguments = {
        "validated_trade": validated,
        "executed_quantity": validated.validated_quantity,
        "execution_price": Decimal("102"),
        "source_provider_identity": "approved-provider",
        "market_date": date(2026, 8, 10),
        "currency": "USD",
        "price_convention": "regular-session-close",
        "executed_at": datetime(2026, 8, 11, 20, tzinfo=timezone.utc),
    }

    with pytest.raises(ValueError, match="partial fills"):
        ExecutedTrade(executed_quantity=Decimal("1"), **{key: value for key, value in common_arguments.items() if key != "executed_quantity"})
    with pytest.raises(ValueError, match="currency"):
        ExecutedTrade(currency="EUR", **{key: value for key, value in common_arguments.items() if key != "currency"})
    with pytest.raises(TypeError, match="date, not a datetime"):
        ExecutedTrade(market_date=datetime(2026, 8, 10, tzinfo=timezone.utc), **{key: value for key, value in common_arguments.items() if key != "market_date"})
    with pytest.raises(ValueError, match="timezone-aware"):
        ExecutedTrade(executed_at=datetime(2026, 8, 11, 20), **{key: value for key, value in common_arguments.items() if key != "executed_at"})
    with pytest.raises(ValueError, match="must not precede"):
        ExecutedTrade(
            executed_at=datetime(2026, 8, 10, 20, tzinfo=timezone.utc),
            **{key: value for key, value in common_arguments.items() if key != "executed_at"},
        )


def test_executed_trade_allows_execution_at_the_validation_timestamp() -> None:
    validated = _validated_trade()

    executed = ExecutedTrade(
        validated_trade=validated,
        executed_quantity=validated.validated_quantity,
        execution_price=Decimal("102"),
        source_provider_identity="approved-provider",
        market_date=date(2026, 8, 10),
        currency="USD",
        price_convention="regular-session-close",
        executed_at=validated.validation_timestamp,
    )

    assert executed.executed_at == validated.validation_timestamp


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("executed_quantity", Decimal("0")),
        ("executed_quantity", Decimal("-0.00000001")),
        ("execution_price", Decimal("0")),
        ("execution_price", Decimal("-0.0001")),
        ("execution_price", Decimal("NaN")),
    ],
)
def test_executed_trade_rejects_invalid_quantity_and_price(field: str, value: Decimal) -> None:
    arguments = {
        "validated_trade": _validated_trade(),
        "executed_quantity": Decimal("1.23456789"),
        "execution_price": Decimal("102"),
        "source_provider_identity": "approved-provider",
        "market_date": date(2026, 8, 10),
        "currency": "USD",
        "price_convention": "regular-session-close",
        "executed_at": datetime(2026, 8, 11, 20, tzinfo=timezone.utc),
    }
    arguments[field] = value

    with pytest.raises(ValueError):
        ExecutedTrade(**arguments)


def test_executed_notional_is_independent_of_the_ambient_decimal_context() -> None:
    def execute_under_precision(precision: int) -> Decimal:
        with localcontext() as context:
            context.prec = precision
            executed = ExecutedTrade(
                validated_trade=_validated_trade(),
                executed_quantity=Decimal("1.23456789"),
                execution_price=Decimal("102.345678"),
                source_provider_identity="approved-provider",
                market_date=date(2026, 8, 10),
                currency="USD",
                price_convention="regular-session-close",
                executed_at=datetime(2026, 8, 11, 20, tzinfo=timezone.utc),
            )
            return executed.executed_notional

    assert execute_under_precision(6) == execute_under_precision(50)
