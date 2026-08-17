"""Operator OVERVIEW cache-fill for the versioned managed universe.

This command fetches Alpha Vantage OVERVIEW only. It never pulls statements,
never retries, and persists each successful row before the next request so a
later failure cannot discard quota already spent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol, Sequence

from agentic_portfolio_lab.application.market_configuration import ALPHA_VANTAGE_DAILY_REQUEST_LIMIT
from agentic_portfolio_lab.application.refresh_fundamentals import provider_fundamental_record_from_normalized
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.provider_fundamentals import ProviderEndpoint, ProviderFundamentalRecord
from agentic_portfolio_lab.domain.research_provider import NormalizedOverviewFacts
from agentic_portfolio_lab.domain.universe import CandidateUniverse

_PROVIDER_IDENTITY = "alpha-vantage"


class OverviewBootstrapProvider(Protocol):
    def fetch_overview(self, security: SecurityIdentity, *, as_of: datetime | None = None) -> NormalizedOverviewFacts: ...


class OverviewBootstrapState(Protocol):
    def load_fundamental_records(self) -> tuple[ProviderFundamentalRecord, ...]: ...

    def persist_overview_record(self, record: ProviderFundamentalRecord) -> None: ...


@dataclass(frozen=True, slots=True)
class BootstrapOverviewResult:
    fetched: tuple[SecurityIdentity, ...]
    skipped: tuple[SecurityIdentity, ...]
    remaining: tuple[SecurityIdentity, ...]
    request_count: int
    provider_identity: str


def _require_aware(as_of: datetime) -> datetime:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("overview bootstrap clock must return a timezone-aware datetime")
    return as_of


def _has_cached_overview(records: Sequence[ProviderFundamentalRecord], security: SecurityIdentity) -> bool:
    return any(record.security == security and record.endpoint is ProviderEndpoint.OVERVIEW for record in records)


class BootstrapOverviewService:
    """Fill missing OVERVIEW rows for VALUE_US_EQUITIES_V1, at most 25 fetches per call."""

    def __init__(
        self,
        *,
        provider: OverviewBootstrapProvider,
        state: OverviewBootstrapState,
        universe: CandidateUniverse,
        request_limit: int = ALPHA_VANTAGE_DAILY_REQUEST_LIMIT,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if request_limit < 1:
            raise ValueError("request_limit must be at least 1")
        self._provider = provider
        self._state = state
        self._universe = universe
        self._request_limit = request_limit
        self._now = now or (lambda: datetime.now(timezone.utc))

    def bootstrap(self) -> BootstrapOverviewResult:
        as_of = _require_aware(self._now())
        cached = list(self._state.load_fundamental_records())
        fetched: list[SecurityIdentity] = []
        skipped: list[SecurityIdentity] = []
        request_count = 0
        for security in self._universe.identities:
            if _has_cached_overview(cached, security):
                skipped.append(security)
                continue
            if request_count >= self._request_limit:
                continue
            overview = self._provider.fetch_overview(security, as_of=as_of)
            request_count += 1
            record = provider_fundamental_record_from_normalized(
                security,
                ProviderEndpoint.OVERVIEW,
                overview,
                as_of,
            )
            self._state.persist_overview_record(record)
            cached.append(record)
            fetched.append(security)
        remaining = tuple(
            security
            for security in self._universe.identities
            if not _has_cached_overview(cached, security)
        )
        return BootstrapOverviewResult(
            fetched=tuple(fetched),
            skipped=tuple(skipped),
            remaining=remaining,
            request_count=request_count,
            provider_identity=_PROVIDER_IDENTITY,
        )
