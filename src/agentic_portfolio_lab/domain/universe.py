"""Versioned candidate-universe snapshots for managed research screening.

This is a configuration snapshot type. It does not choose the live ticker list.
"""

from __future__ import annotations

from dataclasses import dataclass

from .portfolio import SecurityIdentity, _require_non_empty_text

_SPY_TICKER = "SPY"
_EQUITY = "EQUITY"
_ETF = "ETF"
_USD = "USD"


def require_managed_universe_identities(
    identities: tuple[SecurityIdentity, ...] | list[SecurityIdentity],
    *,
    field_name: str = "identities",
) -> tuple[SecurityIdentity, ...]:
    """Return a unique EQUITY/USD identity snapshot; reject SPY and ETFs."""
    if not isinstance(identities, (tuple, list)):
        raise TypeError(f"{field_name} must be a tuple or list of SecurityIdentity instances")
    snapshot = tuple(identities)
    if not snapshot:
        raise ValueError(f"{field_name} must not be empty")
    if not all(isinstance(identity, SecurityIdentity) for identity in snapshot):
        raise TypeError(f"{field_name} must contain SecurityIdentity instances")
    for identity in snapshot:
        if identity.security_type == _ETF or identity.ticker == _SPY_TICKER:
            raise ValueError(f"{field_name} must not include SPY or ETF securities")
        if identity.security_type != _EQUITY:
            raise ValueError(f"{field_name} must contain EQUITY securities")
        if identity.currency != _USD:
            raise ValueError(f"{field_name} must contain USD securities")
    if len(set(snapshot)) != len(snapshot):
        raise ValueError(f"{field_name} must not contain duplicate or ambiguous security identities")
    tickers = tuple(identity.ticker for identity in snapshot)
    if len(set(tickers)) != len(tickers):
        raise ValueError(f"{field_name} must not contain duplicate or ambiguous security identities")
    return snapshot


@dataclass(frozen=True, slots=True)
class CandidateUniverse:
    """A versioned managed-research universe snapshot."""

    universe_version: str
    identities: tuple[SecurityIdentity, ...] | list[SecurityIdentity]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "universe_version",
            _require_non_empty_text(self.universe_version, field_name="universe_version").strip(),
        )
        object.__setattr__(self, "identities", require_managed_universe_identities(self.identities))
