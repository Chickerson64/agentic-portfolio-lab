"""Regression coverage for decision history after later paired revaluations."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agentic_portfolio_lab.api.app import create_app
from agentic_portfolio_lab.api.queries import MvpQueryService
from agentic_portfolio_lab.application.mark_to_market import MarkToMarketService
from agentic_portfolio_lab.application.managed_execution import ManagedPaperExecutionService
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.dashboard import _synchronized_snapshot_pair_for_decision_cycle
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteMvpReadState

from .test_managed_execution import _prepared_store


def _later_quote(execution, *, price: str, offset: int) -> PriceObservation:
    observed_at = execution.executed_trade.executed_at + timedelta(minutes=offset)
    return PriceObservation(
        security=execution.executed_trade.security,
        observed_price=Decimal(price),
        market_date=observed_at.date(), observed_at=observed_at, currency="USD",
        source_provider_identity="test-provider", price_convention="provider-quote-close",
    )


def _append_mark_to_market(store, quote: PriceObservation) -> None:
    state = store.open_run()
    assert state is not None
    proposed = MarkToMarketService.propose(
        replace(state, price_observations=(*state.price_observations, quote)), (quote,)
    )
    store.save_transition(proposed)


def test_executed_history_uses_first_synchronized_pair_not_later_mark_to_market(tmp_path) -> None:
    store, journal, _, quote = _prepared_store(tmp_path)
    execution = ManagedPaperExecutionService(store).execute(
        decision_cycle_id=journal.decision_cycle_id, executed_at=quote.observed_at + timedelta(minutes=1),
    ).execution
    initial_pair_quote = _later_quote(execution, price="102", offset=1)
    later_pair_quote = _later_quote(execution, price="105", offset=2)
    _append_mark_to_market(store, initial_pair_quote)
    _append_mark_to_market(store, later_pair_quote)

    client = TestClient(create_app(database_path=str(tmp_path / "run.sqlite")))
    decisions = client.get("/decisions")
    dashboard = client.get("/dashboard")
    performance = client.get("/performance")

    assert decisions.status_code == dashboard.status_code == performance.status_code == 200
    assert decisions.json()["entries_newest_first"][0]["lifecycle_status"] == "EXECUTED"
    assert performance.json()["as_of_timestamp"] == later_pair_quote.observed_at.isoformat()
    state = store.open_run()
    assert state is not None
    assert state.executions[0].executed_trade == execution.executed_trade
    view = MvpQueryService(SQLiteMvpReadState(store))._dashboard_view()
    assert view.history is not None
    assert view.history.entries_newest_first[0].snapshot is not None
    assert view.history.entries_newest_first[0].snapshot.timestamp == initial_pair_quote.observed_at.isoformat()
    assert tuple(point.timestamp_at for point in view.history.chart_points_oldest_first[-2:]) == (
        initial_pair_quote.observed_at, later_pair_quote.observed_at,
    )


def test_multiple_benchmark_snapshots_for_one_timestamp_remain_fail_closed(tmp_path) -> None:
    store, journal, _, quote = _prepared_store(tmp_path)
    execution = ManagedPaperExecutionService(store).execute(
        decision_cycle_id=journal.decision_cycle_id, executed_at=quote.observed_at + timedelta(minutes=1),
    ).execution
    first_pair_quote = _later_quote(execution, price="102", offset=1)
    _append_mark_to_market(store, first_pair_quote)
    state = store.open_run()
    assert state is not None
    malformed_benchmark_history = SimpleNamespace(
        snapshots=(state.benchmark_history.snapshots[-1], state.benchmark_history.snapshots[-1]),
    )

    with pytest.raises(ValueError, match="multiple benchmark snapshots"):
        _synchronized_snapshot_pair_for_decision_cycle(
            state.managed_history, malformed_benchmark_history,
            journal_entry=state.journal_entries[0], executed_trade=state.executions[0].executed_trade,
        )
