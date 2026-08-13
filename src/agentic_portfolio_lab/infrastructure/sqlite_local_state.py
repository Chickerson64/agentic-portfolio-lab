"""SQLite implementation of the small local-run state boundary."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from agentic_portfolio_lab.application.local_state import LocalRunMetadata, PersistedRunState
from agentic_portfolio_lab.application.local_state_codec import decode_run_state, encode
from agentic_portfolio_lab.dashboard import DecisionHistoryArtifacts
from agentic_portfolio_lab.domain.cash_events import CashEvent, CashEventFundingWorkflow
from agentic_portfolio_lab.domain.performance import BenchmarkPerformanceHistory, PerformanceComparison, PortfolioPerformanceHistory
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio, SecurityIdentity
from agentic_portfolio_lab.domain.valuation import BenchmarkPortfolio, PortfolioValuation

SCHEMA_VERSION = 1


class SQLiteLocalRunStore:
    """Explicit local SQLite state; no ORM, event store, or repository framework."""

    def __init__(self, database_path: str | Path) -> None:
        self._path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize_run(self, *, initialized_at: datetime) -> PersistedRunState:
        if initialized_at.tzinfo is None or initialized_at.utcoffset() is None:
            raise ValueError("initialized_at must be timezone-aware")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._create_schema(connection)
            if connection.execute("SELECT 1 FROM run_metadata LIMIT 1").fetchone() is not None:
                raise ValueError("local SQLite run already exists")
        state = self._initial_state(initialized_at)
        self._save_transition(state, initializing=True)
        return state

    def open_run(self) -> PersistedRunState | None:
        if not self._path.exists():
            return None
        with self._connect() as connection:
            self._create_schema(connection)
            version = connection.execute("SELECT schema_version FROM run_metadata LIMIT 1").fetchone()
            if version is None:
                return None
            if version["schema_version"] != SCHEMA_VERSION:
                raise ValueError("unsupported local SQLite schema version")
            row = connection.execute("SELECT document FROM current_run_state WHERE singleton = 1").fetchone()
            if row is None:
                raise ValueError("local SQLite run is missing its current state document")
            return decode_run_state(json.loads(row["document"]))

    def save_transition(self, state: PersistedRunState) -> None:
        """Atomically validate and persist one append-preserving transition."""
        if not isinstance(state, PersistedRunState):
            raise TypeError("state must be a PersistedRunState")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._create_schema(connection)
            try:
                # The current-state read and replacement write share this
                # write lock. A stale writer therefore validates against the
                # last committed state, rather than an earlier observation.
                connection.execute("BEGIN IMMEDIATE")
                current = self._load_current_state(connection)
                if current is None:
                    raise ValueError("local SQLite run must be created through initialize_run")
                state.validate()
                self._validate_transition(current, state)
                self._write_state(connection, state)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _save_transition(self, state: PersistedRunState, *, initializing: bool) -> None:
        if not isinstance(state, PersistedRunState):
            raise TypeError("state must be a PersistedRunState")
        state.validate()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._create_schema(connection)
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute("SELECT schema_version FROM run_metadata LIMIT 1").fetchone()
                if existing is not None and existing["schema_version"] != SCHEMA_VERSION:
                    raise ValueError("unsupported local SQLite schema version")
                if existing is not None and initializing:
                    raise ValueError("local SQLite run already exists")
                if existing is None and not initializing:
                    raise ValueError("local SQLite run must be created through initialize_run")
                if existing is not None:
                    current_identity = connection.execute(
                        "SELECT run_id, initialized_at FROM run_metadata WHERE singleton = 1"
                    ).fetchone()
                    assert current_identity is not None
                    if current_identity["run_id"] != str(state.metadata.run_id):
                        raise ValueError("save_transition must not change run_id")
                    if current_identity["initialized_at"] != state.metadata.initialized_at.isoformat():
                        raise ValueError("save_transition must not change initialized_at")
                self._write_state(connection, state)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _load_current_state(connection: sqlite3.Connection) -> PersistedRunState | None:
        version = connection.execute("SELECT schema_version FROM run_metadata LIMIT 1").fetchone()
        if version is None:
            return None
        if version["schema_version"] != SCHEMA_VERSION:
            raise ValueError("unsupported local SQLite schema version")
        row = connection.execute("SELECT document FROM current_run_state WHERE singleton = 1").fetchone()
        if row is None:
            raise ValueError("local SQLite run is missing its current state document")
        return decode_run_state(json.loads(row["document"]))

    def _write_state(self, connection: sqlite3.Connection, state: PersistedRunState) -> None:
        document = json.dumps(encode(state), separators=(",", ":"), sort_keys=True)
        connection.execute(
            "INSERT OR REPLACE INTO run_metadata (singleton, run_id, status, initialized_at, schema_version) VALUES (1, ?, ?, ?, ?)",
            (str(state.metadata.run_id), state.metadata.status, state.metadata.initialized_at.isoformat(), SCHEMA_VERSION),
        )
        connection.execute("INSERT OR REPLACE INTO current_run_state (singleton, document) VALUES (1, ?)", (document,))
        self._replace_index_rows(connection, state)

    @staticmethod
    def _validate_transition(current: PersistedRunState, proposed: PersistedRunState) -> None:
        if current.metadata.run_id != proposed.metadata.run_id:
            raise ValueError("save_transition must not change run_id")
        if current.metadata.initialized_at != proposed.metadata.initialized_at:
            raise ValueError("save_transition must not change initialized_at")
        SQLiteLocalRunStore._require_history_prefix(
            current.managed_history.snapshots,
            proposed.managed_history.snapshots,
            label="managed performance history",
        )
        SQLiteLocalRunStore._require_history_prefix(
            current.benchmark_history.snapshots,
            proposed.benchmark_history.snapshots,
            label="benchmark performance history",
        )
        SQLiteLocalRunStore._require_immutable_records(
            current.funding_results,
            proposed.funding_results,
            key=lambda result: result.cash_event.event_id,
            label="funding results",
        )
        SQLiteLocalRunStore._require_immutable_records(
            current.price_observations,
            proposed.price_observations,
            key=lambda observation: (observation.security, observation.observed_at),
            label="price observations",
        )
        SQLiteLocalRunStore._require_immutable_records(
            current.research_batches,
            proposed.research_batches,
            key=lambda batch: batch.batch_id,
            label="research batches",
        )
        SQLiteLocalRunStore._require_immutable_records(
            current.journal_entries,
            proposed.journal_entries,
            key=lambda journal: journal.decision_cycle_id,
            label="decision journals",
        )
        SQLiteLocalRunStore._require_immutable_records(
            current.approvals,
            proposed.approvals,
            key=lambda approval: approval.decision_cycle_id,
            label="approvals",
        )
        SQLiteLocalRunStore._require_immutable_records(
            current.executions,
            proposed.executions,
            key=lambda execution: execution.executed_trade.executed_trade_id,
            label="executions",
        )
        SQLiteLocalRunStore._require_immutable_records(
            current.history_entries,
            proposed.history_entries,
            key=lambda entry: entry.journal_entry.decision_cycle_id,
            label="history entries",
        )

    @staticmethod
    def _require_history_prefix(current: tuple[object, ...], proposed: tuple[object, ...], *, label: str) -> None:
        if len(proposed) < len(current) or proposed[: len(current)] != current:
            raise ValueError(f"{label} must preserve the persisted prefix")

    @staticmethod
    def _require_immutable_records(current, proposed, *, key, label: str) -> None:
        current_by_key = {key(item): item for item in current}
        proposed_by_key = {key(item): item for item in proposed}
        for identity, existing in current_by_key.items():
            replacement = proposed_by_key.get(identity)
            if replacement is None:
                raise ValueError(f"{label} must not remove persisted artifact {identity}")
            if replacement != existing:
                raise ValueError(f"{label} must not rewrite persisted artifact {identity}")

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS run_metadata (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), run_id TEXT NOT NULL, status TEXT NOT NULL, initialized_at TEXT NOT NULL, schema_version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS current_run_state (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS portfolio_state (role TEXT PRIMARY KEY, portfolio_id TEXT NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cash_events (event_id TEXT PRIMARY KEY, effective_at TEXT NOT NULL, currency TEXT NOT NULL, amount TEXT NOT NULL, source TEXT NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cash_event_funding (event_id TEXT PRIMARY KEY, managed_contribution_id TEXT NOT NULL, benchmark_contribution_id TEXT NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS price_observations (observation_key TEXT PRIMARY KEY, security_ticker TEXT NOT NULL, observed_at TEXT NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_batches (batch_id TEXT PRIMARY KEY, decision_cycle_id TEXT NOT NULL, portfolio_id TEXT NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS decision_journals (decision_cycle_id TEXT PRIMARY KEY, portfolio_id TEXT NOT NULL, journaled_at TEXT NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS approvals (decision_cycle_id TEXT PRIMARY KEY, decided_at TEXT NOT NULL, outcome TEXT NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS executions (executed_trade_id TEXT PRIMARY KEY, decision_cycle_id TEXT NOT NULL, validated_trade_id TEXT NOT NULL, executed_at TEXT NOT NULL, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS managed_history (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS benchmark_history (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS history_entries (decision_cycle_id TEXT PRIMARY KEY, document TEXT NOT NULL);
            """
        )

    @staticmethod
    def _document(value: object) -> str:
        return json.dumps(encode(value), separators=(",", ":"), sort_keys=True)

    def _replace_index_rows(self, connection: sqlite3.Connection, state: PersistedRunState) -> None:
        for table in ("portfolio_state", "cash_events", "cash_event_funding", "price_observations", "research_batches", "decision_journals", "approvals", "executions", "managed_history", "benchmark_history", "history_entries"):
            connection.execute(f"DELETE FROM {table}")
        connection.executemany("INSERT INTO portfolio_state VALUES (?, ?, ?)", (("managed", str(state.managed_portfolio.portfolio_id), self._document(state.managed_portfolio)), ("benchmark", str(state.benchmark_portfolio.portfolio.portfolio_id), self._document(state.benchmark_portfolio))))
        for result in state.funding_results:
            event = result.cash_event
            connection.execute("INSERT INTO cash_events VALUES (?, ?, ?, ?, ?, ?)", (str(event.event_id), event.effective_at.isoformat(), event.currency, format(event.amount, "f"), event.source, self._document(event)))
            connection.execute("INSERT INTO cash_event_funding VALUES (?, ?, ?, ?)", (str(event.event_id), str(result.managed_contribution.contribution_id), str(result.benchmark_contribution.contribution_id), self._document(result)))
        for observation in state.price_observations:
            key = f"{observation.security.ticker}:{observation.observed_at.isoformat()}"
            connection.execute("INSERT INTO price_observations VALUES (?, ?, ?, ?)", (key, observation.security.ticker, observation.observed_at.isoformat(), self._document(observation)))
        for batch in state.research_batches:
            connection.execute("INSERT INTO research_batches VALUES (?, ?, ?, ?)", (batch.batch_id, str(batch.decision_cycle_id), str(batch.portfolio_id), self._document(batch)))
        for journal in state.journal_entries:
            connection.execute("INSERT INTO decision_journals VALUES (?, ?, ?, ?)", (str(journal.decision_cycle_id), str(journal.portfolio_id), journal.journaled_at.isoformat(), self._document(journal)))
        for approval in state.approvals:
            connection.execute("INSERT INTO approvals VALUES (?, ?, ?, ?)", (str(approval.decision_cycle_id), approval.decided_at.isoformat(), approval.decision.value, self._document(approval)))
        for execution in state.executions:
            trade = execution.executed_trade
            connection.execute("INSERT INTO executions VALUES (?, ?, ?, ?, ?)", (str(trade.executed_trade_id), str(trade.decision_cycle_id), str(trade.validated_trade_id), trade.executed_at.isoformat(), self._document(execution)))
        connection.execute("INSERT INTO managed_history VALUES (1, ?)", (self._document(state.managed_history),))
        connection.execute("INSERT INTO benchmark_history VALUES (1, ?)", (self._document(state.benchmark_history),))
        for entry in state.history_entries:
            connection.execute("INSERT INTO history_entries VALUES (?, ?)", (str(entry.journal_entry.decision_cycle_id), self._document(entry)))

    @staticmethod
    def _initial_state(initialized_at: datetime) -> PersistedRunState:
        managed = Portfolio(uuid4(), "Managed Value", "USD", Decimal("1000"), CashBalance("USD", Decimal("0")), initialized_at)
        benchmark = BenchmarkPortfolio(Portfolio(uuid4(), "SPY Benchmark", "USD", Decimal("1000"), CashBalance("USD", Decimal("0")), initialized_at), SecurityIdentity("SPY", "ETF", "NYSEARCA", "USD"))
        funding = CashEventFundingWorkflow.apply(CashEvent(Decimal("1000"), "USD", initialized_at, "INITIAL_FUNDING"), managed, benchmark)
        funded_managed, funded_benchmark = funding.funded_managed_portfolio, funding.funded_benchmark_portfolio
        valuation_kwargs = dict(as_of_timestamp=initialized_at, market_date=initialized_at.date(), source_price_timestamp=initialized_at, source_provider_identity="initial-cash-event", price_convention="cash-only-baseline")
        managed_valuation = PortfolioValuation.from_portfolio(funded_managed, (), **valuation_kwargs)
        benchmark_valuation = PortfolioValuation.from_benchmark(funded_benchmark, (), **valuation_kwargs)
        managed_history = PortfolioPerformanceHistory(funded_managed.portfolio_id, "USD").append(funded_managed, managed_valuation)
        benchmark_history = BenchmarkPerformanceHistory.for_benchmark(funded_benchmark).append(funded_benchmark, benchmark_valuation)
        # Constructing this comparison validates equal baseline state and the shared valuation convention.
        PerformanceComparison(managed_history, benchmark_history)
        return PersistedRunState(LocalRunMetadata(uuid4(), "ACTIVE", initialized_at), funded_managed, funded_benchmark, managed_history, benchmark_history, (funding,))


class SQLiteMvpReadState:
    """Read adapter: SQLite details stay outside the FastAPI query/domain layers."""

    def __init__(self, store: SQLiteLocalRunStore) -> None:
        self._store = store

    def _state(self) -> PersistedRunState:
        state = self._store.open_run()
        if state is None:
            raise ValueError("local SQLite run has not been initialized")
        return state

    def snapshot(self):
        """Load once per query service so comparison/history identity is stable."""
        from agentic_portfolio_lab.api.queries import MvpReadStateSnapshot

        state = self._state()
        return MvpReadStateSnapshot(
            managed_history=state.managed_history,
            benchmark_history=state.benchmark_history,
            comparison=PerformanceComparison(state.managed_history, state.benchmark_history),
            latest_journal_entry=state.latest_journal_entry,
            latest_approval=state.latest_approval,
            history_entries=state.history_entries,
            source_metadata=self.source_metadata,
        )

    @property
    def source_metadata(self):
        # Import lazily to keep SQLite infrastructure independent of API module
        # initialization while still satisfying the existing read-state protocol.
        from agentic_portfolio_lab.api.queries import StateSourceMetadata

        return StateSourceMetadata(mode="local-sqlite", persisted=True, synthetic=False)

    @property
    def managed_history(self):
        return self._state().managed_history

    @property
    def benchmark_history(self):
        return self._state().benchmark_history

    @property
    def comparison(self):
        state = self._state()
        return PerformanceComparison(state.managed_history, state.benchmark_history)

    @property
    def latest_journal_entry(self):
        return self._state().latest_journal_entry

    @property
    def latest_approval(self):
        return self._state().latest_approval

    @property
    def history_entries(self) -> tuple[DecisionHistoryArtifacts, ...]:
        return self._state().history_entries
