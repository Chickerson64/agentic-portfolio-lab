"""Provider-neutral daily market-data boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Mapping, Protocol, Sequence, runtime_checkable

from .portfolio import SecurityIdentity, _require_aware_datetime, _require_date, _require_non_empty_text, _require_positive_decimal


class MarketDataError(RuntimeError):
    """A provider could not supply valid market data."""


class MarketDataConfigurationError(MarketDataError):
    """A market-data provider has not been configured."""


@dataclass(frozen=True, slots=True)
class DailyBar:
    security: SecurityIdentity
    market_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source_provider_identity: str

    def __post_init__(self) -> None:
        if not isinstance(self.security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        _require_date(self.market_date, field_name="market_date")
        for field in ("open", "high", "low", "close"):
            object.__setattr__(self, field, _require_positive_decimal(getattr(self, field), field_name=field))
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("bar high/low must contain open and close")
        if not isinstance(self.volume, int) or isinstance(self.volume, bool) or self.volume < 0:
            raise ValueError("volume must be a non-negative integer")
        object.__setattr__(self, "source_provider_identity", _require_non_empty_text(self.source_provider_identity, field_name="source_provider_identity").strip())


@dataclass(frozen=True, slots=True)
class CurrentQuote:
    security: SecurityIdentity
    bid: Decimal | None
    ask: Decimal | None
    quote_at: datetime
    source_provider_identity: str

    def __post_init__(self) -> None:
        if not isinstance(self.security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        for field in ("bid", "ask"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _require_positive_decimal(value, field_name=field))
        if self.bid is None and self.ask is None:
            raise ValueError("bid or ask must be provided")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise ValueError("bid must not exceed ask")
        _require_aware_datetime(self.quote_at, field_name="quote_at")
        object.__setattr__(self, "source_provider_identity", _require_non_empty_text(self.source_provider_identity, field_name="source_provider_identity").strip())


class MarketDataProvider(Protocol):
    def get_daily_bars(self, security: SecurityIdentity, *, start: date, end: date) -> Sequence[DailyBar]: ...

    def get_current_quote(self, security: SecurityIdentity) -> CurrentQuote: ...


@runtime_checkable
class BatchDailyBarsProvider(Protocol):
    """Optional capability for one historical daily-bars request over many symbols.

    The mapping must contain every requested ticker; an empty sequence records
    an explicit provider history miss without making it indistinguishable from
    a provider that omitted a requested symbol.
    """

    def get_daily_bars_batch(
        self, securities: Sequence[SecurityIdentity], *, start: date, end: date
    ) -> Mapping[str, Sequence[DailyBar]]: ...
