"""Deterministic portfolio state transitions for the buy-only MVP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from .portfolio import (
    CashBalance,
    Contribution,
    Portfolio,
    PortfolioValuationSnapshot,
    Position,
    SecurityIdentity,
    _calculate_decimal,
    _require_max_decimal_places,
    _require_non_negative_decimal,
    _require_positive_decimal,
)
from .trades import ExecutedTrade


def _require_target_weight(value: Decimal) -> Decimal:
    value = _require_positive_decimal(value, field_name="target_weight")
    value = _require_max_decimal_places(value, Decimal("0.000001"), field_name="target_weight")
    if value > Decimal("1"):
        raise ValueError("target_weight must not exceed 1")
    return value


def _floor_divide_to_quantity_places(amount: Decimal, price: Decimal) -> Decimal:
    """Return floor(amount / price) at the settled eight-place quantity scale.

    Decimal division can have an infinite expansion, so this uses the values'
    exact coefficients rather than a bounded Decimal context. The only rounding
    is the required round-down to the supported fractional-share increment.
    """
    amount_tuple = amount.as_tuple()
    price_tuple = price.as_tuple()
    amount_coefficient = int("".join(map(str, amount_tuple.digits)) or "0")
    price_coefficient = int("".join(map(str, price_tuple.digits)) or "0")
    exponent_difference = amount_tuple.exponent - price_tuple.exponent + 8
    if exponent_difference >= 0:
        numerator = amount_coefficient * (10 ** exponent_difference)
        denominator = price_coefficient
    else:
        numerator = amount_coefficient
        denominator = price_coefficient * (10 ** (-exponent_difference))
    quantity_coefficient = numerator // denominator
    return Decimal(f"{quantity_coefficient}e-8")


@dataclass(frozen=True, slots=True)
class TargetPurchaseCalculation:
    """The deterministic buy amount needed to reach an approved target weight."""

    security: SecurityIdentity
    portfolio_value: Decimal
    target_weight: Decimal
    execution_price: Decimal
    target_dollar_allocation: Decimal
    current_security_value: Decimal
    required_purchase_amount: Decimal
    available_cash: Decimal
    purchasable_quantity: Decimal
    cash_usage: Decimal
    remaining_cash: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        object.__setattr__(self, "portfolio_value", _require_non_negative_decimal(self.portfolio_value, field_name="portfolio_value"))
        object.__setattr__(self, "target_weight", _require_target_weight(self.target_weight))
        object.__setattr__(self, "execution_price", _require_positive_decimal(self.execution_price, field_name="execution_price"))
        for field_name in (
            "target_dollar_allocation",
            "current_security_value",
            "required_purchase_amount",
            "available_cash",
            "purchasable_quantity",
            "cash_usage",
            "remaining_cash",
        ):
            object.__setattr__(self, field_name, _require_non_negative_decimal(getattr(self, field_name), field_name=field_name))
        if self.available_cash > self.portfolio_value:
            raise ValueError("available_cash must not exceed portfolio_value")
        if self.current_security_value > self.portfolio_value:
            raise ValueError("current_security_value must not exceed portfolio_value")
        expected_target_allocation = _calculate_decimal(lambda: self.portfolio_value * self.target_weight)
        if self.target_dollar_allocation != expected_target_allocation:
            raise ValueError("target_dollar_allocation must equal portfolio_value multiplied by target_weight")
        expected_required_purchase = _calculate_decimal(
            lambda: max(Decimal("0"), self.target_dollar_allocation - self.current_security_value)
        )
        if self.required_purchase_amount != expected_required_purchase:
            raise ValueError("required_purchase_amount must equal the target allocation shortfall")
        expected_quantity = _floor_divide_to_quantity_places(
            _calculate_decimal(lambda: min(self.required_purchase_amount, self.available_cash)),
            self.execution_price,
        )
        if self.purchasable_quantity != expected_quantity:
            raise ValueError("purchasable_quantity must be the rounded-down feasible quantity")
        expected_cash_usage = _calculate_decimal(lambda: self.purchasable_quantity * self.execution_price)
        if self.cash_usage != expected_cash_usage:
            raise ValueError("cash_usage must equal purchasable_quantity multiplied by execution_price")
        if self.cash_usage > self.available_cash:
            raise ValueError("cash_usage must not exceed available_cash")
        expected_remaining_cash = _calculate_decimal(lambda: self.available_cash - self.cash_usage)
        if self.remaining_cash != expected_remaining_cash:
            raise ValueError("remaining_cash must equal available_cash minus cash_usage")


class PortfolioService:
    """Pure operations that return replacement immutable portfolio state."""

    @staticmethod
    def apply_contribution(portfolio: Portfolio, contribution: Contribution) -> Portfolio:
        if not isinstance(portfolio, Portfolio):
            raise TypeError("portfolio must be a Portfolio")
        if not isinstance(contribution, Contribution):
            raise TypeError("contribution must be a Contribution")
        if contribution.currency != portfolio.base_currency:
            raise ValueError("contribution currency must match portfolio base_currency")

        updated_cash = _calculate_decimal(lambda: portfolio.cash_balance.amount + contribution.amount)
        return PortfolioService._with_state(
            portfolio,
            cash_balance=CashBalance(currency=portfolio.base_currency, amount=updated_cash),
            positions=portfolio.positions,
        )

    @staticmethod
    def calculate_target_purchase(
        portfolio: Portfolio,
        security: SecurityIdentity,
        target_weight: Decimal,
        execution_price: Decimal,
    ) -> TargetPurchaseCalculation:
        if not isinstance(portfolio, Portfolio):
            raise TypeError("portfolio must be a Portfolio")
        if not isinstance(security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        if security.currency != portfolio.base_currency:
            raise ValueError("security currency must match portfolio base_currency")
        target_weight = _require_target_weight(target_weight)
        execution_price = _require_positive_decimal(execution_price, field_name="execution_price")

        existing_position = next((position for position in portfolio.positions if position.security == security), None)
        current_security_value = (
            Decimal("0")
            if existing_position is None
            else _calculate_decimal(lambda: existing_position.quantity * execution_price)
        )
        # Align the target security's value with the supplied execution price.
        portfolio_value = (
            portfolio.current_total_value
            if existing_position is None
            else _calculate_decimal(
                lambda: portfolio.current_total_value - existing_position.market_value + current_security_value
            )
        )
        target_dollar_allocation = _calculate_decimal(lambda: portfolio_value * target_weight)
        required_purchase_amount = _calculate_decimal(
            lambda: max(Decimal("0"), target_dollar_allocation - current_security_value)
        )
        cash_limited_purchase = _calculate_decimal(
            lambda: min(required_purchase_amount, portfolio.cash_balance.amount)
        )
        purchasable_quantity = _floor_divide_to_quantity_places(cash_limited_purchase, execution_price)
        cash_usage = _calculate_decimal(lambda: purchasable_quantity * execution_price)
        remaining_cash = _calculate_decimal(lambda: portfolio.cash_balance.amount - cash_usage)

        return TargetPurchaseCalculation(
            security=security,
            portfolio_value=portfolio_value,
            target_weight=target_weight,
            execution_price=execution_price,
            target_dollar_allocation=target_dollar_allocation,
            current_security_value=current_security_value,
            required_purchase_amount=required_purchase_amount,
            available_cash=portfolio.cash_balance.amount,
            purchasable_quantity=purchasable_quantity,
            cash_usage=cash_usage,
            remaining_cash=remaining_cash,
        )

    @staticmethod
    def execute_validated_trade(portfolio: Portfolio, executed_trade: ExecutedTrade) -> Portfolio:
        if not isinstance(portfolio, Portfolio):
            raise TypeError("portfolio must be a Portfolio")
        if not isinstance(executed_trade, ExecutedTrade):
            raise TypeError("executed_trade must be an ExecutedTrade")
        if executed_trade.portfolio_id != portfolio.portfolio_id:
            raise ValueError("executed_trade portfolio_id must match portfolio")
        if executed_trade.currency != portfolio.base_currency:
            raise ValueError("executed_trade currency must match portfolio base_currency")
        if executed_trade.security.currency != portfolio.base_currency:
            raise ValueError("executed_trade security currency must match portfolio base_currency")
        if executed_trade.executed_notional > portfolio.cash_balance.amount:
            raise ValueError("executed trade must not exceed available cash")

        existing_position = next(
            (position for position in portfolio.positions if position.security == executed_trade.security),
            None,
        )
        if existing_position is None:
            updated_position = Position(
                security=executed_trade.security,
                quantity=executed_trade.executed_quantity,
                total_cost_basis=executed_trade.executed_notional,
                market_price=executed_trade.execution_price,
            )
            updated_positions = portfolio.positions + (updated_position,)
        else:
            updated_quantity = _calculate_decimal(lambda: existing_position.quantity + executed_trade.executed_quantity)
            updated_total_cost_basis = _calculate_decimal(
                lambda: existing_position.total_cost_basis + executed_trade.executed_notional
            )
            updated_position = Position(
                security=existing_position.security,
                quantity=updated_quantity,
                total_cost_basis=updated_total_cost_basis,
                market_price=executed_trade.execution_price,
            )
            updated_positions = tuple(
                updated_position if position.security == executed_trade.security else position
                for position in portfolio.positions
            )

        updated_cash = _calculate_decimal(lambda: portfolio.cash_balance.amount - executed_trade.executed_notional)
        return PortfolioService._with_state(
            portfolio,
            cash_balance=CashBalance(currency=portfolio.base_currency, amount=updated_cash),
            positions=updated_positions,
            decision_cycle_id=executed_trade.decision_cycle_id,
        )

    @staticmethod
    def portfolio_snapshot(
        portfolio: Portfolio,
        *,
        as_of_timestamp: datetime,
        source_provider_identity: str,
        market_date: date,
        source_price_timestamp: datetime,
        price_convention: str,
    ) -> PortfolioValuationSnapshot:
        if not isinstance(portfolio, Portfolio):
            raise TypeError("portfolio must be a Portfolio")
        return PortfolioValuationSnapshot.from_components(
            portfolio_id=portfolio.portfolio_id,
            as_of_timestamp=as_of_timestamp,
            cash_balance=portfolio.cash_balance,
            positions=portfolio.positions,
            source_provider_identity=source_provider_identity,
            market_date=market_date,
            source_price_timestamp=source_price_timestamp,
            price_convention=price_convention,
        )

    @staticmethod
    def _with_state(
        portfolio: Portfolio,
        *,
        cash_balance: CashBalance,
        positions: tuple[Position, ...],
        decision_cycle_id: UUID | None = None,
    ) -> Portfolio:
        return Portfolio(
            portfolio_id=portfolio.portfolio_id,
            portfolio_name=portfolio.portfolio_name,
            base_currency=portfolio.base_currency,
            starting_capital=portfolio.starting_capital,
            cash_balance=cash_balance,
            created_at=portfolio.created_at,
            positions=positions,
            status=portfolio.status,
            decision_cycle_id=portfolio.decision_cycle_id if decision_cycle_id is None else decision_cycle_id,
        )
