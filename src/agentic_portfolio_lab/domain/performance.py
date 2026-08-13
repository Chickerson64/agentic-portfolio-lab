"""Immutable valuation-based performance history and comparison primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from .cash_events import CashEvent
from .portfolio import (
    Portfolio,
    Position,
    SecurityIdentity,
    _calculate_decimal,
    _calculate_informational_decimal,
    _canonical_upper_text,
    _require_non_negative_decimal,
    _require_positive_decimal,
)
from .valuation import BenchmarkPortfolio, PortfolioValuation


def _validate_snapshot_state(portfolio: Portfolio, valuation: PortfolioValuation) -> None:
    """Verify a supplied valuation remains structurally tied to one portfolio state."""
    if valuation.subject_id != portfolio.portfolio_id:
        raise ValueError("valuation subject_id must match portfolio")
    if valuation.currency != portfolio.base_currency:
        raise ValueError("valuation currency must match portfolio base_currency")
    if valuation.cash_value != portfolio.cash_balance.amount:
        raise ValueError("valuation cash_value must match portfolio cash_balance")

    positions_by_security: dict[SecurityIdentity, Position] = {position.security: position for position in portfolio.positions}
    valuations_by_security = {valuation_item.security: valuation_item for valuation_item in valuation.position_valuations}
    if set(positions_by_security) != set(valuations_by_security):
        raise ValueError("valuation positions must match portfolio positions")
    for security, position in positions_by_security.items():
        position_valuation = valuations_by_security[security]
        if (
            position_valuation.quantity != position.quantity
            or position_valuation.total_cost_basis != position.total_cost_basis
        ):
            raise ValueError("valuation position quantity and cost basis must match portfolio position")


def _normalize_cash_events(
    cash_events: tuple[CashEvent, ...] | list[CashEvent],
    *,
    portfolio: Portfolio,
    timestamp: datetime,
) -> tuple[CashEvent, ...]:
    if not isinstance(cash_events, (tuple, list)):
        raise TypeError("cash_events must be a tuple or list of CashEvent instances")
    normalized = tuple(cash_events)
    if not all(isinstance(cash_event, CashEvent) for cash_event in normalized):
        raise TypeError("cash_events must contain CashEvent instances")
    event_ids = tuple(cash_event.event_id for cash_event in normalized)
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("cash_events must not contain duplicate event_id values")
    if any(
        later.effective_at < earlier.effective_at
        for earlier, later in zip(normalized, normalized[1:], strict=False)
    ):
        raise ValueError("cash_events must be in nondecreasing effective_at order")
    for cash_event in normalized:
        if cash_event.currency != portfolio.base_currency:
            raise ValueError("CashEvent currency must match portfolio base_currency")
        if cash_event.effective_at < portfolio.created_at:
            raise ValueError("CashEvent effective_at must not precede portfolio creation")
        if cash_event.effective_at > timestamp:
            raise ValueError("CashEvent effective_at must not postdate performance snapshot")
    return normalized


@dataclass(frozen=True, slots=True)
class PerformanceSnapshot:
    """One immutable valuation event with an explicit external-capital basis.

    A snapshot is not a trade record. It can represent cash-only, HOLD, or
    price-movement periods. Cash Events provide the current MVP's structural
    external-capital linkage; persistence is required for authoritative proof
    that a supplied portfolio state was funded by every listed event.
    """

    portfolio: Portfolio
    valuation: PortfolioValuation
    baseline_value: Decimal
    cumulative_external_contributions: Decimal
    cash_events: tuple[CashEvent, ...] | list[CashEvent] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.portfolio, Portfolio):
            raise TypeError("portfolio must be a Portfolio")
        if not isinstance(self.valuation, PortfolioValuation):
            raise TypeError("valuation must be a PortfolioValuation")
        baseline_value = _require_positive_decimal(self.baseline_value, field_name="baseline_value")
        cumulative_contributions = _require_non_negative_decimal(
            self.cumulative_external_contributions,
            field_name="cumulative_external_contributions",
        )
        if self.valuation.as_of_timestamp < self.portfolio.created_at:
            raise ValueError("valuation as_of_timestamp must not precede portfolio creation")
        _validate_snapshot_state(self.portfolio, self.valuation)
        cash_events = _normalize_cash_events(
            self.cash_events,
            portfolio=self.portfolio,
            timestamp=self.valuation.as_of_timestamp,
        )
        object.__setattr__(self, "baseline_value", baseline_value)
        object.__setattr__(self, "cumulative_external_contributions", cumulative_contributions)
        object.__setattr__(self, "cash_events", cash_events)

    @property
    def timestamp(self) -> datetime:
        return self.valuation.as_of_timestamp

    @property
    def portfolio_value(self) -> Decimal:
        return self.valuation.total_value

    @property
    def cash_value(self) -> Decimal:
        return self.valuation.cash_value

    @property
    def positions_value(self) -> Decimal:
        return self.valuation.invested_value

    @property
    def contributed_capital_basis(self) -> Decimal:
        return _calculate_decimal(lambda: self.baseline_value + self.cumulative_external_contributions)

    @property
    def investment_gain(self) -> Decimal:
        return _calculate_decimal(
            lambda: self.portfolio_value - self.baseline_value - self.cumulative_external_contributions
        )

    @property
    def total_return(self) -> Decimal:
        return _calculate_informational_decimal(lambda: self.investment_gain / self.contributed_capital_basis)


def _validate_history_snapshots(
    snapshots: tuple[PerformanceSnapshot, ...],
    *,
    portfolio_id: UUID,
    currency: str,
    benchmark_security: SecurityIdentity | None = None,
) -> None:
    previous_timestamp: datetime | None = None
    baseline_value: Decimal | None = None
    reference_created_at: datetime | None = None
    reference_starting_capital: Decimal | None = None
    reference_base_currency: str | None = None
    cumulative_contributions = Decimal("0")
    event_ids: set[UUID] = set()
    for index, snapshot in enumerate(snapshots):
        if not isinstance(snapshot, PerformanceSnapshot):
            raise TypeError("snapshots must contain PerformanceSnapshot instances")
        if snapshot.portfolio.portfolio_id != portfolio_id:
            raise ValueError("snapshot portfolio identity must match history")
        if snapshot.valuation.currency != currency:
            raise ValueError("snapshot currency must match history currency")
        if reference_created_at is None:
            reference_created_at = snapshot.portfolio.created_at
            reference_starting_capital = snapshot.portfolio.starting_capital
            reference_base_currency = snapshot.portfolio.base_currency
        elif (
            snapshot.portfolio.created_at != reference_created_at
            or snapshot.portfolio.starting_capital != reference_starting_capital
            or snapshot.portfolio.base_currency != reference_base_currency
        ):
            raise ValueError("snapshot portfolio immutable lineage metadata must match history")
        if baseline_value is None:
            baseline_value = snapshot.portfolio_value
        if snapshot.baseline_value != baseline_value:
            raise ValueError("snapshot baseline_value must match the first history value")
        if previous_timestamp is not None and snapshot.timestamp <= previous_timestamp:
            raise ValueError("history snapshot timestamps must be strictly increasing")
        if index == 0 and snapshot.cash_events:
            raise ValueError("first history snapshot must not include post-baseline Cash Events")
        if previous_timestamp is not None:
            for cash_event in snapshot.cash_events:
                if cash_event.effective_at <= previous_timestamp:
                    raise ValueError("CashEvent effective_at must be after the prior snapshot timestamp")
        for cash_event in snapshot.cash_events:
            if cash_event.event_id in event_ids:
                raise ValueError("CashEvent may appear only once in a performance history")
            event_ids.add(cash_event.event_id)
            cumulative_contributions = _calculate_decimal(lambda: cumulative_contributions + cash_event.amount)
        if snapshot.cumulative_external_contributions != cumulative_contributions:
            raise ValueError("snapshot cumulative_external_contributions must equal recorded CashEvent amounts")
        previous_timestamp = snapshot.timestamp

        if benchmark_security is not None:
            BenchmarkPortfolio(snapshot.portfolio, benchmark_security)


@dataclass(frozen=True, slots=True)
class PortfolioPerformanceHistory:
    """Append-only valuation snapshots for one managed portfolio identity."""

    portfolio_id: UUID
    currency: str
    snapshots: tuple[PerformanceSnapshot, ...] | list[PerformanceSnapshot] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.portfolio_id, UUID):
            raise TypeError("portfolio_id must be a UUID")
        currency = _canonical_upper_text(self.currency, field_name="currency")
        snapshots = tuple(self.snapshots)
        _validate_history_snapshots(snapshots, portfolio_id=self.portfolio_id, currency=currency)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "snapshots", snapshots)

    def append(
        self,
        portfolio: Portfolio,
        valuation: PortfolioValuation,
        *,
        cash_events: tuple[CashEvent, ...] | list[CashEvent] = (),
    ) -> "PortfolioPerformanceHistory":
        """Return a replacement history with one supplied valuation event."""
        if not isinstance(portfolio, Portfolio):
            raise TypeError("portfolio must be a Portfolio")
        if not isinstance(valuation, PortfolioValuation):
            raise TypeError("valuation must be a PortfolioValuation")
        if portfolio.portfolio_id != self.portfolio_id:
            raise ValueError("portfolio must match history identity")
        baseline_value = self.snapshots[0].portfolio_value if self.snapshots else valuation.total_value
        prior_contributions = (
            self.snapshots[-1].cumulative_external_contributions if self.snapshots else Decimal("0")
        )
        normalized_cash_events = _normalize_cash_events(
            cash_events,
            portfolio=portfolio,
            timestamp=valuation.as_of_timestamp,
        )
        cumulative_contributions = _calculate_decimal(
            lambda: prior_contributions + sum((cash_event.amount for cash_event in normalized_cash_events), Decimal("0"))
        )
        snapshot = PerformanceSnapshot(
            portfolio,
            valuation,
            baseline_value,
            cumulative_contributions,
            normalized_cash_events,
        )
        return PortfolioPerformanceHistory(self.portfolio_id, self.currency, (*self.snapshots, snapshot))


@dataclass(frozen=True, slots=True)
class BenchmarkPerformanceHistory:
    """Append-only SPY benchmark valuation snapshots."""

    benchmark_portfolio_id: UUID
    benchmark_security: SecurityIdentity
    currency: str
    snapshots: tuple[PerformanceSnapshot, ...] | list[PerformanceSnapshot] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.benchmark_portfolio_id, UUID):
            raise TypeError("benchmark_portfolio_id must be a UUID")
        if not isinstance(self.benchmark_security, SecurityIdentity):
            raise TypeError("benchmark_security must be a SecurityIdentity")
        currency = _canonical_upper_text(self.currency, field_name="currency")
        if self.benchmark_security.ticker != "SPY":
            raise ValueError("benchmark_security ticker must be SPY")
        if self.benchmark_security.currency != currency:
            raise ValueError("benchmark_security currency must match history currency")
        snapshots = tuple(self.snapshots)
        _validate_history_snapshots(
            snapshots,
            portfolio_id=self.benchmark_portfolio_id,
            currency=currency,
            benchmark_security=self.benchmark_security,
        )
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "snapshots", snapshots)

    @classmethod
    def for_benchmark(cls, benchmark: BenchmarkPortfolio) -> "BenchmarkPerformanceHistory":
        if not isinstance(benchmark, BenchmarkPortfolio):
            raise TypeError("benchmark must be a BenchmarkPortfolio")
        return cls(
            benchmark_portfolio_id=benchmark.portfolio.portfolio_id,
            benchmark_security=benchmark.benchmark_security,
            currency=benchmark.portfolio.base_currency,
        )

    def append(
        self,
        benchmark: BenchmarkPortfolio,
        valuation: PortfolioValuation,
        *,
        cash_events: tuple[CashEvent, ...] | list[CashEvent] = (),
    ) -> "BenchmarkPerformanceHistory":
        """Return a replacement history with one benchmark valuation event."""
        if not isinstance(benchmark, BenchmarkPortfolio):
            raise TypeError("benchmark must be a BenchmarkPortfolio")
        if not isinstance(valuation, PortfolioValuation):
            raise TypeError("valuation must be a PortfolioValuation")
        if (
            benchmark.portfolio.portfolio_id != self.benchmark_portfolio_id
            or benchmark.benchmark_security != self.benchmark_security
        ):
            raise ValueError("benchmark must match history identity and security")
        baseline_value = self.snapshots[0].portfolio_value if self.snapshots else valuation.total_value
        prior_contributions = (
            self.snapshots[-1].cumulative_external_contributions if self.snapshots else Decimal("0")
        )
        normalized_cash_events = _normalize_cash_events(
            cash_events,
            portfolio=benchmark.portfolio,
            timestamp=valuation.as_of_timestamp,
        )
        cumulative_contributions = _calculate_decimal(
            lambda: prior_contributions + sum((cash_event.amount for cash_event in normalized_cash_events), Decimal("0"))
        )
        snapshot = PerformanceSnapshot(
            benchmark.portfolio,
            valuation,
            baseline_value,
            cumulative_contributions,
            normalized_cash_events,
        )
        return BenchmarkPerformanceHistory(
            self.benchmark_portfolio_id,
            self.benchmark_security,
            self.currency,
            (*self.snapshots, snapshot),
        )


@dataclass(frozen=True, slots=True)
class PerformanceComparison:
    """Deterministic cumulative managed-versus-benchmark valuation comparison."""

    managed_history: PortfolioPerformanceHistory
    benchmark_history: BenchmarkPerformanceHistory

    def __post_init__(self) -> None:
        if not isinstance(self.managed_history, PortfolioPerformanceHistory):
            raise TypeError("managed_history must be a PortfolioPerformanceHistory")
        if not isinstance(self.benchmark_history, BenchmarkPerformanceHistory):
            raise TypeError("benchmark_history must be a BenchmarkPerformanceHistory")
        if not self.managed_history.snapshots or not self.benchmark_history.snapshots:
            raise ValueError("performance comparison requires non-empty histories")
        if self.managed_history.currency != self.benchmark_history.currency:
            raise ValueError("managed and benchmark histories must share currency")
        if self.managed_history.portfolio_id == self.benchmark_history.benchmark_portfolio_id:
            raise ValueError("managed and benchmark histories must have distinct portfolio identities")
        if (
            self.managed_history.snapshots[0].portfolio.starting_capital
            != self.benchmark_history.snapshots[0].portfolio.starting_capital
        ):
            raise ValueError("managed and benchmark histories must share starting_capital")
        if len(self.managed_history.snapshots) != len(self.benchmark_history.snapshots):
            raise ValueError("managed and benchmark histories must have equal snapshot counts")
        for managed_snapshot, benchmark_snapshot in zip(self.managed_history.snapshots, self.benchmark_history.snapshots, strict=True):
            for field_name in (
                "as_of_timestamp",
                "currency",
                "source_provider_identity",
                "market_date",
                "source_price_timestamp",
                "price_convention",
            ):
                if getattr(managed_snapshot.valuation, field_name) != getattr(benchmark_snapshot.valuation, field_name):
                    raise ValueError(f"managed and benchmark snapshots must share valuation {field_name}")
            if managed_snapshot.cash_events != benchmark_snapshot.cash_events:
                raise ValueError("managed and benchmark snapshots must share the same CashEvent schedule")

    @property
    def managed_cumulative_return(self) -> Decimal:
        return self.managed_history.snapshots[-1].total_return

    @property
    def benchmark_cumulative_return(self) -> Decimal:
        return self.benchmark_history.snapshots[-1].total_return

    @property
    def absolute_alpha(self) -> Decimal:
        return _calculate_decimal(lambda: self.managed_cumulative_return - self.benchmark_cumulative_return)

    @property
    def relative_alpha(self) -> Decimal:
        benchmark_growth = _calculate_informational_decimal(lambda: Decimal("1") + self.benchmark_cumulative_return)
        if benchmark_growth.is_zero():
            raise ValueError("relative alpha is undefined when benchmark cumulative value is zero")
        return _calculate_informational_decimal(
            lambda: ((Decimal("1") + self.managed_cumulative_return) / benchmark_growth) - Decimal("1")
        )
