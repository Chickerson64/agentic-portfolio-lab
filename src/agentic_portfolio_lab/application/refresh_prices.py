"""Atomic, persistence-neutral application service for refreshing market prices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol, Sequence
from uuid import UUID, uuid4

from agentic_portfolio_lab.domain.market_prices import MarketPriceProvider
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.domain.price_refresh import PriceRefreshOperation, PriceRefreshOperationStatus


class PriceRefreshState(Protocol):
    def begin_price_refresh(self, operation: PriceRefreshOperation) -> None: ...
    def complete_price_refresh(self, operation_id: UUID, observations: tuple[PriceObservation, ...], completed_at: datetime) -> None: ...
    def fail_price_refresh(self, operation_id: UUID, *, completed_at: datetime, failure_code: str, failure_message: str) -> None: ...
    def recover_interrupted_price_refresh(self, operation_id: UUID, *, recovered_at: datetime) -> None: ...


class PriceRefreshConflict(ValueError):
    """A second operator request encountered the durable active operation."""


@dataclass(frozen=True, slots=True)
class PriceRefreshResult:
    observations: tuple[PriceObservation, ...]
    operation: PriceRefreshOperation

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
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._state = state
        self._candidate_universe = tuple(candidate_universe)
        self._spy_benchmark = spy_benchmark
        self._now = now or (lambda: datetime.now(timezone.utc))

    def refresh(self, held_securities: Sequence[SecurityIdentity]) -> PriceRefreshResult:
        required = self.required_securities(held_securities)
        identity = getattr(self._provider, "provider_identity", self._provider.__class__.__name__)
        operation = PriceRefreshOperation(uuid4(), PriceRefreshOperationStatus.IN_PROGRESS, self._now(), str(identity), len(required))
        self._state.begin_price_refresh(operation)
        try:
            observations = tuple(self._provider.get_observation(security) for security in required)
            completed_at = self._now()
            self._state.complete_price_refresh(operation.operation_id, observations, completed_at)
        except Exception as error:
            code = "market_price_configuration" if error.__class__.__name__ == "MarketPriceConfigurationError" else "market_price_unavailable" if error.__class__.__name__ == "MarketPriceError" else "refresh_unavailable"
            self._state.fail_price_refresh(operation.operation_id, completed_at=self._now(), failure_code=code, failure_message=str(error))
            raise
        completed = PriceRefreshOperation(operation.operation_id, PriceRefreshOperationStatus.COMPLETED, operation.started_at, operation.provider_identity, operation.expected_security_count, completed_at, len(observations), max(item.observed_at for item in observations))
        return PriceRefreshResult(observations=observations, operation=completed)

    def required_securities(self, held_securities: Sequence[SecurityIdentity]) -> tuple[SecurityIdentity, ...]:
        selected: list[SecurityIdentity] = []
        for security in (*held_securities, *self._candidate_universe, self._spy_benchmark):
            if security not in selected:
                selected.append(security)
        return tuple(selected)

    def recover_interrupted(self, operation_id: UUID) -> None:
        self._state.recover_interrupted_price_refresh(operation_id, recovered_at=self._now())


class InMemoryPriceRefreshState:
    """Test/local state adapter; deliberately replaceable by Lane A's store."""

    def __init__(self) -> None:
        self.latest_observations: tuple[PriceObservation, ...] = ()
        self.latest_operation: PriceRefreshOperation | None = None

    def apply_price_refresh(self, observations: tuple[PriceObservation, ...]) -> None:
        if not observations:
            raise ValueError("a refresh must contain at least one observation")
        if len({observation.security for observation in observations}) != len(observations):
            raise ValueError("a refresh must not contain duplicate securities")
        self.latest_observations = observations

    def begin_price_refresh(self, operation: PriceRefreshOperation) -> None:
        if self.latest_operation is not None and self.latest_operation.status is PriceRefreshOperationStatus.IN_PROGRESS:
            raise PriceRefreshConflict("a price refresh is already in progress")
        self.latest_operation = operation

    def complete_price_refresh(self, operation_id: UUID, observations: tuple[PriceObservation, ...], completed_at: datetime) -> None:
        if self.latest_operation is None or self.latest_operation.operation_id != operation_id:
            raise ValueError("price refresh operation is not current")
        self.apply_price_refresh(observations)
        prior = self.latest_operation
        self.latest_operation = PriceRefreshOperation(operation_id, PriceRefreshOperationStatus.COMPLETED, prior.started_at, prior.provider_identity, prior.expected_security_count, completed_at, len(observations), max(item.observed_at for item in observations))

    def fail_price_refresh(self, operation_id: UUID, *, completed_at: datetime, failure_code: str, failure_message: str) -> None:
        if self.latest_operation is None or self.latest_operation.operation_id != operation_id:
            raise ValueError("price refresh operation is not current")
        prior = self.latest_operation
        self.latest_operation = PriceRefreshOperation(operation_id, PriceRefreshOperationStatus.FAILED, prior.started_at, prior.provider_identity, prior.expected_security_count, completed_at, failure_code=failure_code, failure_message=failure_message)

    def recover_interrupted_price_refresh(self, operation_id: UUID, *, recovered_at: datetime) -> None:
        if self.latest_operation is None or self.latest_operation.operation_id != operation_id or self.latest_operation.status is not PriceRefreshOperationStatus.IN_PROGRESS:
            raise ValueError("no in-progress price refresh operation requires recovery")
        prior = self.latest_operation
        self.latest_operation = PriceRefreshOperation(prior.operation_id, PriceRefreshOperationStatus.FAILED, prior.started_at, prior.provider_identity, prior.expected_security_count, recovered_at, failure_code="refresh_interrupted", failure_message="operator marked the unfinished refresh as interrupted")
