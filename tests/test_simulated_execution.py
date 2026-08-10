from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from agentic_portfolio_lab.domain.approval import ApprovalDecision, DecisionApproval
from agentic_portfolio_lab.domain.portfolio import CashBalance, Position, SecurityIdentity
from agentic_portfolio_lab.domain.reviewer import ReviewDecision
from agentic_portfolio_lab.domain.simulated_execution import SimulatedExecutionResult, SimulatedExecutionWorkflow
from agentic_portfolio_lab.domain.valuation import PriceObservation
from tests.test_decision_approval import DECIDED_AT, _journal_entry


def _approval(*, decision: str = "APPROVED", action: str = "BUY", passed: bool = True, reviewer_decision=None):
    return DecisionApproval(_journal_entry(action=action, passed=passed, reviewer_decision=reviewer_decision), "user", decision, DECIDED_AT)


def _observation(approval: DecisionApproval, *, price: Decimal = Decimal("100"), **overrides: object) -> PriceObservation:
    trade = approval.journal_entry.risk_validation_result.validated_trade
    assert trade is not None
    fields: dict[str, object] = {
        "security": trade.security,
        "observed_price": price,
        "market_date": DECIDED_AT.date(),
        "observed_at": DECIDED_AT,
        "currency": "USD",
        "source_provider_identity": "execution-provider",
        "price_convention": "regular-session-close",
    }
    fields.update(overrides)
    return PriceObservation(**fields)  # type: ignore[arg-type]


def test_approved_buy_executes_with_execution_observation_provenance() -> None:
    approval = _approval()
    portfolio = approval.journal_entry.decision_result.context.portfolio
    observation = _observation(approval)

    result = SimulatedExecutionWorkflow.execute(approval, portfolio, observation, executed_at=DECIDED_AT)

    assert result.execution_observation is observation
    assert result.executed_trade.execution_price == observation.observed_price
    assert result.updated_portfolio.cash_balance.amount == Decimal("900.00000000")
    assert portfolio.cash_balance.amount == Decimal("1000")
    assert result.executed_trade.decision_cycle_id == approval.decision_cycle_id


@pytest.mark.parametrize("decision", ["REJECTED", "EXPIRED"])
def test_non_approved_buy_cannot_execute(decision: str) -> None:
    approval = _approval(decision=decision)
    with pytest.raises(ValueError, match="APPROVED"):
        SimulatedExecutionWorkflow.execute(approval, approval.journal_entry.decision_result.context.portfolio, _observation(_approval()), executed_at=DECIDED_AT)


def test_hold_and_failed_validation_cannot_execute() -> None:
    hold = _approval(action="HOLD")
    with pytest.raises(ValueError, match="passed BUY"):
        SimulatedExecutionWorkflow.execute(hold, hold.journal_entry.decision_result.context.portfolio, _observation(_approval()), executed_at=DECIDED_AT)
    with pytest.raises(ValueError, match="passed deterministic validation"):
        _approval(passed=False)


def test_changed_execution_price_recalculates_quantity_without_overspending() -> None:
    approval = _approval()
    portfolio = approval.journal_entry.decision_result.context.portfolio
    higher = SimulatedExecutionWorkflow.execute(approval, portfolio, _observation(approval, price=Decimal("200")), executed_at=DECIDED_AT)
    lower = SimulatedExecutionWorkflow.execute(approval, portfolio, _observation(approval, price=Decimal("50")), executed_at=DECIDED_AT)

    assert higher.executed_trade.executed_quantity == Decimal("0.50000000")
    assert lower.executed_trade.executed_quantity == Decimal("2.00000000")
    assert higher.executed_trade.executed_notional <= portfolio.cash_balance.amount


def test_request_changes_reviewer_does_not_override_human_approval() -> None:
    approval = _approval(reviewer_decision=ReviewDecision.REQUEST_CHANGES)
    portfolio = approval.journal_entry.decision_result.context.portfolio

    result = SimulatedExecutionWorkflow.execute(approval, portfolio, _observation(approval), executed_at=DECIDED_AT)

    assert result.executed_trade.action == "BUY"


def test_insufficient_or_already_at_target_current_state_fails_without_mutation() -> None:
    approval = _approval()
    original = approval.journal_entry.decision_result.context.portfolio
    insufficient = replace(
        original,
        cash_balance=CashBalance("USD", Decimal("1")),
        positions=(
            Position(
                SecurityIdentity("MSFT", "EQUITY", "NASDAQ", "USD"),
                Decimal("10"),
                Decimal("1000"),
                Decimal("100"),
            ),
        ),
    )
    at_target = replace(
        original,
        positions=(Position(_observation(approval).security, Decimal("100"), Decimal("10000"), Decimal("100")),),
    )
    observation = _observation(approval)

    with pytest.raises(ValueError, match="cash-feasible"):
        SimulatedExecutionWorkflow.execute(approval, insufficient, observation, executed_at=DECIDED_AT)
    with pytest.raises(ValueError, match="quantity must be positive"):
        SimulatedExecutionWorkflow.execute(approval, at_target, observation, executed_at=DECIDED_AT)
    assert insufficient.cash_balance.amount == Decimal("1")
    assert at_target.positions[0].quantity == Decimal("100")


def test_execution_rejects_observation_before_approval_and_wrong_security() -> None:
    approval = _approval()
    portfolio = approval.journal_entry.decision_result.context.portfolio
    with pytest.raises(ValueError, match="precede"):
        SimulatedExecutionWorkflow.execute(approval, portfolio, _observation(approval), executed_at=DECIDED_AT - timedelta(seconds=1))
    with pytest.raises(ValueError, match="observation must not precede approval"):
        SimulatedExecutionWorkflow.execute(
            approval,
            portfolio,
            _observation(approval, observed_at=DECIDED_AT - timedelta(seconds=1)),
            executed_at=DECIDED_AT,
        )
    with pytest.raises(ValueError, match="security"):
        SimulatedExecutionWorkflow.execute(
            approval,
            portfolio,
            _observation(approval, security=replace(_observation(approval).security, ticker="MSFT")),
            executed_at=DECIDED_AT,
        )


def test_observation_and_execution_time_equality_boundaries_are_allowed() -> None:
    approval = _approval()
    portfolio = approval.journal_entry.decision_result.context.portfolio
    observation = _observation(approval, observed_at=DECIDED_AT)

    result = SimulatedExecutionWorkflow.execute(approval, portfolio, observation, executed_at=DECIDED_AT)

    assert result.executed_trade.executed_at == observation.observed_at == approval.decided_at


@pytest.mark.parametrize("field", ["source_provider_identity", "market_date", "price_convention"])
def test_result_rejects_trade_provenance_mismatch(field: str) -> None:
    approval = _approval()
    portfolio = approval.journal_entry.decision_result.context.portfolio
    result = SimulatedExecutionWorkflow.execute(approval, portfolio, _observation(approval), executed_at=DECIDED_AT)
    values = {
        "source_provider_identity": "other-provider",
        "market_date": DECIDED_AT.date() - timedelta(days=1),
        "price_convention": "other-convention",
    }
    mismatched_trade = replace(result.executed_trade, **{field: values[field]})

    with pytest.raises(ValueError, match="execution observation"):
        SimulatedExecutionResult(
            result.approval,
            result.original_portfolio,
            result.execution_observation,
            result.execution_target_purchase,
            mismatched_trade,
            result.updated_portfolio,
        )


def test_execution_is_decimal_context_independent() -> None:
    approval = _approval()
    portfolio = approval.journal_entry.decision_result.context.portfolio
    observation = _observation(approval, price=Decimal("123.456789"))
    def quantity(precision: int) -> Decimal:
        with localcontext() as context:
            context.prec = precision
            return SimulatedExecutionWorkflow.execute(approval, portfolio, observation, executed_at=DECIDED_AT).executed_trade.executed_quantity
    assert quantity(6) == quantity(50)
