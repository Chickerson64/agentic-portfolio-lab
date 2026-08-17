"""Application service for one complete, source-attributed research batch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol, Sequence
from uuid import uuid4

from agentic_portfolio_lab.application.assemble_research_packets import assemble_research_packet
from agentic_portfolio_lab.application.refresh_fundamentals import (
    FundamentalEndpointProvider,
    RefreshFundamentalsService,
)
from agentic_portfolio_lab.application.screen_research import ScreeningService
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.provider_fundamentals import (
    ProviderEndpoint,
    ProviderFundamentalRecord,
    ReuseStatus,
)
from agentic_portfolio_lab.domain.research import ResearchBatch, ResearchPacket
from agentic_portfolio_lab.domain.screening import ScreeningRun
from agentic_portfolio_lab.domain.universe import CandidateUniverse
from agentic_portfolio_lab.domain.valuation import PriceObservation


@dataclass(frozen=True, slots=True)
class ResearchCycleInputs:
    """Current-cycle prices and cached fundamental records for screening."""

    price_observations: tuple[PriceObservation, ...]
    fundamental_records: tuple[ProviderFundamentalRecord, ...]


class ResearchCycleState(Protocol):
    def load_research_inputs(self) -> ResearchCycleInputs: ...

    def persist_research_cycle(
        self,
        *,
        screening_run: ScreeningRun,
        fetched_records: Sequence[ProviderFundamentalRecord],
        batch: ResearchBatch,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class BuildResearchResult:
    batch: ResearchBatch
    provider_identity: str


def _require_aware(as_of: datetime) -> datetime:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("research clock must return a timezone-aware datetime")
    return as_of


def _packets_in_universe_order(
    universe: CandidateUniverse,
    packets_by_security: dict[SecurityIdentity, ResearchPacket],
) -> tuple[ResearchPacket, ...]:
    """Order manager-facing packets by universe identity, not screening rank or slot."""
    return tuple(
        packets_by_security[security]
        for security in universe.identities
        if security in packets_by_security
    )


def _cycle_price(
    observations: Sequence[PriceObservation],
    security: SecurityIdentity,
) -> PriceObservation:
    matches = [observation for observation in observations if observation.security == security]
    if not matches:
        raise ValueError(f"missing this-cycle price observation for {security.ticker}")
    latest_at = max(observation.observed_at for observation in matches)
    latest = tuple(observation for observation in matches if observation.observed_at == latest_at)
    if len(latest) != 1:
        raise ValueError(f"ambiguous this-cycle price observations for {security.ticker}")
    return latest[0]


class BuildResearchService:
    """Screen the universe, refresh selected names, then persist one research cycle."""

    def __init__(
        self,
        *,
        provider: FundamentalEndpointProvider,
        state: ResearchCycleState,
        universe: CandidateUniverse,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._state = state
        self._universe = universe
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._screening = ScreeningService()
        self._refresh = RefreshFundamentalsService(provider=provider, now=self._now)

    def build(self, *, portfolio_id, manager_type: str = "VALUE") -> BuildResearchResult:
        as_of = _require_aware(self._now())
        inputs = self._state.load_research_inputs()
        screening_run = self._screening.screen(
            universe=self._universe,
            price_observations=inputs.price_observations,
            fundamental_records=inputs.fundamental_records,
            screening_run_id=uuid4(),
            as_of=as_of,
        )
        if not screening_run.selected:
            raise ValueError(
                "screening selected no eligible priced names; cannot persist an empty research batch"
            )

        fetched_records: list[ProviderFundamentalRecord] = []
        packets_by_security: dict[SecurityIdentity, ResearchPacket] = {}
        provider_identity: str | None = None
        for security in screening_run.selected:
            price = _cycle_price(inputs.price_observations, security)
            refresh = self._refresh.refresh(security, inputs.fundamental_records, as_of)
            fetched_records.extend(
                status.record
                for status in refresh.statuses
                if status.reuse_status is ReuseStatus.FETCHED_THIS_CYCLE
            )
            if provider_identity is None:
                provider_identity = refresh.status_for(ProviderEndpoint.OVERVIEW).record.provider_identity
            packets_by_security[security] = assemble_research_packet(
                security=security, refresh=refresh, price=price, as_of=as_of
            )

        created_at = _require_aware(self._now())
        batch = ResearchBatch(
            batch_id=f"research-{uuid4()}",
            decision_cycle_id=uuid4(),
            portfolio_id=portfolio_id,
            manager_type=manager_type,
            created_at=created_at,
            as_of_timestamp=as_of,
            packets=_packets_in_universe_order(self._universe, packets_by_security),
            screening_run_id=screening_run.screening_run_id,
        )
        self._state.persist_research_cycle(
            screening_run=screening_run,
            fetched_records=tuple(fetched_records),
            batch=batch,
        )
        if provider_identity is None:
            raise ValueError("research cycle produced packets without provider identity")
        return BuildResearchResult(batch, provider_identity)
