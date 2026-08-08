from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.portfolio import CashBalance, Contribution, Portfolio, Position, SecurityIdentity
from agentic_portfolio_lab.domain.portfolio_service import PortfolioService, TargetPurchaseCalculation
from agentic_portfolio_lab.domain.trades import ExecutedTrade, TradeProposal, ValidatedTrade


UTC = timezone.utc


def _security() -> SecurityIdentity:
    return SecurityIdentity(ticker="AAPL", security_type="EQUITY", exchange="NASDAQ", currency="USD")


def _portfolio(*, cash: Decimal = Decimal("1000"), positions: tuple[Position, ...] = ()) -> Portfolio:
    return Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Core",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance(currency="USD", amount=cash),
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        positions=positions,
    )


def _executed_trade(portfolio: Portfolio, *, quantity: Decimal, price: Decimal) -> ExecutedTrade:
    proposal = TradeProposal(
        decision_cycle_id=uuid4(),
        portfolio_id=portfolio.portfolio_id,
        security=_security(),
        action="BUY",
        target_weight=Decimal("0.1"),
        proposed_notional_amount=quantity * price,
        proposed_quantity=quantity,
        price_source_timestamp=datetime(2026, 8, 12, 20, tzinfo=UTC),
        reason_reference="decision-1",
    )
    validated = ValidatedTrade(
        proposal=proposal,
        validation_timestamp=datetime(2026, 8, 12, 20, 1, tzinfo=UTC),
    )
    return ExecutedTrade(
        validated_trade=validated,
        executed_quantity=quantity,
        execution_price=price,
        source_provider_identity="test-provider",
        market_date=date(2026, 8, 12),
        currency="USD",
        price_convention="regular-session-close",
        executed_at=datetime(2026, 8, 12, 20, 1, tzinfo=UTC),
    )


def test_apply_contribution_returns_new_portfolio_and_increases_cash() -> None:
    portfolio = _portfolio()
    contribution = Contribution(
        amount=Decimal("250.1234"),
        currency="USD",
        effective_at=datetime(2026, 8, 13, tzinfo=UTC),
        received_at=datetime(2026, 8, 13, 1, tzinfo=UTC),
        source="bank transfer",
    )

    updated = PortfolioService.apply_contribution(portfolio, contribution)

    assert updated is not portfolio
    assert portfolio.cash_balance.amount == Decimal("1000")
    assert updated.cash_balance.amount == Decimal("1250.1234")
    assert updated.positions == portfolio.positions


def test_apply_contribution_rejects_currency_mismatch() -> None:
    contribution = Contribution(
        amount=Decimal("1"), currency="EUR", effective_at=datetime(2026, 8, 13, tzinfo=UTC),
        received_at=datetime(2026, 8, 13, tzinfo=UTC), source="bank transfer",
    )

    with pytest.raises(ValueError, match="currency"):
        PortfolioService.apply_contribution(_portfolio(), contribution)


def test_calculate_target_purchase_calculates_exact_new_position_allocation() -> None:
    calculation = PortfolioService.calculate_target_purchase(
        _portfolio(), _security(), Decimal("0.25"), Decimal("125")
    )

    assert calculation.portfolio_value == Decimal("1000")
    assert calculation.target_dollar_allocation == Decimal("250.00")
    assert calculation.required_purchase_amount == Decimal("250.00")
    assert calculation.purchasable_quantity == Decimal("2.00000000")
    assert calculation.cash_usage == Decimal("250.00000000")
    assert calculation.remaining_cash == Decimal("750.00000000")


def test_calculate_target_purchase_uses_existing_position_to_find_shortfall() -> None:
    position = Position(_security(), Decimal("2"), Decimal("180"), Decimal("100"))
    calculation = PortfolioService.calculate_target_purchase(
        _portfolio(cash=Decimal("800"), positions=(position,)), _security(), Decimal("0.3"), Decimal("100")
    )

    assert calculation.current_security_value == Decimal("200")
    assert calculation.target_dollar_allocation == Decimal("300.0")
    assert calculation.required_purchase_amount == Decimal("100.0")
    assert calculation.purchasable_quantity == Decimal("1.00000000")


def test_calculate_target_purchase_rounds_down_and_never_overspends_cash() -> None:
    calculation = PortfolioService.calculate_target_purchase(
        _portfolio(cash=Decimal("10")), _security(), Decimal("1"), Decimal("3")
    )

    assert calculation.purchasable_quantity == Decimal("3.33333333")
    assert calculation.cash_usage == Decimal("9.99999999")
    assert calculation.cash_usage <= Decimal("10")
    assert calculation.remaining_cash == Decimal("0.00000001")


def test_calculate_target_purchase_handles_zero_cash_and_target_already_met() -> None:
    zero_cash = PortfolioService.calculate_target_purchase(
        _portfolio(cash=Decimal("0")), _security(), Decimal("0.1"), Decimal("100")
    )
    existing_position = Position(_security(), Decimal("2"), Decimal("180"), Decimal("100"))
    already_met = PortfolioService.calculate_target_purchase(
        _portfolio(cash=Decimal("800"), positions=(existing_position,)), _security(), Decimal("0.1"), Decimal("100")
    )

    assert zero_cash.purchasable_quantity == Decimal("0")
    assert zero_cash.cash_usage == Decimal("0")
    assert already_met.required_purchase_amount == Decimal("0")
    assert already_met.purchasable_quantity == Decimal("0")


def test_calculate_target_purchase_rejects_out_of_policy_target_weight_precision() -> None:
    with pytest.raises(ValueError, match="decimal places"):
        PortfolioService.calculate_target_purchase(
            _portfolio(), _security(), Decimal("0.1234567"), Decimal("100")
        )


def test_calculate_target_purchase_rejects_zero_weight_buy() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        PortfolioService.calculate_target_purchase(_portfolio(), _security(), Decimal("0"), Decimal("100"))


def test_calculate_target_purchase_aligns_existing_security_to_execution_price() -> None:
    target = Position(_security(), Decimal("2"), Decimal("180"), Decimal("100"))
    non_target_security = SecurityIdentity(ticker="MSFT", security_type="EQUITY", exchange="NASDAQ", currency="USD")
    non_target = Position(non_target_security, Decimal("1"), Decimal("150"), Decimal("200"))
    portfolio = _portfolio(cash=Decimal("600"), positions=(target, non_target))

    calculation = PortfolioService.calculate_target_purchase(portfolio, _security(), Decimal("0.5"), Decimal("200"))

    assert calculation.portfolio_value == Decimal("1200")
    assert calculation.current_security_value == Decimal("400")
    assert calculation.target_dollar_allocation == Decimal("600.0")
    assert calculation.required_purchase_amount == Decimal("200.0")
    assert calculation.purchasable_quantity == Decimal("1.00000000")
    assert calculation.current_security_value + calculation.cash_usage == calculation.target_dollar_allocation


def test_calculate_target_purchase_handles_exact_cash_exhaustion_and_sub_increment_amount() -> None:
    exhausted = PortfolioService.calculate_target_purchase(
        _portfolio(cash=Decimal("100")), _security(), Decimal("1"), Decimal("100")
    )
    sub_increment = PortfolioService.calculate_target_purchase(
        _portfolio(cash=Decimal("0.000000001")), _security(), Decimal("1"), Decimal("1")
    )

    assert exhausted.cash_usage == Decimal("100.00000000")
    assert exhausted.remaining_cash == Decimal("0")
    assert sub_increment.required_purchase_amount == Decimal("0.000000001")
    assert sub_increment.purchasable_quantity == Decimal("0")
    assert sub_increment.cash_usage == Decimal("0")
    assert sub_increment.remaining_cash == Decimal("0.000000001")


def test_target_purchase_calculation_rejects_contradictory_derived_fields() -> None:
    with pytest.raises(ValueError, match="cash_usage"):
        TargetPurchaseCalculation(
            security=_security(),
            portfolio_value=Decimal("100"),
            target_weight=Decimal("1"),
            execution_price=Decimal("100"),
            target_dollar_allocation=Decimal("100"),
            current_security_value=Decimal("0"),
            required_purchase_amount=Decimal("100"),
            available_cash=Decimal("100"),
            purchasable_quantity=Decimal("1"),
            cash_usage=Decimal("99"),
            remaining_cash=Decimal("1"),
        )


def test_target_purchase_calculation_rejects_structurally_impossible_portfolio_values() -> None:
    common_arguments = {
        "security": _security(),
        "portfolio_value": Decimal("100"),
        "target_weight": Decimal("0.5"),
        "execution_price": Decimal("100"),
        "target_dollar_allocation": Decimal("50"),
        "current_security_value": Decimal("0"),
        "required_purchase_amount": Decimal("50"),
        "available_cash": Decimal("50"),
        "purchasable_quantity": Decimal("0.5"),
        "cash_usage": Decimal("50"),
        "remaining_cash": Decimal("0"),
    }

    with pytest.raises(ValueError, match="available_cash"):
        TargetPurchaseCalculation(available_cash=Decimal("101"), remaining_cash=Decimal("51"), **{
            key: value for key, value in common_arguments.items() if key not in {"available_cash", "remaining_cash"}
        })
    with pytest.raises(ValueError, match="current_security_value"):
        TargetPurchaseCalculation(
            current_security_value=Decimal("101"),
            required_purchase_amount=Decimal("0"),
            available_cash=Decimal("0"),
            purchasable_quantity=Decimal("0"),
            cash_usage=Decimal("0"),
            remaining_cash=Decimal("0"),
            **{key: value for key, value in common_arguments.items() if key not in {
                "current_security_value", "required_purchase_amount", "available_cash", "purchasable_quantity", "cash_usage", "remaining_cash"
            }},
        )


def test_target_purchase_calculation_allows_structural_equality_boundaries() -> None:
    calculation = TargetPurchaseCalculation(
        security=_security(),
        portfolio_value=Decimal("100"),
        target_weight=Decimal("1"),
        execution_price=Decimal("100"),
        target_dollar_allocation=Decimal("100"),
        current_security_value=Decimal("100"),
        required_purchase_amount=Decimal("0"),
        available_cash=Decimal("100"),
        purchasable_quantity=Decimal("0"),
        cash_usage=Decimal("0"),
        remaining_cash=Decimal("100"),
    )

    assert calculation.available_cash == calculation.portfolio_value
    assert calculation.current_security_value == calculation.portfolio_value


def test_execute_validated_trade_creates_new_position_and_updates_cash() -> None:
    portfolio = _portfolio()
    updated = PortfolioService.execute_validated_trade(
        portfolio, _executed_trade(portfolio, quantity=Decimal("2.5"), price=Decimal("100"))
    )

    assert portfolio.positions == ()
    assert updated.cash_balance.amount == Decimal("750.0")
    assert portfolio.cash_balance.amount == Decimal("1000")
    assert updated.positions == (Position(_security(), Decimal("2.5"), Decimal("250"), Decimal("100")),)
    assert updated.current_market_value == Decimal("250.0")


def test_execute_validated_trade_updates_existing_position_with_weighted_average_cost_basis() -> None:
    existing = Position(_security(), Decimal("2"), Decimal("160"), Decimal("90"))
    portfolio = _portfolio(cash=Decimal("800"), positions=(existing,))
    updated = PortfolioService.execute_validated_trade(
        portfolio, _executed_trade(portfolio, quantity=Decimal("3"), price=Decimal("120"))
    )

    assert updated.cash_balance.amount == Decimal("440")
    assert updated.positions[0].quantity == Decimal("5")
    assert updated.positions[0].total_cost_basis == Decimal("520")
    assert updated.positions[0].average_cost_basis == Decimal("104")
    assert updated.positions[0].market_price == Decimal("120")
    assert updated.positions[0].market_value == Decimal("600")


def test_execute_validated_trade_supports_repeated_buys() -> None:
    portfolio = _portfolio()
    after_first_buy = PortfolioService.execute_validated_trade(
        portfolio, _executed_trade(portfolio, quantity=Decimal("2"), price=Decimal("100"))
    )
    after_second_buy = PortfolioService.execute_validated_trade(
        after_first_buy, _executed_trade(after_first_buy, quantity=Decimal("3"), price=Decimal("120"))
    )

    assert len(after_second_buy.positions) == 1
    assert after_second_buy.positions[0].quantity == Decimal("5")
    assert after_second_buy.positions[0].average_cost_basis == Decimal("112")
    assert after_second_buy.cash_balance.amount == Decimal("440")


def test_execute_validated_trade_preserves_non_terminating_average_with_authoritative_total_cost() -> None:
    portfolio = _portfolio()
    after_first_buy = PortfolioService.execute_validated_trade(
        portfolio, _executed_trade(portfolio, quantity=Decimal("1"), price=Decimal("100"))
    )

    updated = PortfolioService.execute_validated_trade(
        after_first_buy,
        _executed_trade(after_first_buy, quantity=Decimal("2"), price=Decimal("101")),
    )

    assert updated.positions[0].total_cost_basis == Decimal("302")
    assert updated.positions[0].average_cost_basis == Decimal("100.6666666666666666666666667")


def test_execute_validated_trade_rejects_insufficient_cash_and_wrong_portfolio() -> None:
    portfolio = _portfolio(cash=Decimal("100"))

    with pytest.raises(ValueError, match="available cash"):
        PortfolioService.execute_validated_trade(
            portfolio, _executed_trade(portfolio, quantity=Decimal("2"), price=Decimal("100"))
        )
    with pytest.raises(ValueError, match="portfolio_id"):
        PortfolioService.execute_validated_trade(
            portfolio, _executed_trade(_portfolio(), quantity=Decimal("1"), price=Decimal("100"))
        )


def test_execute_validated_trade_replaces_the_portfolio_decision_cycle() -> None:
    portfolio = _portfolio()
    prior_cycle_id = uuid4()
    portfolio = Portfolio(
        portfolio_id=portfolio.portfolio_id,
        portfolio_name=portfolio.portfolio_name,
        base_currency=portfolio.base_currency,
        starting_capital=portfolio.starting_capital,
        cash_balance=portfolio.cash_balance,
        created_at=portfolio.created_at,
        decision_cycle_id=prior_cycle_id,
    )
    executed_trade = _executed_trade(portfolio, quantity=Decimal("1"), price=Decimal("100"))

    updated = PortfolioService.execute_validated_trade(portfolio, executed_trade)

    assert portfolio.decision_cycle_id == prior_cycle_id
    assert updated.decision_cycle_id == executed_trade.decision_cycle_id


def test_portfolio_snapshot_uses_current_cash_and_positions() -> None:
    position = Position(_security(), Decimal("2"), Decimal("160"), Decimal("125"))
    portfolio = _portfolio(cash=Decimal("750"), positions=(position,))

    snapshot = PortfolioService.portfolio_snapshot(
        portfolio,
        as_of_timestamp=datetime(2026, 8, 13, tzinfo=UTC),
        source_provider_identity="test-provider",
        market_date=date(2026, 8, 13),
        source_price_timestamp=datetime(2026, 8, 13, tzinfo=UTC),
        price_convention="regular-session-close",
    )

    assert snapshot.cash_balance == Decimal("750")
    assert snapshot.positions_market_value == Decimal("250")
    assert snapshot.total_value == Decimal("1000")


def test_service_calculations_ignore_ambient_decimal_context() -> None:
    def calculate(precision: int) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        with localcontext() as context:
            context.prec = precision
            portfolio = _portfolio(cash=Decimal("100000000.123456"))
            calculation = PortfolioService.calculate_target_purchase(
                portfolio, _security(), Decimal("0.123456"), Decimal("102.345678")
            )
            updated = PortfolioService.execute_validated_trade(
                portfolio, _executed_trade(portfolio, quantity=Decimal("1.23456789"), price=Decimal("102.345678"))
            )
            snapshot = PortfolioService.portfolio_snapshot(
                updated,
                as_of_timestamp=datetime(2026, 8, 13, tzinfo=UTC),
                source_provider_identity="test-provider",
                market_date=date(2026, 8, 13),
                source_price_timestamp=datetime(2026, 8, 13, tzinfo=UTC),
                price_convention="regular-session-close",
            )
            return calculation.cash_usage, updated.cash_balance.amount, updated.current_total_value, snapshot.total_value

    assert calculate(6) == calculate(50)
