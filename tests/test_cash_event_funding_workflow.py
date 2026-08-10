from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.cash_events import (
    CashEvent,
    CashEventFundingResult,
    CashEventFundingWorkflow,
)
from agentic_portfolio_lab.domain.portfolio import CashBalance, Contribution, Portfolio, Position, SecurityIdentity
from agentic_portfolio_lab.domain.valuation import BenchmarkPortfolio


UTC = timezone.utc


def _security(ticker: str, *, exchange: str) -> SecurityIdentity:
    return SecurityIdentity(ticker=ticker, security_type="EQUITY", exchange=exchange, currency="USD")


def _managed_portfolio() -> Portfolio:
    aapl = _security("AAPL", exchange="NASDAQ")
    return Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Value",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance(currency="USD", amount=Decimal("800")),
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
        positions=(Position(aapl, Decimal("2"), Decimal("200"), Decimal("100")),),
    )


def _benchmark_portfolio() -> BenchmarkPortfolio:
    spy = _security("SPY", exchange="NYSEARCA")
    return BenchmarkPortfolio(
        portfolio=Portfolio(
            portfolio_id=uuid4(),
            portfolio_name="Passive Index",
            base_currency="USD",
            starting_capital=Decimal("1000"),
            cash_balance=CashBalance(currency="USD", amount=Decimal("500")),
            created_at=datetime(2026, 8, 10, tzinfo=UTC),
            positions=(Position(spy, Decimal("1.25"), Decimal("500"), Decimal("400")),),
        ),
        benchmark_security=spy,
    )


def _cash_event(amount: Decimal = Decimal("250.1234"), **overrides: object) -> CashEvent:
    fields: dict[str, object] = {
        "amount": amount,
        "currency": " usd ",
        "effective_at": datetime(2026, 8, 20, 14, tzinfo=UTC),
        "source": "bank transfer",
    }
    fields.update(overrides)
    return CashEvent(**fields)  # type: ignore[arg-type]


def test_paired_funding_applies_one_cash_event_to_cash_only_and_preserves_lineage() -> None:
    managed = _managed_portfolio()
    benchmark = _benchmark_portfolio()
    cash_event = _cash_event()

    result = CashEventFundingWorkflow.apply(cash_event, managed, benchmark)

    assert result.cash_event is cash_event
    assert result.event_id == cash_event.event_id
    assert result.applied_at == cash_event.effective_at
    assert result.managed_contribution.cash_event_id == cash_event.event_id
    assert result.benchmark_contribution.cash_event_id == cash_event.event_id
    assert result.managed_contribution.contribution_id != result.benchmark_contribution.contribution_id
    assert result.funded_managed_portfolio.cash_balance.amount == Decimal("1050.1234")
    assert result.funded_benchmark_portfolio.portfolio.cash_balance.amount == Decimal("750.1234")
    assert result.funded_managed_portfolio.cash_balance.amount - managed.cash_balance.amount == cash_event.amount
    assert result.funded_benchmark_portfolio.portfolio.cash_balance.amount - benchmark.portfolio.cash_balance.amount == cash_event.amount
    assert result.funded_managed_portfolio.starting_capital == managed.starting_capital
    assert result.funded_benchmark_portfolio.portfolio.starting_capital == benchmark.portfolio.starting_capital
    assert result.funded_managed_portfolio.positions == managed.positions
    assert result.funded_benchmark_portfolio.portfolio.positions == benchmark.portfolio.positions
    assert result.funded_benchmark_portfolio.portfolio.positions[0].quantity == Decimal("1.25")


def test_paired_funding_preserves_original_immutable_portfolio_state() -> None:
    managed = _managed_portfolio()
    benchmark = _benchmark_portfolio()

    result = CashEventFundingWorkflow.apply(_cash_event(), managed, benchmark)

    assert result.funded_managed_portfolio is not managed
    assert result.funded_benchmark_portfolio is not benchmark
    assert result.funded_benchmark_portfolio.portfolio is not benchmark.portfolio
    assert managed.cash_balance.amount == Decimal("800")
    assert benchmark.portfolio.cash_balance.amount == Decimal("500")
    with pytest.raises(AttributeError):
        result.cash_event.amount = Decimal("0")  # type: ignore[misc]
    with pytest.raises(AttributeError):
        result.funded_managed_portfolio = managed  # type: ignore[misc]


def test_funding_rejects_currency_mismatch_for_either_portfolio_path() -> None:
    event = _cash_event(currency="EUR")

    with pytest.raises(ValueError, match="managed"):
        CashEventFundingWorkflow.apply(event, _managed_portfolio(), _benchmark_portfolio())

    benchmark = _benchmark_portfolio()
    eur_benchmark = BenchmarkPortfolio(
        portfolio=Portfolio(
            portfolio_id=benchmark.portfolio.portfolio_id,
            portfolio_name=benchmark.portfolio.portfolio_name,
            base_currency="EUR",
            starting_capital=benchmark.portfolio.starting_capital,
            cash_balance=CashBalance(currency="EUR", amount=benchmark.portfolio.cash_balance.amount),
            created_at=benchmark.portfolio.created_at,
            positions=(),
        ),
        benchmark_security=SecurityIdentity("SPY", "EQUITY", "XETRA", "EUR"),
    )
    with pytest.raises(ValueError, match="benchmark"):
        CashEventFundingWorkflow.apply(_cash_event(currency="USD"), _managed_portfolio(), eur_benchmark)


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")])
def test_cash_event_rejects_non_positive_or_non_finite_amounts(amount: Decimal) -> None:
    with pytest.raises(ValueError):
        _cash_event(amount)


def test_cash_event_requires_aware_effective_timestamp_and_normalizes_currency() -> None:
    event = _cash_event()
    assert event.currency == "USD"
    with pytest.raises(ValueError, match="timezone-aware"):
        _cash_event(effective_at=datetime(2026, 8, 20, 14))


def test_funding_is_independent_of_ambient_decimal_context() -> None:
    event = _cash_event(Decimal("0.12345678901234567890"))

    def funded_cash(precision: int) -> tuple[Decimal, Decimal]:
        with localcontext() as context:
            context.prec = precision
            result = CashEventFundingWorkflow.apply(event, _managed_portfolio(), _benchmark_portfolio())
            return (
                result.funded_managed_portfolio.cash_balance.amount,
                result.funded_benchmark_portfolio.portfolio.cash_balance.amount,
            )

    assert funded_cash(6) == funded_cash(50) == (
        Decimal("800.12345678901234567890"),
        Decimal("500.12345678901234567890"),
    )


def test_distinct_cash_events_accumulate_without_investing_cash() -> None:
    managed = _managed_portfolio()
    benchmark = _benchmark_portfolio()

    first = CashEventFundingWorkflow.apply(_cash_event(Decimal("100")), managed, benchmark)
    second = CashEventFundingWorkflow.apply(
        _cash_event(Decimal("25"), effective_at=datetime(2026, 8, 21, 14, tzinfo=UTC)),
        first.funded_managed_portfolio,
        first.funded_benchmark_portfolio,
    )

    assert second.funded_managed_portfolio.cash_balance.amount == Decimal("925")
    assert second.funded_benchmark_portfolio.portfolio.cash_balance.amount == Decimal("625")
    assert second.funded_managed_portfolio.positions == managed.positions
    assert second.funded_benchmark_portfolio.portfolio.positions == benchmark.portfolio.positions


def test_same_cash_event_applied_twice_deposits_twice() -> None:
    managed = _managed_portfolio()
    benchmark = _benchmark_portfolio()
    event = _cash_event(Decimal("100"))

    first = CashEventFundingWorkflow.apply(event, managed, benchmark)
    second = CashEventFundingWorkflow.apply(
        event,
        first.funded_managed_portfolio,
        first.funded_benchmark_portfolio,
    )

    assert second.funded_managed_portfolio.cash_balance.amount == Decimal("1000")
    assert second.funded_benchmark_portfolio.portfolio.cash_balance.amount == Decimal("700")


def test_funding_preserves_non_null_decision_cycle_ids() -> None:
    managed = replace(_managed_portfolio(), decision_cycle_id=uuid4())
    benchmark = _benchmark_portfolio()
    benchmark = BenchmarkPortfolio(
        portfolio=replace(benchmark.portfolio, decision_cycle_id=uuid4()),
        benchmark_security=benchmark.benchmark_security,
    )

    result = CashEventFundingWorkflow.apply(_cash_event(), managed, benchmark)

    assert result.funded_managed_portfolio.decision_cycle_id == managed.decision_cycle_id
    assert result.funded_benchmark_portfolio.portfolio.decision_cycle_id == benchmark.portfolio.decision_cycle_id


def test_result_rejects_direct_construction_that_changes_non_cash_state() -> None:
    managed = _managed_portfolio()
    benchmark = _benchmark_portfolio()
    event = _cash_event()
    result = CashEventFundingWorkflow.apply(event, managed, benchmark)

    changed_positions = replace(result.funded_managed_portfolio, positions=())
    with pytest.raises(ValueError, match="only managed portfolio cash"):
        CashEventFundingResult(
            cash_event=event,
            original_managed_portfolio=managed,
            funded_managed_portfolio=changed_positions,
            original_benchmark_portfolio=benchmark,
            funded_benchmark_portfolio=result.funded_benchmark_portfolio,
            managed_contribution=result.managed_contribution,
            benchmark_contribution=result.benchmark_contribution,
        )


@pytest.mark.parametrize(
    "substitute_event",
    [
        lambda event: replace(event, event_id=uuid4()),
        lambda event: replace(event, effective_at=datetime(2026, 8, 21, 14, tzinfo=UTC)),
        lambda event: replace(event, source="another bank"),
    ],
    ids=["event-id", "effective-at", "source"],
)
def test_result_rejects_substitute_cash_event_with_matching_amount_and_currency(
    substitute_event: Callable[[CashEvent], CashEvent],
) -> None:
    managed = _managed_portfolio()
    benchmark = _benchmark_portfolio()
    event = _cash_event()
    result = CashEventFundingWorkflow.apply(event, managed, benchmark)

    with pytest.raises(ValueError, match="CashEvent"):
        CashEventFundingResult(
            cash_event=substitute_event(event),
            original_managed_portfolio=managed,
            funded_managed_portfolio=result.funded_managed_portfolio,
            original_benchmark_portfolio=benchmark,
            funded_benchmark_portfolio=result.funded_benchmark_portfolio,
            managed_contribution=result.managed_contribution,
            benchmark_contribution=result.benchmark_contribution,
        )


@pytest.mark.parametrize(
    "tamper_contribution",
    [
        lambda contribution: replace(contribution, amount=Decimal("1")),
        lambda contribution: replace(contribution, currency="EUR"),
        lambda contribution: replace(contribution, cash_event_id=uuid4()),
        lambda contribution: replace(
            contribution,
            effective_at=datetime(2026, 8, 21, 14, tzinfo=UTC),
        ),
        lambda contribution: replace(
            contribution,
            received_at=datetime(2026, 8, 21, 14, tzinfo=UTC),
        ),
        lambda contribution: replace(contribution, source="another bank"),
    ],
    ids=["amount", "currency", "event-id", "effective-at", "received-at", "source"],
)
def test_result_rejects_tampered_managed_contribution(
    tamper_contribution: Callable[[Contribution], Contribution],
) -> None:
    managed = _managed_portfolio()
    benchmark = _benchmark_portfolio()
    result = CashEventFundingWorkflow.apply(_cash_event(), managed, benchmark)

    with pytest.raises(ValueError):
        CashEventFundingResult(
            cash_event=result.cash_event,
            original_managed_portfolio=managed,
            funded_managed_portfolio=result.funded_managed_portfolio,
            original_benchmark_portfolio=benchmark,
            funded_benchmark_portfolio=result.funded_benchmark_portfolio,
            managed_contribution=tamper_contribution(result.managed_contribution),
            benchmark_contribution=result.benchmark_contribution,
        )


def test_result_rejects_reusing_one_contribution_for_both_portfolio_paths() -> None:
    managed = _managed_portfolio()
    benchmark = _benchmark_portfolio()
    result = CashEventFundingWorkflow.apply(_cash_event(), managed, benchmark)

    with pytest.raises(ValueError, match="distinct contribution_id"):
        CashEventFundingResult(
            cash_event=result.cash_event,
            original_managed_portfolio=managed,
            funded_managed_portfolio=result.funded_managed_portfolio,
            original_benchmark_portfolio=benchmark,
            funded_benchmark_portfolio=result.funded_benchmark_portfolio,
            managed_contribution=result.managed_contribution,
            benchmark_contribution=result.managed_contribution,
        )


def test_result_rejects_direct_construction_with_changed_starting_capital() -> None:
    managed = _managed_portfolio()
    benchmark = _benchmark_portfolio()
    result = CashEventFundingWorkflow.apply(_cash_event(), managed, benchmark)

    with pytest.raises(ValueError, match="only managed portfolio cash"):
        CashEventFundingResult(
            cash_event=result.cash_event,
            original_managed_portfolio=managed,
            funded_managed_portfolio=replace(result.funded_managed_portfolio, starting_capital=Decimal("1001")),
            original_benchmark_portfolio=benchmark,
            funded_benchmark_portfolio=result.funded_benchmark_portfolio,
            managed_contribution=result.managed_contribution,
            benchmark_contribution=result.benchmark_contribution,
        )


def test_result_rejects_direct_construction_with_changed_benchmark_holdings() -> None:
    managed = _managed_portfolio()
    benchmark = _benchmark_portfolio()
    result = CashEventFundingWorkflow.apply(_cash_event(), managed, benchmark)
    changed_position = replace(result.funded_benchmark_portfolio.portfolio.positions[0], market_price=Decimal("401"))
    changed_benchmark = BenchmarkPortfolio(
        portfolio=replace(result.funded_benchmark_portfolio.portfolio, positions=(changed_position,)),
        benchmark_security=benchmark.benchmark_security,
    )

    with pytest.raises(ValueError, match="only benchmark portfolio cash"):
        CashEventFundingResult(
            cash_event=result.cash_event,
            original_managed_portfolio=managed,
            funded_managed_portfolio=result.funded_managed_portfolio,
            original_benchmark_portfolio=benchmark,
            funded_benchmark_portfolio=changed_benchmark,
            managed_contribution=result.managed_contribution,
            benchmark_contribution=result.benchmark_contribution,
        )


def test_result_rejects_direct_construction_with_currency_mismatch() -> None:
    managed = _managed_portfolio()
    benchmark = _benchmark_portfolio()
    result = CashEventFundingWorkflow.apply(_cash_event(), managed, benchmark)

    with pytest.raises(ValueError, match="currency"):
        CashEventFundingResult(
            cash_event=replace(result.cash_event, currency="EUR"),
            original_managed_portfolio=managed,
            funded_managed_portfolio=result.funded_managed_portfolio,
            original_benchmark_portfolio=benchmark,
            funded_benchmark_portfolio=result.funded_benchmark_portfolio,
            managed_contribution=replace(result.managed_contribution, currency="EUR"),
            benchmark_contribution=replace(result.benchmark_contribution, currency="EUR"),
        )


def test_result_rejects_direct_construction_with_incorrect_cash_delta() -> None:
    managed = _managed_portfolio()
    benchmark = _benchmark_portfolio()
    result = CashEventFundingWorkflow.apply(_cash_event(), managed, benchmark)
    incorrect_cash = replace(
        result.funded_managed_portfolio,
        cash_balance=CashBalance(currency="USD", amount=Decimal("999")),
    )

    with pytest.raises(ValueError, match="cash must increase"):
        CashEventFundingResult(
            cash_event=result.cash_event,
            original_managed_portfolio=managed,
            funded_managed_portfolio=incorrect_cash,
            original_benchmark_portfolio=benchmark,
            funded_benchmark_portfolio=result.funded_benchmark_portfolio,
            managed_contribution=result.managed_contribution,
            benchmark_contribution=result.benchmark_contribution,
        )


@pytest.mark.parametrize("portfolio_path", ["managed", "benchmark"])
def test_funding_rejects_event_effective_before_portfolio_creation(portfolio_path: str) -> None:
    managed = _managed_portfolio()
    benchmark = _benchmark_portfolio()
    if portfolio_path == "managed":
        managed = replace(managed, created_at=datetime(2026, 8, 21, tzinfo=UTC))
    else:
        benchmark = BenchmarkPortfolio(
            portfolio=replace(benchmark.portfolio, created_at=datetime(2026, 8, 21, tzinfo=UTC)),
            benchmark_security=benchmark.benchmark_security,
        )

    with pytest.raises(ValueError, match=portfolio_path):
        CashEventFundingWorkflow.apply(_cash_event(), managed, benchmark)


def test_funding_allows_event_effective_exactly_at_portfolio_creation() -> None:
    created_at = datetime(2026, 8, 20, 14, tzinfo=UTC)
    managed = replace(_managed_portfolio(), created_at=created_at)
    benchmark = _benchmark_portfolio()
    benchmark = BenchmarkPortfolio(
        portfolio=replace(benchmark.portfolio, created_at=created_at),
        benchmark_security=benchmark.benchmark_security,
    )

    result = CashEventFundingWorkflow.apply(_cash_event(), managed, benchmark)

    assert result.applied_at == created_at


def test_funding_rejects_shared_managed_and_benchmark_portfolio_identity() -> None:
    managed = _managed_portfolio()
    benchmark = _benchmark_portfolio()
    benchmark = BenchmarkPortfolio(
        portfolio=replace(benchmark.portfolio, portfolio_id=managed.portfolio_id),
        benchmark_security=benchmark.benchmark_security,
    )

    with pytest.raises(ValueError, match="distinct"):
        CashEventFundingWorkflow.apply(_cash_event(), managed, benchmark)
