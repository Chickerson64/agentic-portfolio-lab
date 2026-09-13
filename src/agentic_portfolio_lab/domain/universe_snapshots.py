"""Provider-neutral, immutable security-universe snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from .portfolio import SecurityIdentity, _require_non_empty_text


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{field_name} must be UTC")
    return value


@dataclass(frozen=True, slots=True)
class UniverseEligibilityRules:
    """Repository-owned rules over normalized, mixed listed-equity records."""

    allowed_exchanges: tuple[str, ...] = ("NASDAQ", "NYSE", "NYSE ARCA", "BATS", "AMEX")
    require_tradable: bool = True
    require_fractionable: bool = False
    max_symbol_length: int = 12

    def __post_init__(self) -> None:
        exchanges = tuple(self.allowed_exchanges)
        if not exchanges or not all(isinstance(value, str) and value.strip() for value in exchanges):
            raise ValueError("allowed_exchanges must contain non-empty text")
        if not all(isinstance(value, bool) for value in (self.require_tradable, self.require_fractionable)):
            raise TypeError("eligibility flags must be bool")
        if not isinstance(self.max_symbol_length, int) or isinstance(self.max_symbol_length, bool) or self.max_symbol_length <= 0:
            raise ValueError("max_symbol_length must be positive")
        object.__setattr__(self, "allowed_exchanges", tuple(value.strip().upper() for value in exchanges))


@dataclass(frozen=True, slots=True)
class EligibilityOutcome:
    symbol: str
    included: bool
    reason: str
    identity: SecurityIdentity | None

    def __post_init__(self) -> None:
        symbol = _require_non_empty_text(self.symbol, field_name="symbol").strip().upper()
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "reason", _require_non_empty_text(self.reason, field_name="reason").strip())
        if not isinstance(self.included, bool):
            raise TypeError("included must be a bool")
        if self.included != (self.identity is not None):
            raise ValueError("included must agree with identity")
        if self.identity is not None and self.identity.ticker != symbol:
            raise ValueError("identity ticker must agree with symbol")


@dataclass(frozen=True, slots=True)
class UniverseSnapshot:
    snapshot_id: str
    provider_identity: str
    retrieved_at: datetime
    as_of: datetime
    rules: UniverseEligibilityRules
    outcomes: tuple[EligibilityOutcome, ...]
    provenance: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", _require_non_empty_text(self.snapshot_id, field_name="snapshot_id").strip())
        object.__setattr__(self, "provider_identity", _require_non_empty_text(self.provider_identity, field_name="provider_identity").strip())
        _require_utc(self.retrieved_at, field_name="retrieved_at")
        _require_utc(self.as_of, field_name="as_of")
        if self.as_of > self.retrieved_at:
            raise ValueError("as_of must not be after retrieved_at")
        if not isinstance(self.rules, UniverseEligibilityRules):
            raise TypeError("rules must be UniverseEligibilityRules")
        if not isinstance(self.outcomes, tuple) or not all(isinstance(item, EligibilityOutcome) for item in self.outcomes):
            raise TypeError("outcomes must be a tuple of EligibilityOutcome")
        if len({item.symbol for item in self.outcomes}) != len(self.outcomes):
            raise ValueError("outcomes must not contain duplicate symbols")
        if not isinstance(self.provenance, tuple) or not all(isinstance(item, tuple) and len(item) == 2 and all(isinstance(value, str) and value for value in item) for item in self.provenance):
            raise TypeError("provenance must contain non-empty string pairs")

    @property
    def eligible_universe(self) -> tuple[SecurityIdentity, ...]:
        return tuple(item.identity for item in self.outcomes if item.identity is not None)

    def to_json(self) -> str:
        return json.dumps({"snapshot_id": self.snapshot_id, "provider_identity": self.provider_identity, "retrieved_at": self.retrieved_at.isoformat(), "as_of": self.as_of.isoformat(), "rules": {"allowed_exchanges": list(self.rules.allowed_exchanges), "require_tradable": self.rules.require_tradable, "require_fractionable": self.rules.require_fractionable, "max_symbol_length": self.rules.max_symbol_length}, "outcomes": [{"symbol": item.symbol, "included": item.included, "reason": item.reason, "identity": None if item.identity is None else {"ticker": item.identity.ticker, "security_type": item.identity.security_type, "exchange": item.identity.exchange, "currency": item.identity.currency}} for item in self.outcomes], "provenance": [list(item) for item in self.provenance]}, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> "UniverseSnapshot":
        try:
            raw = json.loads(value)
            rules = UniverseEligibilityRules(**raw["rules"])
            outcomes = tuple(EligibilityOutcome(item["symbol"], item["included"], item["reason"], None if item["identity"] is None else SecurityIdentity(**item["identity"])) for item in raw["outcomes"])
            return cls(raw["snapshot_id"], raw["provider_identity"], datetime.fromisoformat(raw["retrieved_at"]), datetime.fromisoformat(raw["as_of"]), rules, outcomes, tuple(tuple(item) for item in raw["provenance"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("universe snapshot document is malformed") from error
