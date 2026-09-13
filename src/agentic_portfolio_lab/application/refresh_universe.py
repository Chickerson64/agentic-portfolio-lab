"""Explicit, provider-neutral operator workflow for universe snapshots."""

from __future__ import annotations

import argparse
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from agentic_portfolio_lab.domain.universe_snapshots import UniverseEligibilityRules, UniverseSnapshot


class UniverseSource(Protocol):
    provider_identity: str

    def build_universe_snapshot(self, *, rules: UniverseEligibilityRules, retrieved_at: datetime) -> UniverseSnapshot: ...


class UniverseSnapshotStore(Protocol):
    def save_universe_snapshot(self, snapshot: UniverseSnapshot) -> None: ...

    def load_universe_snapshot(self, snapshot_id: str | None = None) -> UniverseSnapshot | None: ...


class RefreshUniverseService:
    def __init__(self, *, provider: UniverseSource, state: UniverseSnapshotStore, rules: UniverseEligibilityRules | None = None, now: Callable[[], datetime] | None = None) -> None:
        self._provider = provider
        self._state = state
        self._rules = rules or UniverseEligibilityRules()
        self._now = now or (lambda: datetime.now(timezone.utc))

    def refresh(self) -> UniverseSnapshot:
        retrieved_at = self._now()
        if not isinstance(retrieved_at, datetime) or retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("refresh clock must return a timezone-aware datetime")
        snapshot = self._provider.build_universe_snapshot(rules=self._rules, retrieved_at=retrieved_at.astimezone(timezone.utc))
        # A frozen operator/test clock is legitimate. Preserve both immutable events.
        if self._state.load_universe_snapshot(snapshot.snapshot_id) is not None:
            base = snapshot.snapshot_id
            suffix = 2
            while self._state.load_universe_snapshot(f"{base}-{suffix}") is not None:
                suffix += 1
            snapshot = replace(snapshot, snapshot_id=f"{base}-{suffix}")
        self._state.save_universe_snapshot(snapshot)
        return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh an immutable Alpaca U.S. listed-equity universe snapshot.")
    parser.add_argument("--database-path", default=os.environ.get("AGENTIC_PORTFOLIO_LAB_DB_PATH"))
    parser.add_argument("--exchange", action="append", dest="exchanges")
    parser.add_argument("--allow-nontradable", action="store_true")
    parser.add_argument("--require-fractionable", action="store_true")
    parser.add_argument("--max-symbol-length", type=int, default=12)
    args = parser.parse_args(argv)
    if not args.database_path:
        parser.error("--database-path or AGENTIC_PORTFOLIO_LAB_DB_PATH is required")
    rules = UniverseEligibilityRules(
        allowed_exchanges=tuple(args.exchanges) if args.exchanges else UniverseEligibilityRules().allowed_exchanges,
        require_tradable=not args.allow_nontradable,
        require_fractionable=args.require_fractionable,
        max_symbol_length=args.max_symbol_length,
    )
    from agentic_portfolio_lab.infrastructure.alpaca import AlpacaClient
    from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore

    snapshot = RefreshUniverseService(provider=AlpacaClient(), state=SQLiteLocalRunStore(Path(args.database_path)), rules=rules).refresh()
    print(f"refreshed {snapshot.snapshot_id}: {len(snapshot.eligible_universe)} eligible securities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
