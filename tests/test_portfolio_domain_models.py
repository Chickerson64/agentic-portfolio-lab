from __future__ import annotations

from decimal import Decimal, localcontext
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.portfolio import (
    CashBalance,
    Contribution,
    Portfolio,
    PortfolioValuationSnapshot,
    Position,
    SecurityIdentity,
)


def test_security_identity_requires_all_fields_and_normalizes_key_components() -> None:
    security = SecurityIdentity(ticker=" aapl ", security_type=" Equity ", exchange=" nasdaq ", currency=" usd ")

    assert security.ticker == "AAPL"
    assert security.security_type == "EQUITY"
    assert security.exchange == "NASDAQ"
    assert security.currency == "USD"
    assert security == SecurityIdentity(ticker="AAPL", security_type="equity", exchange="NASDAQ", currency="USD")


@pytest.mark.parametrize("amount", [Decimal("-1"), Decimal("-0.00001"), Decimal("NaN"), Decimal("Infinity")])
def test_cash_balance_rejects_negative_and_non_finite_values(amount: Decimal) -> None:
    with pytest.raises(ValueError):
        CashBalance(currency="USD", amount=amount)


def test_cash_balance_preserves_supplied_decimal_precision() -> None:
    balance = CashBalance(currency="USD", amount=Decimal("100.123456"))

    assert balance.amount == Decimal("100.123456")


def test_position_preserves_authoritative_total_cost_and_calculates_derived_values() -> None:
    security = SecurityIdentity(ticker="AAPL", security_type="equity", exchange="NASDAQ", currency="USD")
    position = Position(
        security=security,
        quantity=Decimal("1.23456789"),
        total_cost_basis=Decimal("123.60920381342784"),
        market_price=Decimal("105.987654"),
    )

    assert position.quantity == Decimal("1.23456789")
    assert position.total_cost_basis == Decimal("123.60920381342784")
    assert position.average_cost_basis == Decimal("100.123456")
    assert position.market_price == Decimal("105.987654")
    assert position.market_value == position.quantity * position.market_price
    assert position.unrealized_pnl == position.market_value - position.total_cost_basis

    with pytest.raises(ValueError):
        Position(
            security=security,
            quantity=Decimal("1.234567891"),
            total_cost_basis=Decimal("100"),
            market_price=Decimal("100"),
        )


def test_average_cost_basis_is_informational_and_context_independent() -> None:
    def average_under_precision(precision: int) -> Decimal:
        with localcontext() as context:
            context.prec = precision
            position = Position(
                security=SecurityIdentity(ticker="AAPL", security_type="equity", exchange="NASDAQ", currency="USD"),
                quantity=Decimal("3"),
                total_cost_basis=Decimal("302"),
                market_price=Decimal("100"),
            )
            return position.average_cost_basis

    assert average_under_precision(6) == average_under_precision(50)
    assert average_under_precision(6) == Decimal("100.6666666666666666666666667")


def test_zero_quantity_position_requires_zero_total_cost_basis() -> None:
    security = SecurityIdentity(ticker="AAPL", security_type="equity", exchange="NASDAQ", currency="USD")
    position = Position(
        security=security,
        quantity=Decimal("0"),
        total_cost_basis=Decimal("0"),
        market_price=Decimal("100"),
    )

    assert position.average_cost_basis == Decimal("0")
    with pytest.raises(ValueError, match="total_cost_basis must be zero"):
        Position(
            security=security,
            quantity=Decimal("0"),
            total_cost_basis=Decimal("1"),
            market_price=Decimal("100"),
        )


def test_contribution_is_explicitly_one_time() -> None:
    contribution = Contribution(
        amount=Decimal("2500.5"),
        currency="USD",
        effective_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        received_at=datetime(2026, 8, 1, 9, tzinfo=timezone.utc),
        source="bank transfer",
    )

    assert contribution.amount == Decimal("2500.5")
    assert contribution.is_one_time_event is True

    with pytest.raises(ValueError):
        Contribution(
            amount=Decimal("1"),
            currency="USD",
            effective_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            received_at=datetime(2026, 8, 1, 9, tzinfo=timezone.utc),
            source="bank transfer",
            is_one_time_event=False,
        )

    with pytest.raises(ValueError):
        Contribution(
            amount=Decimal("0"),
            currency="USD",
            effective_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            received_at=datetime(2026, 8, 1, 9, tzinfo=timezone.utc),
            source="bank transfer",
        )

    with pytest.raises(ValueError):
        Contribution(
            amount=Decimal("1"),
            currency="USD",
            effective_at=datetime(2026, 8, 1),
            received_at=datetime(2026, 8, 1, 9, tzinfo=timezone.utc),
            source="bank transfer",
        )


def test_portfolio_rejects_currency_mismatch_and_derives_values() -> None:
    security = SecurityIdentity(ticker="AAPL", security_type="equity", exchange="NASDAQ", currency="USD")
    position = Position(
        security=security,
        quantity=Decimal("1.0"),
        total_cost_basis=Decimal("100"),
        market_price=Decimal("110"),
    )
    cash = CashBalance(currency="USD", amount=Decimal("890"))

    portfolio = Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Core",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=cash,
        positions=(position,),
        created_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
    )

    assert portfolio.current_market_value == Decimal("110.0000")
    assert portfolio.current_total_value == Decimal("1000.0000")

    portfolio_with_contribution_cash = Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Core",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance(currency="USD", amount=Decimal("1200")),
        created_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
    )
    assert portfolio_with_contribution_cash.cash_balance.amount == Decimal("1200")

    normalized_equivalent_security = SecurityIdentity(
        ticker=" aapl ", security_type=" Equity ", exchange=" nasdaq ", currency=" usd "
    )
    normalized_equivalent_position = Position(
        security=normalized_equivalent_security,
        quantity=Decimal("2"),
        total_cost_basis=Decimal("210"),
        market_price=Decimal("110"),
    )
    with pytest.raises(ValueError):
        Portfolio(
            portfolio_id=uuid4(),
            portfolio_name="Core",
            base_currency="USD",
            starting_capital=Decimal("1000"),
            cash_balance=CashBalance(currency="EUR", amount=Decimal("890")),
            created_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
        )

    with pytest.raises(ValueError):
        Portfolio(
            portfolio_id=uuid4(),
            portfolio_name="Core",
            base_currency="USD",
            starting_capital=Decimal("1000"),
            cash_balance=cash,
            positions=(position, normalized_equivalent_position),
            created_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
        )

    with pytest.raises(ValueError):
        Portfolio(
            portfolio_id=uuid4(),
            portfolio_name="Core",
            base_currency="USD",
            starting_capital=Decimal("1000"),
            cash_balance=cash,
            created_at=datetime(2026, 8, 8),
        )


def test_valuation_snapshot_is_derived_from_components() -> None:
    security = SecurityIdentity(ticker="AAPL", security_type="equity", exchange="NASDAQ", currency="USD")
    position = Position(
        security=security,
        quantity=Decimal("2"),
        total_cost_basis=Decimal("200"),
        market_price=Decimal("105.5555"),
    )
    cash = CashBalance(currency="USD", amount=Decimal("789.4321"))

    snapshot = PortfolioValuationSnapshot.from_components(
        portfolio_id=uuid4(),
        as_of_timestamp=datetime(2026, 8, 8, 10, tzinfo=timezone.utc),
        cash_balance=cash,
        positions=(position,),
        source_provider_identity="provider-x",
        market_date=date(2026, 8, 8),
        source_price_timestamp=datetime(2026, 8, 8, 9, 30, tzinfo=timezone.utc),
        price_convention="regular-session-close",
    )

    assert snapshot.positions_market_value == Decimal("211.1110")
    assert snapshot.total_value == Decimal("1000.5431")


def test_valuation_snapshot_rejects_inconsistent_totals_and_cross_currency_positions() -> None:
    with pytest.raises(ValueError, match="total_value"):
        PortfolioValuationSnapshot(
            portfolio_id=uuid4(),
            as_of_timestamp=datetime(2026, 8, 8, 10, tzinfo=timezone.utc),
            cash_balance=Decimal("10"),
            positions_market_value=Decimal("20"),
            total_value=Decimal("999"),
            source_provider_identity="provider-x",
            market_date=date(2026, 8, 8),
            source_price_timestamp=datetime(2026, 8, 8, 9, 30, tzinfo=timezone.utc),
            currency="USD",
            price_convention="regular-session-close",
        )

    eur_position = Position(
        security=SecurityIdentity(ticker="SAP", security_type="equity", exchange="XETRA", currency="EUR"),
        quantity=Decimal("1"),
        total_cost_basis=Decimal("100"),
        market_price=Decimal("100"),
    )
    with pytest.raises(ValueError, match="currency"):
        PortfolioValuationSnapshot.from_components(
            portfolio_id=uuid4(),
            as_of_timestamp=datetime(2026, 8, 8, 10, tzinfo=timezone.utc),
            cash_balance=CashBalance(currency="USD", amount=Decimal("100")),
            positions=(eur_position,),
            source_provider_identity="provider-x",
            market_date=date(2026, 8, 8),
            source_price_timestamp=datetime(2026, 8, 8, 9, 30, tzinfo=timezone.utc),
            price_convention="regular-session-close",
        )


def test_valuation_snapshot_requires_aware_instants_and_date_only_market_date() -> None:
    common_arguments = {
        "portfolio_id": uuid4(),
        "cash_balance": Decimal("10"),
        "positions_market_value": Decimal("20"),
        "total_value": Decimal("30"),
        "source_provider_identity": "provider-x",
        "market_date": date(2026, 8, 8),
        "source_price_timestamp": datetime(2026, 8, 8, 9, 30, tzinfo=timezone.utc),
        "currency": "USD",
        "price_convention": "regular-session-close",
    }

    with pytest.raises(ValueError, match="timezone-aware"):
        PortfolioValuationSnapshot(as_of_timestamp=datetime(2026, 8, 8, 10), **common_arguments)

    with pytest.raises(TypeError, match="date, not a datetime"):
        PortfolioValuationSnapshot(
            as_of_timestamp=datetime(2026, 8, 8, 10, tzinfo=timezone.utc),
            market_date=datetime(2026, 8, 8, 10, tzinfo=timezone.utc),
            **{key: value for key, value in common_arguments.items() if key != "market_date"},
        )


def test_authoritative_calculations_ignore_the_ambient_decimal_context() -> None:
    def calculate_under_precision(precision: int) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
        with localcontext() as context:
            context.prec = precision
            position = Position(
                security=SecurityIdentity(ticker="AAPL", security_type="equity", exchange="NASDAQ", currency="USD"),
                quantity=Decimal("1.23456789"),
                total_cost_basis=Decimal("123.60920381342784"),
                market_price=Decimal("105.987654"),
            )
            cash = CashBalance(currency="USD", amount=Decimal("100000000.123456"))
            portfolio = Portfolio(
                portfolio_id=uuid4(),
                portfolio_name="Core",
                base_currency="USD",
                starting_capital=Decimal("1000"),
                cash_balance=cash,
                positions=(position,),
                created_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
            )
            snapshot = PortfolioValuationSnapshot.from_components(
                portfolio_id=portfolio.portfolio_id,
                as_of_timestamp=datetime(2026, 8, 8, 10, tzinfo=timezone.utc),
                cash_balance=cash,
                positions=(position,),
                source_provider_identity="provider-x",
                market_date=date(2026, 8, 8),
                source_price_timestamp=datetime(2026, 8, 8, 9, 30, tzinfo=timezone.utc),
                price_convention="regular-session-close",
            )
            return (
                position.market_value,
                position.unrealized_pnl,
                portfolio.current_market_value,
                portfolio.current_total_value,
                snapshot.total_value,
            )

    assert calculate_under_precision(6) == calculate_under_precision(50)


@pytest.mark.parametrize("precision", [6, 50])
def test_snapshot_consistency_validation_ignores_ambient_decimal_context(precision: int) -> None:
    with localcontext() as context:
        context.prec = precision
        with pytest.raises(ValueError, match="total_value"):
            PortfolioValuationSnapshot(
                portfolio_id=uuid4(),
                as_of_timestamp=datetime(2026, 8, 8, 10, tzinfo=timezone.utc),
                cash_balance=Decimal("100000000.123456"),
                positions_market_value=Decimal("130.84895436483006"),
                total_value=Decimal("100000130"),
                source_provider_identity="provider-x",
                market_date=date(2026, 8, 8),
                source_price_timestamp=datetime(2026, 8, 8, 9, 30, tzinfo=timezone.utc),
                currency="USD",
                price_convention="regular-session-close",
            )
