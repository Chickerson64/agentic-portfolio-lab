"""Deterministic paired funding from an external Cash Event."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from .portfolio import (
    Contribution,
    Portfolio,
    _calculate_decimal,
    _canonical_upper_text,
    _require_aware_datetime,
    _require_non_empty_text,
    _require_positive_decimal,
)
from .portfolio_service import PortfolioService
from .valuation import BenchmarkPortfolio


@dataclass(frozen=True, slots=True)
class CashEvent:
    """One externally supplied, one-time source of buying power."""

    amount: Decimal
    currency: str
    effective_at: datetime
    source: str
    event_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, UUID):
            raise TypeError("event_id must be a UUID")
        object.__setattr__(self, "amount", _require_positive_decimal(self.amount, field_name="amount"))
        object.__setattr__(self, "currency", _canonical_upper_text(self.currency, field_name="currency"))
        _require_aware_datetime(self.effective_at, field_name="effective_at")
        object.__setattr__(self, "source", _require_non_empty_text(self.source, field_name="source"))


def _assert_cash_only_funding(
    *,
    original: Portfolio,
    funded: Portfolio,
    cash_event: CashEvent,
    portfolio_label: str,
) -> None:
    if original.base_currency != cash_event.currency:
        raise ValueError(f"CashEvent currency must match {portfolio_label} portfolio base_currency")
    if funded.base_currency != original.base_currency:
        raise ValueError(f"funded {portfolio_label} portfolio base_currency must remain unchanged")
    if (
        funded.portfolio_id != original.portfolio_id
        or funded.portfolio_name != original.portfolio_name
        or funded.starting_capital != original.starting_capital
        or funded.created_at != original.created_at
        or funded.positions != original.positions
        or funded.status != original.status
        or funded.decision_cycle_id != original.decision_cycle_id
    ):
        raise ValueError(f"CashEvent funding may change only {portfolio_label} portfolio cash")
    expected_cash = _calculate_decimal(lambda: original.cash_balance.amount + cash_event.amount)
    if funded.cash_balance.currency != original.base_currency or funded.cash_balance.amount != expected_cash:
        raise ValueError(f"funded {portfolio_label} portfolio cash must increase by the CashEvent amount")


@dataclass(frozen=True, slots=True)
class CashEventFundingResult:
    """Auditable immutable state resulting from one paired Cash Event."""

    cash_event: CashEvent
    original_managed_portfolio: Portfolio
    funded_managed_portfolio: Portfolio
    original_benchmark_portfolio: BenchmarkPortfolio
    funded_benchmark_portfolio: BenchmarkPortfolio

    def __post_init__(self) -> None:
        if not isinstance(self.cash_event, CashEvent):
            raise TypeError("cash_event must be a CashEvent")
        if not isinstance(self.original_managed_portfolio, Portfolio):
            raise TypeError("original_managed_portfolio must be a Portfolio")
        if not isinstance(self.funded_managed_portfolio, Portfolio):
            raise TypeError("funded_managed_portfolio must be a Portfolio")
        if not isinstance(self.original_benchmark_portfolio, BenchmarkPortfolio):
            raise TypeError("original_benchmark_portfolio must be a BenchmarkPortfolio")
        if not isinstance(self.funded_benchmark_portfolio, BenchmarkPortfolio):
            raise TypeError("funded_benchmark_portfolio must be a BenchmarkPortfolio")

        _assert_cash_only_funding(
            original=self.original_managed_portfolio,
            funded=self.funded_managed_portfolio,
            cash_event=self.cash_event,
            portfolio_label="managed",
        )
        if self.funded_benchmark_portfolio.benchmark_security != self.original_benchmark_portfolio.benchmark_security:
            raise ValueError("CashEvent funding must not change benchmark security")
        _assert_cash_only_funding(
            original=self.original_benchmark_portfolio.portfolio,
            funded=self.funded_benchmark_portfolio.portfolio,
            cash_event=self.cash_event,
            portfolio_label="benchmark",
        )

    @property
    def event_id(self) -> UUID:
        """The shared external event identity for both funding paths."""
        return self.cash_event.event_id

    @property
    def applied_at(self) -> datetime:
        """Funding is applied at the Cash Event's supplied effective time."""
        return self.cash_event.effective_at


class CashEventFundingWorkflow:
    """Apply one Cash Event to paired managed and benchmark cash state."""

    @staticmethod
    def apply(
        cash_event: CashEvent,
        managed_portfolio: Portfolio,
        benchmark_portfolio: BenchmarkPortfolio,
    ) -> CashEventFundingResult:
        if not isinstance(cash_event, CashEvent):
            raise TypeError("cash_event must be a CashEvent")
        if not isinstance(managed_portfolio, Portfolio):
            raise TypeError("managed_portfolio must be a Portfolio")
        if not isinstance(benchmark_portfolio, BenchmarkPortfolio):
            raise TypeError("benchmark_portfolio must be a BenchmarkPortfolio")
        if managed_portfolio.base_currency != cash_event.currency:
            raise ValueError("CashEvent currency must match managed portfolio base_currency")
        if benchmark_portfolio.portfolio.base_currency != cash_event.currency:
            raise ValueError("CashEvent currency must match benchmark portfolio base_currency")

        # Contribution is the portfolio-local cash application of this shared external event.
        managed_contribution = Contribution(
            amount=cash_event.amount,
            currency=cash_event.currency,
            effective_at=cash_event.effective_at,
            received_at=cash_event.effective_at,
            source=cash_event.source,
        )
        benchmark_contribution = Contribution(
            amount=cash_event.amount,
            currency=cash_event.currency,
            effective_at=cash_event.effective_at,
            received_at=cash_event.effective_at,
            source=cash_event.source,
        )
        funded_managed = PortfolioService.apply_contribution(managed_portfolio, managed_contribution)
        funded_benchmark = benchmark_portfolio.receive_contribution(benchmark_contribution)

        return CashEventFundingResult(
            cash_event=cash_event,
            original_managed_portfolio=managed_portfolio,
            funded_managed_portfolio=funded_managed,
            original_benchmark_portfolio=benchmark_portfolio,
            funded_benchmark_portfolio=funded_benchmark,
        )
