"""Atomic, persistence-neutral application service for refreshing market prices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence

from agentic_portfolio_lab.domain.market_prices import MarketPriceProvider
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.valuation import PriceObservation


class PriceRefreshState(Protocol):
    """One atomic state transition; Lane A can implement this with persistence."""

    def apply_price_refresh(self, observations: tuple[PriceObservation, ...]) -> None: ...


@dataclass(frozen=True, slots=True)
class PriceRefreshResult:
    observations: tuple[PriceObservation, ...]

    @property
    def provider_identity(self) -> str:
        return self.observations[0].source_provider_identity

    @property
    def latest_source_timestamp(self) -> datetime:
        return max(observation.observed_at for observation in self.observations)


class RefreshPricesService:
    """Select required securities, fetch all prices, then make one state update."""

    def __init__(
        self,
        *,
        provider: MarketPriceProvider,
        state: PriceRefreshState,
        candidate_universe: Sequence[SecurityIdentity],
        spy_benchmark: SecurityIdentity,
    ) -> None:
        self._provider = provider
        self._state = state
        self._candidate_universe = tuple(candidate_universe)
        self._spy_benchmark = spy_benchmark

    def refresh(self, held_securities: Sequence[SecurityIdentity]) -> PriceRefreshResult:
        required = self.required_securities(held_securities)
        observations = tuple(self._provider.get_observation(security) for security in required)
        # Fetching completes before the single state mutation, so a provider
        # failure cannot leave a partly refreshed application state.
        self._state.apply_price_refresh(observations)
        return PriceRefreshResult(observations=observations)

    def required_securities(self, held_securities: Sequence[SecurityIdentity]) -> tuple[SecurityIdentity, ...]:
        selected: list[SecurityIdentity] = []
        for security in (*held_securities, *self._candidate_universe, self._spy_benchmark):
            if security not in selected:
                selected.append(security)
        return tuple(selected)


class InMemoryPriceRefreshState:
    """Test/local state adapter; deliberately replaceable by Lane A's store."""

    def __init__(self) -> None:
        self.latest_observations: tuple[PriceObservation, ...] = ()

    def apply_price_refresh(self, observations: tuple[PriceObservation, ...]) -> None:
        if not observations:
            raise ValueError("a refresh must contain at least one observation")
        if len({observation.security for observation in observations}) != len(observations):
            raise ValueError("a refresh must not contain duplicate securities")
        self.latest_observations = observations
