"""Provider-neutral market price boundary."""

from __future__ import annotations

from typing import Protocol

from .portfolio import SecurityIdentity
from .valuation import PriceObservation


class MarketPriceError(RuntimeError):
    """A required attributable market price could not be obtained."""


class MarketPriceConfigurationError(MarketPriceError):
    """The selected market-price provider is not configured."""


class MarketPriceProvider(Protocol):
    """Fetch one source-attributed observation for one known security."""

    def get_observation(self, security: SecurityIdentity) -> PriceObservation: ...
