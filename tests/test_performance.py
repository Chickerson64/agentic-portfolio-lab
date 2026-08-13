from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

import pytest

from agentic_portfolio_lab.domain.cash_events import CashEvent
from agentic_portfolio_lab.domain.performance import (
    BenchmarkPerformanceHistory,
    PerformanceComparison,
    PortfolioPerformanceHistory,
)
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio, Position, SecurityIdentity
from agentic_portfolio_lab.domain.valuation import BenchmarkPortfolio, PortfolioValuation, PriceObservation


UTC = timezone.utc
CREATED_AT = datetime(2026, 8, 10, 12, tzinfo=UTC)
BASELINE_AT = CREATED_AT + timedelta(days=1)
NEXT_AT = CREATED_AT + timedelta(days=2)
LATER_AT = CREATED_AT + timedelta(days=3)


def _portfolio(
    cash: Decimal,
    *,
    currency: str = "USD",
    portfolio_id: UUID | None = None,
    positions: tuple[Position, ...] = (),
    starting_capital: Decimal = Decimal("1000"),
    created_at: datetime = CREATED_AT,
) -> Portfolio:
    return Portfolio(
        portfolio_id=portfolio_id or uuid4(),
        portfolio_name="Performance Portfolio",
        base_currency=currency,
        starting_capital=starting_capital,
        cash_balance=CashBalance(currency, cash),
        created_at=created_at,
        positions=positions,
    )


def _benchmark(
    cash: Decimal,
    *,
    currency: str = "USD",
    portfolio_id: UUID | None = None,
    starting_capital: Decimal = Decimal("1000"),
) -> BenchmarkPortfolio:
    spy = SecurityIdentity("SPY", "ETF", "NYSEARCA", currency)
    return BenchmarkPortfolio(
        _portfolio(cash, currency=currency, portfolio_id=portfolio_id, starting_capital=starting_capital),
        spy,
    )


def _valuation(
    portfolio: Portfolio,
    *,
    timestamp: datetime,
    prices: dict[SecurityIdentity, Decimal] | None = None,
    provider: str = "test-provider",
    market_date=None,
    source_price_timestamp: datetime | None = None,
    price_convention: str = "regular-session-close",
) -> PortfolioValuation:
    prices = prices or {}
    source_price_timestamp = source_price_timestamp or timestamp
    observations = tuple(
        PriceObservation(
            security=position.security,
            observed_price=prices[position.security],
            market_date=market_date or timestamp.date(),
            observed_at=source_price_timestamp,
            currency=portfolio.base_currency,
            source_provider_identity=provider,
            price_convention=price_convention,
        )
        for position in portfolio.positions
    )
    return PortfolioValuation.from_portfolio(
        portfolio,
        observations,
        as_of_timestamp=timestamp,
        market_date=market_date or timestamp.date(),
        source_price_timestamp=source_price_timestamp,
        source_provider_identity=provider,
        price_convention=price_convention,
    )


def _cash_event(amount: Decimal, *, effective_at: datetime = NEXT_AT, event_id: UUID | None = None) -> CashEvent:
    return CashEvent(
        amount=amount,
        currency="USD",
        effective_at=effective_at,
        source="manual funding",
        event_id=event_id or uuid4(),
    )


def _cash_histories(
    *,
    baseline_value: Decimal = Decimal("1000"),
    managed_value: Decimal = Decimal("1000"),
    benchmark_value: Decimal = Decimal("1000"),
    cash_events: tuple[CashEvent, ...] = (),
) -> tuple[PortfolioPerformanceHistory, BenchmarkPerformanceHistory]:
    managed_id = uuid4()
    benchmark_id = uuid4()
    managed = PortfolioPerformanceHistory(managed_id, "USD")
    benchmark = _benchmark(baseline_value, portfolio_id=benchmark_id)
    benchmark_history = BenchmarkPerformanceHistory.for_benchmark(benchmark)
    baseline_managed = _portfolio(baseline_value, portfolio_id=managed_id)
    managed = managed.append(baseline_managed, _valuation(baseline_managed, timestamp=BASELINE_AT))
    benchmark_history = benchmark_history.append(benchmark, _valuation(benchmark.portfolio, timestamp=BASELINE_AT))

    current_managed = _portfolio(managed_value, portfolio_id=managed_id)
    current_benchmark = _benchmark(benchmark_value, portfolio_id=benchmark_id)
    managed = managed.append(current_managed, _valuation(current_managed, timestamp=NEXT_AT), cash_events=cash_events)
    benchmark_history = benchmark_history.append(
        current_benchmark,
        _valuation(current_benchmark.portfolio, timestamp=NEXT_AT),
        cash_events=cash_events,
    )
    return managed, benchmark_history


def test_cash_only_portfolio_snapshot_requires_no_trade() -> None:
    portfolio = _portfolio(Decimal("1000"))
    history = PortfolioPerformanceHistory(portfolio.portfolio_id, "USD")

    updated = history.append(portfolio, _valuation(portfolio, timestamp=BASELINE_AT))

    snapshot = updated.snapshots[0]
    assert snapshot.cash_value == Decimal("1000")
    assert snapshot.positions_value == Decimal("0")
    assert snapshot.total_return == Decimal("0")


@pytest.mark.parametrize(
    ("timestamp", "should_raise"),
    [
        (CREATED_AT - timedelta(seconds=1), True),
        (CREATED_AT, False),
        (CREATED_AT + timedelta(seconds=1), False),
    ],
)
def test_snapshot_valuation_must_not_precede_portfolio_creation(timestamp: datetime, should_raise: bool) -> None:
    portfolio = _portfolio(Decimal("1000"))
    valuation = _valuation(portfolio, timestamp=timestamp)
    history = PortfolioPerformanceHistory(portfolio.portfolio_id, "USD")

    if should_raise:
        with pytest.raises(ValueError, match="portfolio creation"):
            history.append(portfolio, valuation)
    else:
        assert history.append(portfolio, valuation).snapshots[0].timestamp == timestamp


def test_hold_period_and_price_movement_can_be_measured_without_execution() -> None:
    security = SecurityIdentity("MSFT", "EQUITY", "NASDAQ", "USD")
    portfolio_id = uuid4()
    portfolio = _portfolio(
        Decimal("900"),
        portfolio_id=portfolio_id,
        positions=(Position(security, Decimal("1"), Decimal("100"), Decimal("100")),),
    )
    history = PortfolioPerformanceHistory(portfolio_id, "USD")
    baseline = history.append(portfolio, _valuation(portfolio, timestamp=BASELINE_AT, prices={security: Decimal("100")}))
    updated = baseline.append(portfolio, _valuation(portfolio, timestamp=NEXT_AT, prices={security: Decimal("120")}))

    assert updated.snapshots[-1].portfolio_value == Decimal("1020")
    assert updated.snapshots[-1].total_return == Decimal("0.02")


def test_empty_history_and_immutable_append() -> None:
    portfolio = _portfolio(Decimal("1000"))
    history = PortfolioPerformanceHistory(portfolio.portfolio_id, "USD")
    updated = history.append(portfolio, _valuation(portfolio, timestamp=BASELINE_AT))

    assert history.snapshots == ()
    assert len(updated.snapshots) == 1
    with pytest.raises(FrozenInstanceError):
        updated.currency = "EUR"  # type: ignore[misc]


def test_duplicate_history_timestamp_is_rejected() -> None:
    portfolio = _portfolio(Decimal("1000"))
    history = PortfolioPerformanceHistory(portfolio.portfolio_id, "USD").append(
        portfolio, _valuation(portfolio, timestamp=BASELINE_AT)
    )

    with pytest.raises(ValueError, match="strictly increasing"):
        history.append(portfolio, _valuation(portfolio, timestamp=BASELINE_AT))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("starting_capital", Decimal("2000")),
        ("created_at", CREATED_AT + timedelta(days=1)),
        ("currency", "EUR"),
    ],
)
def test_history_rejects_changed_immutable_portfolio_lineage(field: str, value: object) -> None:
    portfolio_id = uuid4()
    baseline = _portfolio(Decimal("1000"), portfolio_id=portfolio_id)
    history = PortfolioPerformanceHistory(portfolio_id, "USD").append(
        baseline, _valuation(baseline, timestamp=BASELINE_AT)
    )
    fields: dict[str, object] = {"portfolio_id": portfolio_id, "cash": Decimal("1000")}
    fields[field] = value
    later = _portfolio(**fields)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="lineage|currency"):
        history.append(later, _valuation(later, timestamp=NEXT_AT))


def test_cash_event_excludes_external_capital_from_return() -> None:
    event = _cash_event(Decimal("1000"))
    managed, benchmark = _cash_histories(managed_value=Decimal("2000"), benchmark_value=Decimal("2000"), cash_events=(event,))

    assert managed.snapshots[-1].investment_gain == Decimal("0")
    assert managed.snapshots[-1].contributed_capital_basis == Decimal("2000")
    assert managed.snapshots[-1].total_return == Decimal("0")
    assert PerformanceComparison(managed, benchmark).benchmark_cumulative_return == Decimal("0")


def test_cash_event_plus_investment_gain_uses_cumulative_contributed_capital_basis() -> None:
    event = _cash_event(Decimal("1000"))
    managed, _ = _cash_histories(managed_value=Decimal("2200"), cash_events=(event,))

    assert managed.snapshots[-1].investment_gain == Decimal("200")
    assert managed.snapshots[-1].total_return == Decimal("0.1")


def test_multiple_cash_events_accumulate_once_each() -> None:
    portfolio_id = uuid4()
    baseline = _portfolio(Decimal("1000"), portfolio_id=portfolio_id)
    first_event = _cash_event(Decimal("500"), effective_at=NEXT_AT)
    second_event = _cash_event(Decimal("500"), effective_at=LATER_AT)
    history = PortfolioPerformanceHistory(portfolio_id, "USD").append(baseline, _valuation(baseline, timestamp=BASELINE_AT))
    after_first = _portfolio(Decimal("1500"), portfolio_id=portfolio_id)
    history = history.append(after_first, _valuation(after_first, timestamp=NEXT_AT), cash_events=(first_event,))
    after_second = _portfolio(Decimal("2100"), portfolio_id=portfolio_id)
    history = history.append(after_second, _valuation(after_second, timestamp=LATER_AT), cash_events=(second_event,))

    snapshot = history.snapshots[-1]
    assert snapshot.cumulative_external_contributions == Decimal("1000")
    assert snapshot.investment_gain == Decimal("100")
    assert snapshot.total_return == Decimal("0.05")


def test_contribution_before_baseline_is_rejected() -> None:
    portfolio_id = uuid4()
    portfolio = _portfolio(Decimal("1000"), portfolio_id=portfolio_id)
    history = PortfolioPerformanceHistory(portfolio_id, "USD").append(
        portfolio, _valuation(portfolio, timestamp=BASELINE_AT)
    )
    event = _cash_event(Decimal("500"), effective_at=BASELINE_AT)
    updated = _portfolio(Decimal("1500"), portfolio_id=portfolio_id)

    with pytest.raises(ValueError, match="after the prior"):
        history.append(updated, _valuation(updated, timestamp=NEXT_AT), cash_events=(event,))


def test_contribution_exactly_at_snapshot_boundary_is_allowed() -> None:
    portfolio_id = uuid4()
    portfolio = _portfolio(Decimal("1000"), portfolio_id=portfolio_id)
    history = PortfolioPerformanceHistory(portfolio_id, "USD").append(
        portfolio, _valuation(portfolio, timestamp=BASELINE_AT)
    )
    event = _cash_event(Decimal("500"), effective_at=NEXT_AT)
    updated = _portfolio(Decimal("1500"), portfolio_id=portfolio_id)

    assert history.append(updated, _valuation(updated, timestamp=NEXT_AT), cash_events=(event,)).snapshots[-1].total_return == Decimal("0")


def test_contribution_after_snapshot_timestamp_is_rejected() -> None:
    portfolio_id = uuid4()
    portfolio = _portfolio(Decimal("1000"), portfolio_id=portfolio_id)
    history = PortfolioPerformanceHistory(portfolio_id, "USD").append(
        portfolio, _valuation(portfolio, timestamp=BASELINE_AT)
    )
    event = _cash_event(Decimal("500"), effective_at=NEXT_AT + timedelta(seconds=1))
    updated = _portfolio(Decimal("1500"), portfolio_id=portfolio_id)

    with pytest.raises(ValueError, match="postdate"):
        history.append(updated, _valuation(updated, timestamp=NEXT_AT), cash_events=(event,))


def test_multiple_ordered_cash_events_in_one_interval_are_allowed() -> None:
    portfolio_id = uuid4()
    portfolio = _portfolio(Decimal("1000"), portfolio_id=portfolio_id)
    history = PortfolioPerformanceHistory(portfolio_id, "USD").append(
        portfolio, _valuation(portfolio, timestamp=BASELINE_AT)
    )
    first = _cash_event(Decimal("250"), effective_at=NEXT_AT - timedelta(minutes=1))
    second = _cash_event(Decimal("250"), effective_at=NEXT_AT)
    updated = _portfolio(Decimal("1500"), portfolio_id=portfolio_id)

    result = history.append(updated, _valuation(updated, timestamp=NEXT_AT), cash_events=(first, second))

    assert result.snapshots[-1].cumulative_external_contributions == Decimal("500")


def test_reverse_chronological_cash_events_are_rejected_and_equal_timestamps_are_allowed() -> None:
    portfolio_id = uuid4()
    portfolio = _portfolio(Decimal("1000"), portfolio_id=portfolio_id)
    history = PortfolioPerformanceHistory(portfolio_id, "USD").append(
        portfolio, _valuation(portfolio, timestamp=BASELINE_AT)
    )
    earlier = _cash_event(Decimal("250"), effective_at=NEXT_AT - timedelta(minutes=1))
    later = _cash_event(Decimal("250"), effective_at=NEXT_AT)
    updated = _portfolio(Decimal("1500"), portfolio_id=portfolio_id)

    with pytest.raises(ValueError, match="nondecreasing"):
        history.append(updated, _valuation(updated, timestamp=NEXT_AT), cash_events=(later, earlier))

    same_time_one = _cash_event(Decimal("250"), effective_at=NEXT_AT)
    same_time_two = _cash_event(Decimal("250"), effective_at=NEXT_AT)
    assert history.append(
        updated,
        _valuation(updated, timestamp=NEXT_AT),
        cash_events=(same_time_one, same_time_two),
    ).snapshots[-1].cumulative_external_contributions == Decimal("500")


def test_negative_return_with_contribution_uses_approved_formula() -> None:
    event = _cash_event(Decimal("500"))
    managed, _ = _cash_histories(managed_value=Decimal("1200"), cash_events=(event,))

    assert managed.snapshots[-1].total_return == Decimal("-0.2")


def test_managed_and_benchmark_equal_cash_event_schedules_are_comparable() -> None:
    event = _cash_event(Decimal("1000"))
    managed, benchmark = _cash_histories(
        managed_value=Decimal("2200"),
        benchmark_value=Decimal("2100"),
        cash_events=(event,),
    )

    comparison = PerformanceComparison(managed, benchmark)

    assert comparison.managed_cumulative_return == Decimal("0.1")
    assert comparison.benchmark_cumulative_return == Decimal("0.05")
    assert comparison.absolute_alpha == Decimal("0.05")


def test_comparison_requires_matching_starting_capital() -> None:
    managed, benchmark = _cash_histories()
    assert PerformanceComparison(managed, benchmark).absolute_alpha == Decimal("0")

    mismatched_benchmark = _benchmark(Decimal("1000"), portfolio_id=benchmark.benchmark_portfolio_id, starting_capital=Decimal("2000"))
    mismatched_history = BenchmarkPerformanceHistory.for_benchmark(mismatched_benchmark).append(
        mismatched_benchmark,
        _valuation(mismatched_benchmark.portfolio, timestamp=BASELINE_AT),
    ).append(
        mismatched_benchmark,
        _valuation(mismatched_benchmark.portfolio, timestamp=NEXT_AT),
    )

    with pytest.raises(ValueError, match="starting_capital"):
        PerformanceComparison(managed, mismatched_history)


def test_different_cash_event_schedules_are_rejected() -> None:
    event = _cash_event(Decimal("1000"))
    managed, benchmark = _cash_histories(cash_events=(event,))
    benchmark_snapshot = benchmark.snapshots[-1]
    benchmark_without_event = BenchmarkPerformanceHistory(
        benchmark.benchmark_portfolio_id,
        benchmark.benchmark_security,
        benchmark.currency,
        (
            benchmark.snapshots[0],
            type(benchmark_snapshot)(
                benchmark_snapshot.portfolio,
                benchmark_snapshot.valuation,
                benchmark_snapshot.baseline_value,
                Decimal("0"),
                (),
            ),
        ),
    )

    with pytest.raises(ValueError, match="CashEvent schedule"):
        PerformanceComparison(managed, benchmark_without_event)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("as_of_timestamp", NEXT_AT + timedelta(minutes=1)),
        ("source_provider_identity", "other-provider"),
        ("market_date", NEXT_AT.date() - timedelta(days=1)),
        ("source_price_timestamp", NEXT_AT - timedelta(minutes=1)),
        ("price_convention", "other-convention"),
    ],
)
def test_comparison_rejects_mismatched_valuation_provenance(field: str, value: object) -> None:
    managed, benchmark = _cash_histories()
    benchmark_snapshot = benchmark.snapshots[-1]
    valuation_fields = {
        "subject_id": benchmark_snapshot.valuation.subject_id,
        "as_of_timestamp": benchmark_snapshot.valuation.as_of_timestamp,
        "cash_value": benchmark_snapshot.valuation.cash_value,
        "invested_value": benchmark_snapshot.valuation.invested_value,
        "total_value": benchmark_snapshot.valuation.total_value,
        "unrealized_gain_loss": benchmark_snapshot.valuation.unrealized_gain_loss,
        "position_valuations": benchmark_snapshot.valuation.position_valuations,
        "source_provider_identity": benchmark_snapshot.valuation.source_provider_identity,
        "market_date": benchmark_snapshot.valuation.market_date,
        "source_price_timestamp": benchmark_snapshot.valuation.source_price_timestamp,
        "currency": benchmark_snapshot.valuation.currency,
        "price_convention": benchmark_snapshot.valuation.price_convention,
    }
    valuation_fields[field] = value
    mismatched_valuation = PortfolioValuation(**valuation_fields)  # type: ignore[arg-type]
    mismatched_snapshot = type(benchmark_snapshot)(
        benchmark_snapshot.portfolio,
        mismatched_valuation,
        benchmark_snapshot.baseline_value,
        benchmark_snapshot.cumulative_external_contributions,
        benchmark_snapshot.cash_events,
    )
    mismatched_history = BenchmarkPerformanceHistory(
        benchmark.benchmark_portfolio_id,
        benchmark.benchmark_security,
        benchmark.currency,
        (benchmark.snapshots[0], mismatched_snapshot),
    )

    with pytest.raises(ValueError, match="valuation"):
        PerformanceComparison(managed, mismatched_history)


def test_comparison_rejects_provenance_mismatch_only_in_middle_snapshot_pair() -> None:
    managed_id = uuid4()
    benchmark_id = uuid4()
    managed = PortfolioPerformanceHistory(managed_id, "USD")
    benchmark = _benchmark(Decimal("1000"), portfolio_id=benchmark_id)
    benchmark_history = BenchmarkPerformanceHistory.for_benchmark(benchmark)
    for timestamp, provider in (
        (BASELINE_AT, "test-provider"),
        (NEXT_AT, "other-provider"),
        (LATER_AT, "test-provider"),
    ):
        managed_state = _portfolio(Decimal("1000"), portfolio_id=managed_id)
        managed = managed.append(managed_state, _valuation(managed_state, timestamp=timestamp))
        benchmark_history = benchmark_history.append(
            benchmark,
            _valuation(benchmark.portfolio, timestamp=timestamp, provider=provider),
        )

    with pytest.raises(ValueError, match="source_provider_identity"):
        PerformanceComparison(managed, benchmark_history)


def test_comparison_rejects_currency_mismatch() -> None:
    managed_portfolio = _portfolio(Decimal("1000"), currency="USD")
    benchmark = _benchmark(Decimal("1000"), currency="EUR")
    managed = PortfolioPerformanceHistory(managed_portfolio.portfolio_id, "USD").append(
        managed_portfolio, _valuation(managed_portfolio, timestamp=BASELINE_AT)
    )
    benchmark_history = BenchmarkPerformanceHistory.for_benchmark(benchmark).append(
        benchmark, _valuation(benchmark.portfolio, timestamp=BASELINE_AT)
    )

    with pytest.raises(ValueError, match="currency"):
        PerformanceComparison(managed, benchmark_history)


def test_managed_and_benchmark_need_not_share_execution_history() -> None:
    managed, benchmark = _cash_histories(managed_value=Decimal("1100"), benchmark_value=Decimal("1050"))

    comparison = PerformanceComparison(managed, benchmark)

    assert comparison.absolute_alpha == Decimal("0.05")


def test_managed_outperformance_benchmark_outperformance_and_equal_returns() -> None:
    managed, benchmark = _cash_histories(managed_value=Decimal("1100"), benchmark_value=Decimal("1050"))
    assert PerformanceComparison(managed, benchmark).relative_alpha == Decimal("0.047619047619047619047619048")

    managed, benchmark = _cash_histories(managed_value=Decimal("900"), benchmark_value=Decimal("1100"))
    assert PerformanceComparison(managed, benchmark).absolute_alpha == Decimal("-0.2")

    managed, benchmark = _cash_histories(managed_value=Decimal("1000"), benchmark_value=Decimal("1000"))
    assert PerformanceComparison(managed, benchmark).absolute_alpha == Decimal("0")


def test_negative_return_and_benchmark_minus_one_hundred_percent_edge() -> None:
    managed, benchmark = _cash_histories(managed_value=Decimal("900"), benchmark_value=Decimal("0"))
    comparison = PerformanceComparison(managed, benchmark)

    assert comparison.managed_cumulative_return == Decimal("-0.1")
    assert comparison.benchmark_cumulative_return == Decimal("-1")
    with pytest.raises(ValueError, match="undefined"):
        _ = comparison.relative_alpha


def test_performance_calculations_are_ambient_decimal_context_independent() -> None:
    def relative_alpha(precision: int) -> Decimal:
        with localcontext() as context:
            context.prec = precision
            managed, benchmark = _cash_histories(managed_value=Decimal("1333.333333"), benchmark_value=Decimal("1177.777777"))
            return PerformanceComparison(managed, benchmark).relative_alpha

    assert relative_alpha(6) == relative_alpha(50)
