from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.cash_events import CashEvent, CashEventFundingWorkflow
from agentic_portfolio_lab.domain.constitution import (
    NEXT_APPLICABLE_REGULAR_SESSION_CLOSE,
    PassiveIndexConstitution,
    PassiveIndexInvestmentIntent,
)
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio, Position, SecurityIdentity
from agentic_portfolio_lab.domain.valuation import BenchmarkPortfolio


UTC = timezone.utc


def _spy() -> SecurityIdentity:
    return SecurityIdentity("SPY", "ETF", "NYSEARCA", "USD")


def _benchmark(*, cash: Decimal, positions: tuple[Position, ...] = ()) -> BenchmarkPortfolio:
    return BenchmarkPortfolio(
        portfolio=Portfolio(
            portfolio_id=uuid4(),
            portfolio_name="Passive Index",
            base_currency="USD",
            starting_capital=Decimal("1000"),
            cash_balance=CashBalance("USD", cash),
            created_at=datetime(2026, 8, 10, tzinfo=UTC),
            positions=positions,
        ),
        benchmark_security=_spy(),
    )


def _managed() -> Portfolio:
    return Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Value",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance("USD", Decimal("0")),
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


def _cash_event(amount: Decimal, *, effective_at: datetime) -> CashEvent:
    return CashEvent(amount=amount, currency="USD", effective_at=effective_at, source="bank transfer")


def test_zero_cash_produces_no_intent() -> None:
    assert PassiveIndexConstitution().evaluate(_benchmark(cash=Decimal("0"))) is None


def test_positive_cash_produces_one_full_cash_spy_intent() -> None:
    benchmark = _benchmark(cash=Decimal("250.1234"))

    intent = PassiveIndexConstitution().evaluate(benchmark)

    assert intent == PassiveIndexInvestmentIntent(
        benchmark_portfolio=benchmark,
        action="BUY",
        deployment_rule=NEXT_APPLICABLE_REGULAR_SESSION_CLOSE,
        constitution_version="passive-index-v1.0.0",
    )


def test_intent_and_constitution_are_immutable_and_do_not_mutate_portfolio() -> None:
    benchmark = _benchmark(cash=Decimal("100"))
    constitution = PassiveIndexConstitution()

    intent = constitution.evaluate(benchmark)

    assert intent is not None
    assert benchmark.portfolio.cash_balance.amount == Decimal("100")
    with pytest.raises(FrozenInstanceError):
        intent.action = "HOLD"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        constitution.version = constitution.version  # type: ignore[misc]


def test_decimal_context_does_not_change_intent_cash() -> None:
    benchmark = _benchmark(cash=Decimal("123.12345678901234567890"))

    def intent_cash(precision: int) -> Decimal:
        with localcontext() as context:
            context.prec = precision
            intent = PassiveIndexConstitution().evaluate(benchmark)
            assert intent is not None
            return intent.investable_cash

    assert intent_cash(6) == intent_cash(50) == Decimal("123.12345678901234567890")


def test_repeated_cash_events_before_execution_accumulate_into_one_intent() -> None:
    managed = _managed()
    benchmark = _benchmark(cash=Decimal("0"))
    first = CashEventFundingWorkflow.apply(
        _cash_event(Decimal("100"), effective_at=datetime(2026, 8, 11, tzinfo=UTC)),
        managed,
        benchmark,
    )
    second = CashEventFundingWorkflow.apply(
        _cash_event(Decimal("25"), effective_at=datetime(2026, 8, 12, tzinfo=UTC)),
        first.funded_managed_portfolio,
        first.funded_benchmark_portfolio,
    )

    intent = PassiveIndexConstitution().evaluate(second.funded_benchmark_portfolio)

    assert intent is not None
    assert intent.investable_cash == Decimal("125")
    assert intent.benchmark_portfolio_id == benchmark.portfolio.portfolio_id


def test_existing_spy_position_does_not_reduce_new_cash_deployment() -> None:
    spy_position = Position(_spy(), Decimal("2"), Decimal("800"), Decimal("400"))
    benchmark = _benchmark(cash=Decimal("125"), positions=(spy_position,))

    intent = PassiveIndexConstitution().evaluate(benchmark)

    assert intent is not None
    assert intent.investable_cash == Decimal("125")
    assert intent.security == spy_position.security


@pytest.mark.parametrize(
    ("derived_field", "substitute_value"),
    [
        ("benchmark_portfolio_id", uuid4()),
        ("security", SecurityIdentity("AAPL", "EQUITY", "NASDAQ", "USD")),
        ("investable_cash", Decimal("500")),
        ("currency", "EUR"),
    ],
    ids=["portfolio-id", "security", "partial-cash", "currency"],
)
def test_intent_cannot_accept_substituted_derived_benchmark_state(
    derived_field: str,
    substitute_value: object,
) -> None:
    with pytest.raises(TypeError, match="unexpected keyword"):
        PassiveIndexInvestmentIntent(
            benchmark_portfolio=_benchmark(cash=Decimal("1000")),
            action="BUY",
            deployment_rule=NEXT_APPLICABLE_REGULAR_SESSION_CLOSE,
            constitution_version="passive-index-v1.0.0",
            **{derived_field: substitute_value},  # type: ignore[call-arg]
        )


def test_intent_derives_all_benchmark_state_from_its_reference() -> None:
    benchmark = _benchmark(cash=Decimal("1000"))
    intent = PassiveIndexInvestmentIntent(
        benchmark_portfolio=benchmark,
        action="BUY",
        deployment_rule=NEXT_APPLICABLE_REGULAR_SESSION_CLOSE,
        constitution_version="passive-index-v1.0.0",
    )

    assert intent.benchmark_portfolio is benchmark
    assert intent.benchmark_portfolio_id == benchmark.portfolio.portfolio_id
    assert intent.security is benchmark.benchmark_security
    assert intent.investable_cash == benchmark.portfolio.cash_balance.amount
    assert intent.currency == benchmark.portfolio.base_currency


def test_non_spy_benchmark_cannot_produce_or_back_an_intent() -> None:
    aapl = SecurityIdentity("AAPL", "EQUITY", "NASDAQ", "USD")
    with pytest.raises(ValueError, match="SPY"):
        BenchmarkPortfolio(
            portfolio=_benchmark(cash=Decimal("1")).portfolio,
            benchmark_security=aapl,
        )


def test_intent_rejects_unsupported_policy_fields() -> None:
    with pytest.raises(ValueError, match="deployment_rule"):
        PassiveIndexInvestmentIntent(
            benchmark_portfolio=_benchmark(cash=Decimal("1")),
            action="BUY",
            deployment_rule="AT_NOW",
            constitution_version="passive-index-v1.0.0",
        )
    with pytest.raises(ValueError, match="action"):
        PassiveIndexInvestmentIntent(
            benchmark_portfolio=_benchmark(cash=Decimal("1")),
            action="HOLD",
            deployment_rule=NEXT_APPLICABLE_REGULAR_SESSION_CLOSE,
            constitution_version="passive-index-v1.0.0",
        )
    with pytest.raises(ValueError, match="constitution_version"):
        PassiveIndexInvestmentIntent(
            benchmark_portfolio=_benchmark(cash=Decimal("1")),
            action="BUY",
            deployment_rule=NEXT_APPLICABLE_REGULAR_SESSION_CLOSE,
            constitution_version="passive-index-v2.0.0",
        )


def test_direct_intent_construction_rejects_zero_cash_benchmark() -> None:
    with pytest.raises(ValueError, match="investable_cash"):
        PassiveIndexInvestmentIntent(
            benchmark_portfolio=_benchmark(cash=Decimal("0")),
            action="BUY",
            deployment_rule=NEXT_APPLICABLE_REGULAR_SESSION_CLOSE,
            constitution_version="passive-index-v1.0.0",
        )


def test_repeated_evaluation_of_identical_benchmark_state_is_equal() -> None:
    benchmark = _benchmark(cash=Decimal("100"))
    constitution = PassiveIndexConstitution()

    assert constitution.evaluate(benchmark) == constitution.evaluate(benchmark)


@pytest.mark.parametrize("cash", [Decimal("-1"), Decimal("NaN"), Decimal("Infinity")])
def test_invalid_benchmark_cash_is_rejected_by_existing_domain_invariants(cash: Decimal) -> None:
    with pytest.raises(ValueError):
        _benchmark(cash=cash)


def test_constitution_has_no_execution_or_provider_dependencies() -> None:
    intent = PassiveIndexConstitution().evaluate(_benchmark(cash=Decimal("1")))

    assert intent is not None
    assert PassiveIndexConstitution.__module__ == "agentic_portfolio_lab.domain.constitution"
    assert not hasattr(PassiveIndexConstitution, "execute")
    assert not hasattr(PassiveIndexConstitution, "schedule")
    assert not hasattr(intent, "execution_price")
    assert not hasattr(intent, "execution_timestamp")
    assert not hasattr(intent, "provider")
