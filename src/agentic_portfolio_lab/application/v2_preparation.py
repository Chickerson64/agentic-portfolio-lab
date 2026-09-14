"""Configured application entry point for a V2 weekly preparation run."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol, runtime_checkable

from .v2_weekly_cycle import V2WeeklyCycleService

@runtime_checkable
class V2PriceSnapshotProvider(Protocol):
    def snapshot(self, portfolio, target): ...

@runtime_checkable
class V2TargetManager(Protocol):
    def decide_v2(self, context): ...


@dataclass(frozen=True, slots=True)
class V2WeeklyPreparationService:
    cycle_service: V2WeeklyCycleService
    universe_service: object
    screening_service: object
    research_service: object
    manager: V2TargetManager
    price_snapshot_provider: V2PriceSnapshotProvider
    manager_risk_service: object
    reviewer: object | None
    profile_identity: object
    now: Callable[[], datetime]

    def __post_init__(self) -> None:
        required = ((self.universe_service, "refresh"), (self.screening_service, "execute"), (self.research_service, "build"), (self.manager_risk_service, "assess"))
        if not isinstance(self.manager, V2TargetManager) or not isinstance(self.price_snapshot_provider, V2PriceSnapshotProvider):
            raise TypeError("V2 preparation requires typed target-manager and price-snapshot collaborators")
        if any(not callable(getattr(item, method, None)) for item, method in required):
            raise TypeError("V2 preparation collaborators do not implement the required authoritative service contract")

    def prepare(self):
        universe = self.universe_service.refresh()
        return self.cycle_service.prepare(
            snapshot_id=universe.snapshot_id, profile_identity=self.profile_identity, as_of=self.now(),
            screening_service=self.screening_service, research_service=self.research_service,
            manager=self.manager, price_snapshot=self.price_snapshot_provider,
            manager_risk_service=self.manager_risk_service, reviewer=self.reviewer,
        )
