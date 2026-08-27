"""Deterministic, supplied-price valuation and benchmark primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable
from uuid import UUID, uuid4

from .portfolio import (
    QUANTITY_PLACES,
    CashBalance,
    Contribution,
    Portfolio,
    Position,
    SecurityIdentity,
    _calculate_decimal,
    _calculate_informational_decimal,
    _canonical_upper_text,
    _require_aware_datetime,
    _require_date,
    _require_max_decimal_places,
    _require_non_empty_text,
    _require_non_negative_decimal,
    _require_positive_decimal,
)


def _canonical_metadata_text(value: str, *, field_name: str) -> str:
    """Normalize presentation-only metadata without assuming provider semantics."""
    return _require_non_empty_text(value, field_name=field_name).strip()


@dataclass(frozen=True, slots=True)
class PriceObservation:
    """One supplied market price; this model never fetches or infers prices."""

    security: SecurityIdentity
    observed_price: Decimal
    market_date: date
    observed_at: datetime
    currency: str
    source_provider_identity: str
    price_convention: str

    def __post_init__(self) -> None:
        if not isinstance(self.security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        observed_price = _require_positive_decimal(self.observed_price, field_name="observed_price")
        _require_date(self.market_date, field_name="market_date")
        _require_aware_datetime(self.observed_at, field_name="observed_at")
        currency = _canonical_upper_text(self.currency, field_name="currency")
        if currency != self.security.currency:
            raise ValueError("currency must match security currency")
        object.__setattr__(self, "observed_price", observed_price)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(
            self,
            "source_provider_identity",
            _canonical_metadata_text(self.source_provider_identity, field_name="source_provider_identity"),
        )
        object.__setattr__(
            self,
            "price_convention",
            _canonical_metadata_text(self.price_convention, field_name="price_convention"),
        )


@dataclass(frozen=True, slots=True)
class PositionValuation:
    """Supplied-price valuation of one current long-only position."""

    security: SecurityIdentity
    quantity: Decimal
    observed_price: Decimal
    total_cost_basis: Decimal
    market_value: Decimal
    unrealized_gain_loss: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        quantity = _require_non_negative_decimal(self.quantity, field_name="quantity")
        quantity = _require_max_decimal_places(quantity, QUANTITY_PLACES, field_name="quantity")
        observed_price = _require_positive_decimal(self.observed_price, field_name="observed_price")
        total_cost_basis = _require_non_negative_decimal(self.total_cost_basis, field_name="total_cost_basis")
        market_value = _require_non_negative_decimal(self.market_value, field_name="market_value")
        if quantity.is_zero() and not total_cost_basis.is_zero():
            raise ValueError("total_cost_basis must be zero when quantity is zero")
        expected_market_value = _calculate_decimal(lambda: quantity * observed_price)
        if market_value != expected_market_value:
            raise ValueError("market_value must equal quantity multiplied by observed_price")
        expected_gain_loss = _calculate_decimal(lambda: market_value - total_cost_basis)
        if self.unrealized_gain_loss != expected_gain_loss:
            raise ValueError("unrealized_gain_loss must equal market_value minus total_cost_basis")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "observed_price", observed_price)
        object.__setattr__(self, "total_cost_basis", total_cost_basis)
        object.__setattr__(self, "market_value", market_value)

    @classmethod
    def from_position(cls, position: Position, observation: PriceObservation) -> "PositionValuation":
        if not isinstance(position, Position):
            raise TypeError("position must be a Position")
        if not isinstance(observation, PriceObservation):
            raise TypeError("observation must be a PriceObservation")
        if observation.security != position.security:
            raise ValueError("observation security must match position security")
        market_value = _calculate_decimal(lambda: position.quantity * observation.observed_price)
        return cls(
            security=position.security,
            quantity=position.quantity,
            observed_price=observation.observed_price,
            total_cost_basis=position.total_cost_basis,
            market_value=market_value,
            unrealized_gain_loss=_calculate_decimal(lambda: market_value - position.total_cost_basis),
        )


@dataclass(frozen=True, slots=True)
class PortfolioValuation:
    """An immutable point-in-time valuation based exclusively on supplied prices."""

    subject_id: UUID
    as_of_timestamp: datetime
    cash_value: Decimal
    invested_value: Decimal
    total_value: Decimal
    unrealized_gain_loss: Decimal
    position_valuations: tuple[PositionValuation, ...]
    source_provider_identity: str
    market_date: date
    source_price_timestamp: datetime
    currency: str
    price_convention: str

    def __post_init__(self) -> None:
        _require_aware_datetime(self.as_of_timestamp, field_name="as_of_timestamp")
        _require_date(self.market_date, field_name="market_date")
        _require_aware_datetime(self.source_price_timestamp, field_name="source_price_timestamp")
        if self.source_price_timestamp > self.as_of_timestamp:
            raise ValueError("source_price_timestamp must not be after as_of_timestamp")
        if self.market_date > self.as_of_timestamp.date():
            raise ValueError("market_date must not be after as_of_timestamp date")
        cash_value = _require_non_negative_decimal(self.cash_value, field_name="cash_value")
        invested_value = _require_non_negative_decimal(self.invested_value, field_name="invested_value")
        total_value = _require_non_negative_decimal(self.total_value, field_name="total_value")
        currency = _canonical_upper_text(self.currency, field_name="currency")
        normalized_positions = tuple(self.position_valuations)
        seen_securities: set[SecurityIdentity] = set()
        for valuation in normalized_positions:
            if not isinstance(valuation, PositionValuation):
                raise TypeError("position_valuations must contain PositionValuation instances")
            if valuation.security.currency != currency:
                raise ValueError("position valuation currency must match valuation currency")
            if valuation.security in seen_securities:
                raise ValueError("position_valuations must not contain duplicate securities")
            seen_securities.add(valuation.security)
        expected_invested_value = _calculate_decimal(
            lambda: sum((valuation.market_value for valuation in normalized_positions), Decimal("0"))
        )
        if invested_value != expected_invested_value:
            raise ValueError("invested_value must equal the sum of position market values")
        expected_total_value = _calculate_decimal(lambda: cash_value + invested_value)
        if total_value != expected_total_value:
            raise ValueError("total_value must equal cash_value plus invested_value")
        expected_gain_loss = _calculate_decimal(
            lambda: sum((valuation.unrealized_gain_loss for valuation in normalized_positions), Decimal("0"))
        )
        if self.unrealized_gain_loss != expected_gain_loss:
            raise ValueError("unrealized_gain_loss must equal the sum of position gain or loss")
        object.__setattr__(self, "cash_value", cash_value)
        object.__setattr__(self, "invested_value", invested_value)
        object.__setattr__(self, "total_value", total_value)
        object.__setattr__(self, "position_valuations", normalized_positions)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(
            self,
            "source_provider_identity",
            _canonical_metadata_text(self.source_provider_identity, field_name="source_provider_identity"),
        )
        object.__setattr__(
            self,
            "price_convention",
            _canonical_metadata_text(self.price_convention, field_name="price_convention"),
        )

    @property
    def position_weights(self) -> tuple[tuple[SecurityIdentity, Decimal], ...]:
        """Informational current weights derived from this immutable valuation."""
        if self.total_value.is_zero():
            return tuple((valuation.security, Decimal("0")) for valuation in self.position_valuations)
        return tuple(
            (
                valuation.security,
                _calculate_informational_decimal(lambda: valuation.market_value / self.total_value),
            )
            for valuation in self.position_valuations
        )

    @classmethod
    def from_portfolio(
        cls,
        portfolio: Portfolio,
        price_observations: Iterable[PriceObservation],
        *,
        as_of_timestamp: datetime,
        market_date: date,
        source_price_timestamp: datetime,
        source_provider_identity: str,
        price_convention: str,
    ) -> "PortfolioValuation":
        if not isinstance(portfolio, Portfolio):
            raise TypeError("portfolio must be a Portfolio")
        return cls._from_components(
            subject_id=portfolio.portfolio_id,
            cash_balance=portfolio.cash_balance,
            positions=portfolio.positions,
            price_observations=price_observations,
            as_of_timestamp=as_of_timestamp,
            market_date=market_date,
            source_price_timestamp=source_price_timestamp,
            source_provider_identity=source_provider_identity,
            price_convention=price_convention,
        )

    @classmethod
    def from_benchmark(
        cls,
        benchmark: "BenchmarkPortfolio",
        price_observations: Iterable[PriceObservation],
        *,
        as_of_timestamp: datetime,
        market_date: date,
        source_price_timestamp: datetime,
        source_provider_identity: str,
        price_convention: str,
    ) -> "PortfolioValuation":
        if not isinstance(benchmark, BenchmarkPortfolio):
            raise TypeError("benchmark must be a BenchmarkPortfolio")
        return cls._from_components(
            subject_id=benchmark.portfolio.portfolio_id,
            cash_balance=benchmark.portfolio.cash_balance,
            positions=benchmark.portfolio.positions,
            price_observations=price_observations,
            as_of_timestamp=as_of_timestamp,
            market_date=market_date,
            source_price_timestamp=source_price_timestamp,
            source_provider_identity=source_provider_identity,
            price_convention=price_convention,
        )

    @classmethod
    def from_portfolio_mark_to_market(
        cls,
        portfolio: Portfolio,
        price_observations: Iterable[PriceObservation],
        *,
        as_of_timestamp: datetime,
        market_date: date,
        source_price_timestamp: datetime,
        source_provider_identity: str,
        price_convention: str,
    ) -> "PortfolioValuation":
        """Value one portfolio from a coherent persisted refresh set.

        A paced provider may observe distinct securities at different moments.
        The supplied source timestamp is the refresh-set valuation boundary,
        and each position observation must not postdate it.
        """
        if not isinstance(portfolio, Portfolio):
            raise TypeError("portfolio must be a Portfolio")
        return cls._from_components(
            subject_id=portfolio.portfolio_id,
            cash_balance=portfolio.cash_balance,
            positions=portfolio.positions,
            price_observations=price_observations,
            as_of_timestamp=as_of_timestamp,
            market_date=market_date,
            source_price_timestamp=source_price_timestamp,
            source_provider_identity=source_provider_identity,
            price_convention=price_convention,
            allow_observations_before_source_timestamp=True,
        )

    @classmethod
    def from_benchmark_mark_to_market(
        cls,
        benchmark: "BenchmarkPortfolio",
        price_observations: Iterable[PriceObservation],
        **metadata,
    ) -> "PortfolioValuation":
        if not isinstance(benchmark, BenchmarkPortfolio):
            raise TypeError("benchmark must be a BenchmarkPortfolio")
        return cls._from_components(
            subject_id=benchmark.portfolio.portfolio_id,
            cash_balance=benchmark.portfolio.cash_balance,
            positions=benchmark.portfolio.positions,
            price_observations=price_observations,
            allow_observations_before_source_timestamp=True,
            **metadata,
        )

    @classmethod
    def _from_components(
        cls,
        *,
        subject_id: UUID,
        cash_balance: CashBalance,
        positions: tuple[Position, ...],
        price_observations: Iterable[PriceObservation],
        as_of_timestamp: datetime,
        market_date: date,
        source_price_timestamp: datetime,
        source_provider_identity: str,
        price_convention: str,
        allow_observations_before_source_timestamp: bool = False,
    ) -> "PortfolioValuation":
        if not isinstance(cash_balance, CashBalance):
            raise TypeError("cash_balance must be a CashBalance")
        observations_by_security: dict[SecurityIdentity, PriceObservation] = {}
        for observation in tuple(price_observations):
            if not isinstance(observation, PriceObservation):
                raise TypeError("price_observations must contain PriceObservation instances")
            if observation.security in observations_by_security:
                raise ValueError("price_observations must not contain duplicate securities")
            if observation.currency != cash_balance.currency:
                raise ValueError("observation currency must match cash balance currency")
            if observation.market_date != market_date:
                raise ValueError("observation market_date must match valuation market_date")
            if allow_observations_before_source_timestamp:
                if observation.observed_at > source_price_timestamp:
                    raise ValueError("observation timestamp must not postdate valuation source_price_timestamp")
            elif observation.observed_at != source_price_timestamp:
                raise ValueError("observation timestamp must match valuation source_price_timestamp")
            if observation.source_provider_identity != _canonical_metadata_text(
                source_provider_identity, field_name="source_provider_identity"
            ):
                raise ValueError("observation provider must match valuation provider")
            if observation.price_convention != _canonical_metadata_text(
                price_convention, field_name="price_convention"
            ):
                raise ValueError("observation price_convention must match valuation price_convention")
            observations_by_security[observation.security] = observation

        expected_securities = {position.security for position in positions}
        supplied_securities = set(observations_by_security)
        if supplied_securities != expected_securities:
            missing = expected_securities - supplied_securities
            if missing:
                raise ValueError("price_observations are missing prices for one or more positions")
            raise ValueError("price_observations contain securities not held by the portfolio")

        position_valuations = tuple(
            PositionValuation.from_position(position, observations_by_security[position.security])
            for position in positions
        )
        invested_value = _calculate_decimal(
            lambda: sum((valuation.market_value for valuation in position_valuations), Decimal("0"))
        )
        unrealized_gain_loss = _calculate_decimal(
            lambda: sum((valuation.unrealized_gain_loss for valuation in position_valuations), Decimal("0"))
        )
        return cls(
            subject_id=subject_id,
            as_of_timestamp=as_of_timestamp,
            cash_value=cash_balance.amount,
            invested_value=invested_value,
            total_value=_calculate_decimal(lambda: cash_balance.amount + invested_value),
            unrealized_gain_loss=unrealized_gain_loss,
            position_valuations=position_valuations,
            source_provider_identity=source_provider_identity,
            market_date=market_date,
            source_price_timestamp=source_price_timestamp,
            currency=cash_balance.currency,
            price_convention=price_convention,
        )


@dataclass(frozen=True, slots=True)
class BenchmarkPortfolio:
    """A SPY-constrained wrapper around the shared immutable Portfolio state."""

    portfolio: Portfolio
    benchmark_security: SecurityIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.portfolio, Portfolio):
            raise TypeError("portfolio must be a Portfolio")
        if not isinstance(self.benchmark_security, SecurityIdentity):
            raise TypeError("benchmark_security must be a SecurityIdentity")
        if self.benchmark_security.ticker != "SPY":
            raise ValueError("benchmark_security ticker must be SPY")
        if self.benchmark_security.currency != self.portfolio.base_currency:
            raise ValueError("benchmark security currency must match portfolio base_currency")
        for position in self.portfolio.positions:
            if position.security != self.benchmark_security:
                raise ValueError("benchmark portfolio may only hold its benchmark security")

    @classmethod
    def from_portfolio(cls, portfolio: Portfolio, spy_security: SecurityIdentity) -> "BenchmarkPortfolio":
        """Initialize a separate SPY portfolio with the managed portfolio's starting capital."""
        if not isinstance(portfolio, Portfolio):
            raise TypeError("portfolio must be a Portfolio")
        if not isinstance(spy_security, SecurityIdentity):
            raise TypeError("spy_security must be a SecurityIdentity")
        if spy_security.currency != portfolio.base_currency:
            raise ValueError("SPY currency must match portfolio base_currency")
        return cls(
            portfolio=Portfolio(
                portfolio_id=uuid4(),
                portfolio_name=f"{portfolio.portfolio_name} SPY Benchmark",
                base_currency=portfolio.base_currency,
                starting_capital=portfolio.starting_capital,
                cash_balance=CashBalance(currency=portfolio.base_currency, amount=portfolio.starting_capital),
                created_at=portfolio.created_at,
            ),
            benchmark_security=spy_security,
        )

    def receive_contribution(self, contribution: Contribution) -> "BenchmarkPortfolio":
        """Apply a Cash Event without deciding or executing any SPY purchase."""
        # Local import prevents an import cycle while preserving the shared accounting path.
        from .portfolio_service import PortfolioService

        return BenchmarkPortfolio(
            portfolio=PortfolioService.apply_contribution(self.portfolio, contribution),
            benchmark_security=self.benchmark_security,
        )


@dataclass(frozen=True, slots=True)
class PortfolioComparison:
    """A like-for-like managed portfolio and benchmark valuation comparison."""

    managed_valuation: PortfolioValuation
    benchmark_valuation: PortfolioValuation

    def __post_init__(self) -> None:
        if not isinstance(self.managed_valuation, PortfolioValuation):
            raise TypeError("managed_valuation must be a PortfolioValuation")
        if not isinstance(self.benchmark_valuation, PortfolioValuation):
            raise TypeError("benchmark_valuation must be a PortfolioValuation")
        for field_name in (
            "as_of_timestamp",
            "market_date",
            "source_price_timestamp",
            "source_provider_identity",
            "price_convention",
            "currency",
        ):
            if getattr(self.managed_valuation, field_name) != getattr(self.benchmark_valuation, field_name):
                raise ValueError(f"managed and benchmark valuations must share {field_name}")

    @property
    def managed_portfolio_value(self) -> Decimal:
        return self.managed_valuation.total_value

    @property
    def benchmark_value(self) -> Decimal:
        return self.benchmark_valuation.total_value

    @property
    def absolute_difference(self) -> Decimal:
        return _calculate_decimal(lambda: abs(self.managed_portfolio_value - self.benchmark_value))
