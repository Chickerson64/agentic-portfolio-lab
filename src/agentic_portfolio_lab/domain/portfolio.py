"""Deterministic portfolio domain models.

These models intentionally avoid framework dependencies and keep all authoritative
financial values in ``Decimal`` form.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Context, Decimal, MAX_EMAX, MAX_PREC, MIN_EMIN, ROUND_HALF_EVEN, localcontext
from datetime import date, datetime
from typing import Callable, Final
from uuid import UUID, uuid4

QUANTITY_PLACES: Final = Decimal("0.00000001")

# Domain calculations use the full precision and exponent range supported by
# Python's Decimal implementation, independent of caller-controlled context.
_DOMAIN_DECIMAL_CONTEXT: Final = Context(prec=MAX_PREC, Emax=MAX_EMAX, Emin=MIN_EMIN)

# Average cost is informational only. Authoritative cost basis is total cost.
_INFORMATIONAL_DECIMAL_CONTEXT: Final = Context(prec=28, rounding=ROUND_HALF_EVEN)


def _calculate_decimal(operation: Callable[[], Decimal]) -> Decimal:
    with localcontext(_DOMAIN_DECIMAL_CONTEXT):
        return operation()


def _calculate_informational_decimal(operation: Callable[[], Decimal]) -> Decimal:
    with localcontext(_INFORMATIONAL_DECIMAL_CONTEXT):
        return operation()


def _require_finite_decimal(value: Decimal, *, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


def _require_non_negative_decimal(value: Decimal, *, field_name: str) -> Decimal:
    value = _require_finite_decimal(value, field_name=field_name)
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return Decimal("0") if value.is_zero() else value


def _require_positive_decimal(value: Decimal, *, field_name: str) -> Decimal:
    value = _require_finite_decimal(value, field_name=field_name)
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return value


def _require_max_decimal_places(value: Decimal, places: Decimal, *, field_name: str) -> Decimal:
    value = _require_finite_decimal(value, field_name=field_name)
    maximum_places = abs(places.as_tuple().exponent)
    actual_places = max(0, -value.as_tuple().exponent)
    if actual_places > maximum_places:
        raise ValueError(f"{field_name} must have at most {maximum_places} decimal places")
    return value


def _require_non_empty_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _canonical_upper_text(value: str, *, field_name: str) -> str:
    return _require_non_empty_text(value, field_name=field_name).strip().upper()


def _require_aware_datetime(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _require_date(value: date, *, field_name: str) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{field_name} must be a date, not a datetime")
    return value


@dataclass(frozen=True, slots=True)
class SecurityIdentity:
    ticker: str
    security_type: str
    exchange: str
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", _canonical_upper_text(self.ticker, field_name="ticker"))
        object.__setattr__(self, "security_type", _canonical_upper_text(self.security_type, field_name="security_type"))
        object.__setattr__(self, "exchange", _canonical_upper_text(self.exchange, field_name="exchange"))
        object.__setattr__(self, "currency", _canonical_upper_text(self.currency, field_name="currency"))


@dataclass(frozen=True, slots=True)
class CashBalance:
    currency: str
    amount: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", _canonical_upper_text(self.currency, field_name="currency"))
        object.__setattr__(self, "amount", _require_non_negative_decimal(self.amount, field_name="amount"))


@dataclass(frozen=True, slots=True)
class Position:
    security: SecurityIdentity
    quantity: Decimal
    total_cost_basis: Decimal
    market_price: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        quantity = _require_non_negative_decimal(self.quantity, field_name="quantity")
        quantity = _require_max_decimal_places(quantity, QUANTITY_PLACES, field_name="quantity")
        total_cost_basis = _require_non_negative_decimal(self.total_cost_basis, field_name="total_cost_basis")
        if quantity.is_zero() and not total_cost_basis.is_zero():
            raise ValueError("total_cost_basis must be zero when quantity is zero")
        market_price = _require_non_negative_decimal(self.market_price, field_name="market_price")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "total_cost_basis", total_cost_basis)
        object.__setattr__(self, "market_price", market_price)

    @property
    def market_value(self) -> Decimal:
        return _calculate_decimal(lambda: self.quantity * self.market_price)

    @property
    def average_cost_basis(self) -> Decimal:
        """Informational per-share average derived from authoritative total cost."""
        if self.quantity.is_zero():
            return Decimal("0")
        return _calculate_informational_decimal(lambda: self.total_cost_basis / self.quantity)

    @property
    def unrealized_pnl(self) -> Decimal:
        return _calculate_decimal(lambda: self.market_value - self.total_cost_basis)


@dataclass(frozen=True, slots=True)
class Contribution:
    amount: Decimal
    currency: str
    effective_at: datetime
    received_at: datetime
    source: str
    is_one_time_event: bool = True
    contribution_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _require_positive_decimal(self.amount, field_name="amount"))
        object.__setattr__(self, "currency", _canonical_upper_text(self.currency, field_name="currency"))
        _require_aware_datetime(self.effective_at, field_name="effective_at")
        _require_aware_datetime(self.received_at, field_name="received_at")
        object.__setattr__(self, "source", _require_non_empty_text(self.source, field_name="source"))
        if not self.is_one_time_event:
            raise ValueError("is_one_time_event must be True for the MVP")


@dataclass(frozen=True, slots=True)
class PortfolioValuationSnapshot:
    portfolio_id: UUID
    as_of_timestamp: datetime
    cash_balance: Decimal
    positions_market_value: Decimal
    total_value: Decimal
    source_provider_identity: str
    market_date: date
    source_price_timestamp: datetime
    currency: str
    price_convention: str

    def __post_init__(self) -> None:
        _require_aware_datetime(self.as_of_timestamp, field_name="as_of_timestamp")
        _require_date(self.market_date, field_name="market_date")
        _require_aware_datetime(self.source_price_timestamp, field_name="source_price_timestamp")
        object.__setattr__(self, "source_provider_identity", _require_non_empty_text(self.source_provider_identity, field_name="source_provider_identity"))
        object.__setattr__(self, "currency", _canonical_upper_text(self.currency, field_name="currency"))
        object.__setattr__(self, "price_convention", _require_non_empty_text(self.price_convention, field_name="price_convention"))
        cash_balance = _require_non_negative_decimal(self.cash_balance, field_name="cash_balance")
        positions_market_value = _require_non_negative_decimal(self.positions_market_value, field_name="positions_market_value")
        total_value = _require_non_negative_decimal(self.total_value, field_name="total_value")
        expected_total = _calculate_decimal(lambda: cash_balance + positions_market_value)
        if total_value != expected_total:
            raise ValueError("total_value must equal cash_balance plus positions_market_value")
        object.__setattr__(self, "cash_balance", cash_balance)
        object.__setattr__(self, "positions_market_value", positions_market_value)
        object.__setattr__(self, "total_value", total_value)

    @classmethod
    def from_components(
        cls,
        *,
        portfolio_id: UUID,
        as_of_timestamp: datetime,
        cash_balance: CashBalance,
        positions: tuple[Position, ...],
        source_provider_identity: str,
        market_date: date,
        source_price_timestamp: datetime,
        price_convention: str,
    ) -> "PortfolioValuationSnapshot":
        if not isinstance(cash_balance, CashBalance):
            raise TypeError("cash_balance must be a CashBalance")
        normalized_positions = tuple(positions)
        for position in normalized_positions:
            if not isinstance(position, Position):
                raise TypeError("positions must contain Position instances")
            if position.security.currency != cash_balance.currency:
                raise ValueError("position currency must match cash balance currency")
        positions_market_value = _calculate_decimal(
            lambda: sum((position.market_value for position in normalized_positions), Decimal("0"))
        )
        total_value = _calculate_decimal(lambda: cash_balance.amount + positions_market_value)
        return cls(
            portfolio_id=portfolio_id,
            as_of_timestamp=as_of_timestamp,
            cash_balance=cash_balance.amount,
            positions_market_value=positions_market_value,
            total_value=total_value,
            source_provider_identity=source_provider_identity,
            market_date=market_date,
            source_price_timestamp=source_price_timestamp,
            currency=cash_balance.currency,
            price_convention=price_convention,
        )


@dataclass(frozen=True, slots=True)
class Portfolio:
    portfolio_id: UUID
    portfolio_name: str
    base_currency: str
    starting_capital: Decimal
    cash_balance: CashBalance
    created_at: datetime
    positions: tuple[Position, ...] = field(default_factory=tuple)
    status: str = "active"
    decision_cycle_id: UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "portfolio_name", _require_non_empty_text(self.portfolio_name, field_name="portfolio_name"))
        object.__setattr__(self, "base_currency", _canonical_upper_text(self.base_currency, field_name="base_currency"))
        object.__setattr__(self, "starting_capital", _require_non_negative_decimal(self.starting_capital, field_name="starting_capital"))
        if not isinstance(self.cash_balance, CashBalance):
            raise TypeError("cash_balance must be a CashBalance")
        if self.cash_balance.currency != self.base_currency:
            raise ValueError("cash_balance currency must match base_currency")
        normalized_positions = tuple(self.positions)
        seen_securities: set[SecurityIdentity] = set()
        for position in normalized_positions:
            if not isinstance(position, Position):
                raise TypeError("positions must contain Position instances")
            if position.security.currency != self.base_currency:
                raise ValueError("position currency must match portfolio base_currency")
            if position.security in seen_securities:
                raise ValueError("positions must not contain duplicate securities")
            seen_securities.add(position.security)
        object.__setattr__(self, "positions", normalized_positions)
        _require_aware_datetime(self.created_at, field_name="created_at")
        object.__setattr__(self, "status", _require_non_empty_text(self.status, field_name="status"))

    @property
    def current_market_value(self) -> Decimal:
        return _calculate_decimal(lambda: sum((position.market_value for position in self.positions), Decimal("0")))

    @property
    def current_total_value(self) -> Decimal:
        return _calculate_decimal(lambda: self.cash_balance.amount + self.current_market_value)
