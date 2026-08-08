from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.portfolio import CashBalance, Contribution, Portfolio, Position, SecurityIdentity
from agentic_portfolio_lab.domain.portfolio_service import PortfolioService
from agentic_portfolio_lab.domain.valuation import (
    BenchmarkPortfolio,
    PortfolioComparison,
    PortfolioValuation,
    PriceObservation,
)


UTC = timezone.utc
VALUATION_TIMESTAMP = datetime(2026, 8, 20, 21, tzinfo=UTC)
MARKET_DATE = date(2026, 8, 20)


def _security(ticker: str = "AAPL") -> SecurityIdentity:
    return SecurityIdentity(
        ticker=ticker,
        security_type="EQUITY",
        exchange="NYSEARCA" if ticker == "SPY" else "NASDAQ",
        currency="USD",
    )


def _portfolio(*, cash: Decimal = Decimal("1000"), positions: tuple[Position, ...] = ()) -> Portfolio:
    return Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Managed",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance(currency="USD", amount=cash),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        positions=positions,
    )


def _observation(security: SecurityIdentity, price: Decimal, **overrides: object) -> PriceObservation:
    fields: dict[str, object] = {
        "security": security,
        "observed_price": price,
        "market_date": MARKET_DATE,
        "observed_at": VALUATION_TIMESTAMP,
        "currency": "USD",
        "source_provider_identity": "test-provider",
        "price_convention": "regular-session-close",
    }
    fields.update(overrides)
    return PriceObservation(**fields)  # type: ignore[arg-type]


def _portfolio_valuation(
    portfolio: Portfolio,
    observations: tuple[PriceObservation, ...],
    **overrides: object,
) -> PortfolioValuation:
    fields: dict[str, object] = {
        "as_of_timestamp": VALUATION_TIMESTAMP,
        "market_date": MARKET_DATE,
        "source_price_timestamp": VALUATION_TIMESTAMP,
        "source_provider_identity": "test-provider",
        "price_convention": "regular-session-close",
    }
    fields.update(overrides)
    return PortfolioValuation.from_portfolio(portfolio, observations, **fields)  # type: ignore[arg-type]


def _benchmark(*, cash: Decimal = Decimal("1000"), positions: tuple[Position, ...] = ()) -> BenchmarkPortfolio:
    spy = _security("SPY")
    return BenchmarkPortfolio(
        portfolio=Portfolio(
            portfolio_id=uuid4(),
            portfolio_name="SPY Benchmark",
            base_currency="USD",
            starting_capital=Decimal("1000"),
            cash_balance=CashBalance(currency="USD", amount=cash),
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
            positions=positions,
        ),
        benchmark_security=spy,
    )


def _benchmark_valuation(
    benchmark: BenchmarkPortfolio,
    observations: tuple[PriceObservation, ...],
    **overrides: object,
) -> PortfolioValuation:
    fields: dict[str, object] = {
        "as_of_timestamp": VALUATION_TIMESTAMP,
        "market_date": MARKET_DATE,
        "source_price_timestamp": VALUATION_TIMESTAMP,
        "source_provider_identity": "test-provider",
        "price_convention": "regular-session-close",
    }
    fields.update(overrides)
    return PortfolioValuation.from_benchmark(benchmark, observations, **fields)  # type: ignore[arg-type]


def test_cash_only_portfolio_valuation_is_deterministic_and_immutable() -> None:
    portfolio = _portfolio()

    valuation = _portfolio_valuation(portfolio, ())

    assert valuation.cash_value == Decimal("1000")
    assert valuation.invested_value == Decimal("0")
    assert valuation.total_value == Decimal("1000")
    assert valuation.unrealized_gain_loss == Decimal("0")
    assert valuation.position_weights == ()
    assert portfolio.cash_balance.amount == Decimal("1000")
    with pytest.raises(AttributeError):
        valuation.total_value = Decimal("0")  # type: ignore[misc]


def test_portfolio_valuation_uses_supplied_price_not_stored_position_price() -> None:
    security = _security()
    portfolio = _portfolio(
        cash=Decimal("500"),
        positions=(Position(security, Decimal("2"), Decimal("180"), Decimal("1")),),
    )

    valuation = _portfolio_valuation(portfolio, (_observation(security, Decimal("125")),))

    assert valuation.invested_value == Decimal("250")
    assert valuation.total_value == Decimal("750")
    assert valuation.unrealized_gain_loss == Decimal("70")
    assert valuation.position_valuations[0].market_value == Decimal("250")
    assert valuation.position_weights == ((security, Decimal("0.3333333333333333333333333333")),)
    assert portfolio.positions[0].market_price == Decimal("1")


def test_portfolio_service_snapshot_delegates_to_supplied_price_valuation() -> None:
    security = _security()
    portfolio = _portfolio(
        cash=Decimal("500"),
        positions=(Position(security, Decimal("2"), Decimal("180"), Decimal("1")),),
    )

    valuation = PortfolioService.portfolio_snapshot(
        portfolio,
        (_observation(security, Decimal("125")),),
        as_of_timestamp=VALUATION_TIMESTAMP,
        market_date=MARKET_DATE,
        source_price_timestamp=VALUATION_TIMESTAMP,
        source_provider_identity="test-provider",
        price_convention="regular-session-close",
    )

    assert isinstance(valuation, PortfolioValuation)
    assert valuation.invested_value == Decimal("250")
    with pytest.raises(ValueError, match="missing prices"):
        PortfolioService.portfolio_snapshot(
            portfolio,
            (),
            as_of_timestamp=VALUATION_TIMESTAMP,
            market_date=MARKET_DATE,
            source_price_timestamp=VALUATION_TIMESTAMP,
            source_provider_identity="test-provider",
            price_convention="regular-session-close",
        )


def test_portfolio_valuation_supports_multiple_positions_and_zero_value_state() -> None:
    aapl = _security("AAPL")
    msft = _security("MSFT")
    portfolio = _portfolio(
        cash=Decimal("100"),
        positions=(
            Position(aapl, Decimal("2"), Decimal("180"), Decimal("1")),
            Position(msft, Decimal("3"), Decimal("270"), Decimal("1")),
        ),
    )

    valuation = _portfolio_valuation(
        portfolio,
        (_observation(aapl, Decimal("125")), _observation(msft, Decimal("110"))),
    )
    zero_value = _portfolio_valuation(_portfolio(cash=Decimal("0")), ())

    assert valuation.invested_value == Decimal("580")
    assert valuation.total_value == Decimal("680")
    assert valuation.unrealized_gain_loss == Decimal("130")
    assert valuation.position_weights[0][1] == Decimal("0.3676470588235294117647058824")
    assert valuation.position_weights[1][1] == Decimal("0.4852941176470588235294117647")
    assert zero_value.total_value == Decimal("0")
    assert zero_value.position_weights == ()


def test_portfolio_valuation_rejects_missing_duplicate_and_unrelated_observations() -> None:
    security = _security()
    other_security = _security("MSFT")
    portfolio = _portfolio(positions=(Position(security, Decimal("1"), Decimal("100"), Decimal("1")),))
    observation = _observation(security, Decimal("100"))

    with pytest.raises(ValueError, match="missing prices"):
        _portfolio_valuation(portfolio, ())
    with pytest.raises(ValueError, match="duplicate"):
        _portfolio_valuation(portfolio, (observation, observation))
    with pytest.raises(ValueError, match="not held"):
        _portfolio_valuation(portfolio, (observation, _observation(other_security, Decimal("100"))))


@pytest.mark.parametrize("price", [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")])
def test_price_observation_rejects_non_positive_or_non_finite_prices(price: Decimal) -> None:
    with pytest.raises(ValueError):
        _observation(_security(), price)


def test_price_observation_requires_aware_timestamp_and_date_only_market_date() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _observation(_security(), Decimal("100"), observed_at=datetime(2026, 8, 20, 21))
    with pytest.raises(TypeError, match="date, not a datetime"):
        _observation(_security(), Decimal("100"), market_date=datetime(2026, 8, 20, 21, tzinfo=UTC))


def test_portfolio_valuation_rejects_inconsistent_observation_metadata_and_currency() -> None:
    security = _security()
    portfolio = _portfolio(positions=(Position(security, Decimal("1"), Decimal("100"), Decimal("1")),))

    with pytest.raises(ValueError, match="provider"):
        _portfolio_valuation(portfolio, (_observation(security, Decimal("100"), source_provider_identity="other-provider"),))
    with pytest.raises(ValueError, match="timestamp"):
        _portfolio_valuation(
            portfolio,
            (_observation(security, Decimal("100"), observed_at=VALUATION_TIMESTAMP - timedelta(minutes=1)),),
        )
    with pytest.raises(ValueError, match="currency"):
        _observation(security, Decimal("100"), currency="EUR")


def test_valuation_rejects_lookahead_prices_and_allows_equal_or_older_observations() -> None:
    security = _security()
    portfolio = _portfolio(positions=(Position(security, Decimal("1"), Decimal("100"), Decimal("1")),))
    future_timestamp = VALUATION_TIMESTAMP + timedelta(minutes=1)
    future_market_date = MARKET_DATE + timedelta(days=1)

    with pytest.raises(ValueError, match="source_price_timestamp"):
        _portfolio_valuation(
            portfolio,
            (_observation(security, Decimal("100"), observed_at=future_timestamp),),
            source_price_timestamp=future_timestamp,
        )
    with pytest.raises(ValueError, match="market_date"):
        _portfolio_valuation(
            portfolio,
            (_observation(security, Decimal("100"), market_date=future_market_date),),
            market_date=future_market_date,
        )

    equal_cutoff = _portfolio_valuation(portfolio, (_observation(security, Decimal("100")),))
    older_observation = _portfolio_valuation(
        portfolio,
        (_observation(security, Decimal("100"), market_date=MARKET_DATE - timedelta(days=1), observed_at=VALUATION_TIMESTAMP - timedelta(days=1)),),
        market_date=MARKET_DATE - timedelta(days=1),
        source_price_timestamp=VALUATION_TIMESTAMP - timedelta(days=1),
    )

    assert equal_cutoff.total_value == Decimal("1100")
    assert older_observation.total_value == Decimal("1100")


def test_valuation_is_independent_of_ambient_decimal_context() -> None:
    security = _security()
    portfolio = _portfolio(
        cash=Decimal("1"),
        positions=(Position(security, Decimal("1.23456789"), Decimal("100"), Decimal("1")),),
    )
    observation = _observation(security, Decimal("123.456789"))

    def value_under_precision(precision: int) -> PortfolioValuation:
        with localcontext() as context:
            context.prec = precision
            return _portfolio_valuation(portfolio, (observation,))

    low_precision = value_under_precision(6)
    high_precision = value_under_precision(50)
    assert low_precision.invested_value == high_precision.invested_value
    assert low_precision.unrealized_gain_loss == high_precision.unrealized_gain_loss
    assert low_precision.position_weights == high_precision.position_weights


def test_benchmark_composes_portfolio_and_delegates_cash_event_application() -> None:
    managed = _portfolio()
    benchmark = BenchmarkPortfolio.from_portfolio(managed, _security("SPY"))
    contribution = Contribution(
        amount=Decimal("250"),
        currency="USD",
        effective_at=datetime(2026, 8, 21, tzinfo=UTC),
        received_at=datetime(2026, 8, 21, tzinfo=UTC),
        source="bank transfer",
    )

    updated = benchmark.receive_contribution(contribution)
    valuation = _benchmark_valuation(updated, ())

    assert isinstance(benchmark.portfolio, Portfolio)
    assert benchmark.portfolio is not managed
    assert benchmark.portfolio.starting_capital == managed.starting_capital
    assert benchmark.portfolio.cash_balance.amount == Decimal("1000")
    assert updated.portfolio is not benchmark.portfolio
    assert updated.portfolio.cash_balance.amount == Decimal("1250")
    assert updated.portfolio.positions == ()
    assert valuation.total_value == Decimal("1250")


def test_benchmark_with_fractional_spy_holding_is_valued_from_supplied_price() -> None:
    spy = _security("SPY")
    benchmark = _benchmark(
        cash=Decimal("100"),
        positions=(Position(spy, Decimal("2.5"), Decimal("1000"), Decimal("1")),),
    )

    valuation = _benchmark_valuation(benchmark, (_observation(spy, Decimal("450")),))

    assert valuation.invested_value == Decimal("1125.0")
    assert valuation.total_value == Decimal("1225.0")
    assert valuation.unrealized_gain_loss == Decimal("125.0")


def test_benchmark_rejects_non_spy_or_non_benchmark_positions() -> None:
    with pytest.raises(ValueError, match="ticker"):
        BenchmarkPortfolio(portfolio=_portfolio(), benchmark_security=_security("AAPL"))
    with pytest.raises(ValueError, match="only hold"):
        BenchmarkPortfolio(
            portfolio=_portfolio(positions=(Position(_security("AAPL"), Decimal("1"), Decimal("100"), Decimal("1")),)),
            benchmark_security=_security("SPY"),
        )


def test_portfolio_comparison_is_absolute_in_both_directions_and_at_equality() -> None:
    benchmark_valuation = _benchmark_valuation(_benchmark(cash=Decimal("1000")), ())
    managed_higher = _portfolio_valuation(_portfolio(cash=Decimal("1200")), ())
    managed_lower = _portfolio_valuation(_portfolio(cash=Decimal("800")), ())
    managed_equal = _portfolio_valuation(_portfolio(cash=Decimal("1000")), ())

    assert PortfolioComparison(managed_higher, benchmark_valuation).absolute_difference == Decimal("200")
    assert PortfolioComparison(managed_lower, benchmark_valuation).absolute_difference == Decimal("200")
    assert PortfolioComparison(managed_equal, benchmark_valuation).absolute_difference == Decimal("0")


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("as_of_timestamp", VALUATION_TIMESTAMP + timedelta(minutes=1)),
        ("market_date", MARKET_DATE - timedelta(days=1)),
        ("source_price_timestamp", VALUATION_TIMESTAMP - timedelta(minutes=1)),
        ("source_provider_identity", "other-provider"),
        ("price_convention", "intraday-last"),
        ("currency", "EUR"),
    ],
)
def test_portfolio_comparison_rejects_each_metadata_mismatch(field_name: str, value: object) -> None:
    managed = _portfolio_valuation(_portfolio(), ())
    benchmark = _benchmark_valuation(_benchmark(), ())
    mismatched_benchmark = replace(benchmark, **{field_name: value})

    with pytest.raises(ValueError, match=field_name):
        PortfolioComparison(managed, mismatched_benchmark)
