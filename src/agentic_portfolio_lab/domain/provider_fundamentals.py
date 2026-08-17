"""Append-only normalized provider fundamental records.

These records are the durable source of truth for per-endpoint facts. Raw
vendor JSON is not persisted as authoritative state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from .portfolio import (
    SecurityIdentity,
    _require_aware_datetime,
    _require_date,
    _require_non_empty_text,
)

_MISSING_FACT_VALUES = frozenset({"n/a", "na", "none"})


class ReuseStatus(StrEnum):
    FETCHED_THIS_CYCLE = "FETCHED_THIS_CYCLE"
    REUSED_CURRENT = "REUSED_CURRENT"
    STALE = "STALE"
    MISSING = "MISSING"


class FreshnessClass(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ReliabilityClass(StrEnum):
    PRIMARY_STATEMENT = "PRIMARY_STATEMENT"
    MARKET_OBSERVATION = "MARKET_OBSERVATION"
    PROVIDER_COMPUTED = "PROVIDER_COMPUTED"
    DERIVED_DETERMINISTIC = "DERIVED_DETERMINISTIC"


class ProviderEndpoint(StrEnum):
    OVERVIEW = "OVERVIEW"
    INCOME_STATEMENT = "INCOME_STATEMENT"
    BALANCE_SHEET = "BALANCE_SHEET"
    CASH_FLOW = "CASH_FLOW"
    EARNINGS = "EARNINGS"


def _normalize_facts(value: tuple[tuple[str, str], ...] | list[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError("facts must be a tuple or list of (key, value) pairs")
    facts = tuple((key, fact_value) for key, fact_value in value)
    keys: list[str] = []
    normalized: list[tuple[str, str]] = []
    for key, fact_value in facts:
        if not isinstance(key, str) or not isinstance(fact_value, str):
            raise TypeError("facts must contain string keys and values")
        normalized_key = _require_non_empty_text(key, field_name="facts key").strip()
        normalized_value = _require_non_empty_text(fact_value, field_name="facts value").strip()
        if normalized_value.casefold() in _MISSING_FACT_VALUES:
            raise ValueError("facts must omit missing N/A-like values")
        keys.append(normalized_key)
        normalized.append((normalized_key, normalized_value))
    if len(set(keys)) != len(keys):
        raise ValueError("facts keys must be unique")
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class ProviderFundamentalRecord:
    """One append-only normalized per-endpoint fundamental fact record."""

    record_id: str
    security: SecurityIdentity
    provider_identity: str
    endpoint: ProviderEndpoint
    fiscal_period: date | None
    source_date: date
    fetched_at: datetime
    facts: tuple[tuple[str, str], ...] | list[tuple[str, str]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_id", _require_non_empty_text(self.record_id, field_name="record_id").strip())
        if not isinstance(self.security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        object.__setattr__(
            self,
            "provider_identity",
            _require_non_empty_text(self.provider_identity, field_name="provider_identity").strip(),
        )
        if not isinstance(self.endpoint, ProviderEndpoint):
            raise TypeError("endpoint must be a ProviderEndpoint")
        if self.fiscal_period is not None:
            _require_date(self.fiscal_period, field_name="fiscal_period")
        _require_date(self.source_date, field_name="source_date")
        fetched_at = _require_aware_datetime(self.fetched_at, field_name="fetched_at")
        if self.source_date > fetched_at.date():
            raise ValueError("source_date must not be after fetched_at")
        object.__setattr__(self, "facts", _normalize_facts(self.facts))
