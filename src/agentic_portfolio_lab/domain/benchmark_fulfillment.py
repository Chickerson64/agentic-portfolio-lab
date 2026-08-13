"""Deterministic, quote-attributed paper fulfillment for the SPY benchmark."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from .constitution import PassiveIndexInvestmentIntent, PROVIDER_ATTRIBUTED_PAPER_QUOTE
from .portfolio import CashBalance, Portfolio, Position, _calculate_decimal, _require_aware_datetime
from .portfolio_service import PortfolioService, TargetPurchaseCalculation
from .valuation import BenchmarkPortfolio, PriceObservation


@dataclass(frozen=True, slots=True)
class PassiveIndexFulfillment:
    """One paper-only SPY deployment with exact provider observation lineage."""

    intent: PassiveIndexInvestmentIntent
    price_observation: PriceObservation
    original_benchmark_portfolio: BenchmarkPortfolio
    fulfilled_benchmark_portfolio: BenchmarkPortfolio
    target_purchase: TargetPurchaseCalculation
    quantity: Decimal
    notional: Decimal
    fulfilled_at: datetime
    fulfillment_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not isinstance(self.intent, PassiveIndexInvestmentIntent):
            raise TypeError("intent must be a PassiveIndexInvestmentIntent")
        if self.intent.deployment_rule != PROVIDER_ATTRIBUTED_PAPER_QUOTE:
            raise ValueError("paper fulfillment requires PROVIDER_ATTRIBUTED_PAPER_QUOTE")
        if not isinstance(self.price_observation, PriceObservation):
            raise TypeError("price_observation must be a PriceObservation")
        if not isinstance(self.original_benchmark_portfolio, BenchmarkPortfolio) or not isinstance(self.fulfilled_benchmark_portfolio, BenchmarkPortfolio):
            raise TypeError("benchmark portfolios must be BenchmarkPortfolio instances")
        if self.intent.benchmark_portfolio != self.original_benchmark_portfolio:
            raise ValueError("intent must describe the original benchmark portfolio")
        if self.price_observation.security != self.intent.security:
            raise ValueError("price observation must match benchmark SPY security")
        if self.price_observation.currency != self.intent.currency:
            raise ValueError("price observation currency must match benchmark cash")
        if not isinstance(self.target_purchase, TargetPurchaseCalculation):
            raise TypeError("target_purchase must be a TargetPurchaseCalculation")
        if self.target_purchase != PortfolioService.calculate_target_purchase(self.original_benchmark_portfolio.portfolio, self.intent.security, Decimal("1"), self.price_observation.observed_price):
            raise ValueError("target_purchase must deploy all feasible benchmark cash")
        if self.quantity != self.target_purchase.purchasable_quantity or self.notional != self.target_purchase.cash_usage:
            raise ValueError("quantity and notional must match deterministic target purchase")
        if self.quantity <= 0 or self.notional <= 0:
            raise ValueError("paper fulfillment quantity and notional must be positive")
        _require_aware_datetime(self.fulfilled_at, field_name="fulfilled_at")
        if self.fulfilled_at < self.price_observation.observed_at:
            raise ValueError("fulfilled_at must not precede price observation")
        if not isinstance(self.fulfillment_id, UUID):
            raise TypeError("fulfillment_id must be a UUID")
        if self.fulfilled_benchmark_portfolio != _fulfilled_portfolio(self.original_benchmark_portfolio, self.price_observation, self.quantity, self.notional):
            raise ValueError("fulfilled benchmark portfolio must exactly reflect the paper quote purchase")

    @property
    def provider_identity(self) -> str:
        return self.price_observation.source_provider_identity


def _fulfilled_portfolio(original: BenchmarkPortfolio, observation: PriceObservation, quantity: Decimal, notional: Decimal) -> BenchmarkPortfolio:
    portfolio = original.portfolio
    existing = next((position for position in portfolio.positions if position.security == observation.security), None)
    if existing is None:
        positions = portfolio.positions + (Position(observation.security, quantity, notional, observation.observed_price),)
    else:
        positions = tuple(
            Position(position.security, _calculate_decimal(lambda: position.quantity + quantity), _calculate_decimal(lambda: position.total_cost_basis + notional), observation.observed_price)
            if position.security == observation.security else position
            for position in portfolio.positions
        )
    updated = Portfolio(portfolio.portfolio_id, portfolio.portfolio_name, portfolio.base_currency, portfolio.starting_capital, CashBalance(portfolio.base_currency, _calculate_decimal(lambda: portfolio.cash_balance.amount - notional)), portfolio.created_at, positions, portfolio.status, portfolio.decision_cycle_id)
    return BenchmarkPortfolio(updated, original.benchmark_security)


def fulfill_paper_intent(intent: PassiveIndexInvestmentIntent, observation: PriceObservation, *, fulfilled_at: datetime) -> PassiveIndexFulfillment:
    calculation = PortfolioService.calculate_target_purchase(intent.benchmark_portfolio.portfolio, intent.security, Decimal("1"), observation.observed_price)
    if calculation.purchasable_quantity.is_zero():
        raise ValueError("benchmark paper fulfillment requires positive feasible quantity")
    fulfilled = _fulfilled_portfolio(intent.benchmark_portfolio, observation, calculation.purchasable_quantity, calculation.cash_usage)
    return PassiveIndexFulfillment(intent, observation, intent.benchmark_portfolio, fulfilled, calculation, calculation.purchasable_quantity, calculation.cash_usage, fulfilled_at)
