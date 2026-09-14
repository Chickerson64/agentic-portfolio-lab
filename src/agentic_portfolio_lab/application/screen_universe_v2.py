"""Application boundary for reproducible V2 screening artifacts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping

from agentic_portfolio_lab.domain.market_data import BatchDailyBarsProvider, DailyBar, MarketDataProvider
from agentic_portfolio_lab.domain.screening_v2 import (
    ScreeningProfileIdentity,
    ScreeningProvenance,
    ScreeningRunV2,
    screen_universe_v2,
)
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore


class ScreenUniverseV2Service:
    """Loads one immutable snapshot, fetches daily bars, and appends one artifact."""

    def __init__(self, store: SQLiteLocalRunStore, market_data: MarketDataProvider, *, clock: Callable[[], datetime] | None = None) -> None:
        self._store = store
        self._market_data = market_data
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def execute(
        self,
        *,
        snapshot_id: str,
        profile_identity: ScreeningProfileIdentity,
        as_of: datetime,
    ) -> ScreeningRunV2:
        """Screen using only a profile previously persisted under ``profile_identity``."""
        if not isinstance(profile_identity, ScreeningProfileIdentity):
            raise TypeError("profile_identity must be a ScreeningProfileIdentity")
        snapshot = self._store.load_universe_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError(f"universe snapshot not found: {snapshot_id}")
        state = self._store.open_run()
        if state is None:
            raise ValueError("local SQLite run has not been initialized")
        if as_of.tzinfo is None or as_of.utcoffset() != timezone.utc.utcoffset(as_of):
            raise ValueError("as_of must be UTC")
        profile = self._store.load_screening_profile(profile_identity)
        if profile is None:
            raise ValueError(f"screening profile not found: {profile_identity!r}")
        # A request that includes today's 1Day aggregate can observe an active
        # session.  Weekly screening therefore consumes only completed dates.
        end = as_of.date() - timedelta(days=1)
        start = end - timedelta(days=max(30, profile.required_history_days * 3))
        bars = self._daily_bars(snapshot.eligible_universe, start=start, end=end)
        benchmark_bars = None
        if profile.benchmark is not None:
            benchmark_bars = tuple(self._market_data.get_daily_bars(profile.benchmark, start=start, end=end))
        providers = {bar.source_provider_identity for history in bars.values() for bar in history}
        if benchmark_bars:
            providers.update(bar.source_provider_identity for bar in benchmark_bars)
        provenance = ScreeningProvenance(as_of, tuple(sorted(providers)) or ("unknown-market-data-provider",), snapshot.snapshot_id, self._clock())
        current_holdings = tuple(position.security for position in state.managed_portfolio.positions if position.quantity > 0)
        run = screen_universe_v2(snapshot=snapshot, profile=profile, daily_bars=bars, benchmark_bars=benchmark_bars, current_holdings=current_holdings, provenance=provenance)
        self._store.save_screening_artifact(run)
        return run

    def _daily_bars(self, securities, *, start, end) -> dict[str, tuple[DailyBar, ...]]:
        if isinstance(self._market_data, BatchDailyBarsProvider):
            supplied = self._market_data.get_daily_bars_batch(securities, start=start, end=end)
            if not isinstance(supplied, Mapping) or set(supplied) != {security.ticker for security in securities}:
                raise ValueError("batch daily-bars provider must return exactly one history for every requested security")
            result = {security.ticker: tuple(supplied[security.ticker]) for security in securities}
        else:
            result = {security.ticker: tuple(self._market_data.get_daily_bars(security, start=start, end=end)) for security in securities}
        if any(any(not isinstance(bar, DailyBar) or bar.security != security for bar in result[security.ticker]) for security in securities):
            raise ValueError("daily-bars provider returned a history bound to the wrong security")
        return result
