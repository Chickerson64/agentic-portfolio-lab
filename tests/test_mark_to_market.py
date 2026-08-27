"""Focused regressions for persisted-price synchronized mark-to-market."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agentic_portfolio_lab.application.mark_to_market import MarkToMarketService
from agentic_portfolio_lab.application.wave2_commands import BenchmarkFulfillmentService, CashEventService
from agentic_portfolio_lab.domain.performance import PerformanceComparison
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio, Position, SecurityIdentity
from agentic_portfolio_lab.domain.valuation import PortfolioValuation, PriceObservation
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore, SQLitePriceRefreshState
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteMvpReadState


UTC = timezone.utc
START = datetime(2026, 8, 26, 14, tzinfo=UTC)


def _quote(security, price, observed_at):
    return PriceObservation(security, Decimal(price), observed_at.date(), observed_at, "USD", "test-prices", "test-quote")


def _fulfilled_store(tmp_path):
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    initial = store.initialize_run(initialized_at=START)
    spy = initial.benchmark_portfolio.benchmark_security
    CashEventService(store).apply(amount=Decimal("1000"), currency="USD", source="funding", effective_at=START + timedelta(minutes=2))
    first_quote = _quote(spy, "500", START + timedelta(minutes=3))
    SQLitePriceRefreshState(store).apply_price_refresh((first_quote,))
    assert BenchmarkFulfillmentService(store).fulfill(fulfilled_at=START + timedelta(minutes=4)).status.value == "FULFILLED"
    return store, spy


def test_refresh_marks_fulfilled_benchmark_and_keeps_cash_only_managed_valid(tmp_path) -> None:
    store, spy = _fulfilled_store(tmp_path)
    before = store.open_run()
    assert before is not None
    before_benchmark = before.benchmark_history.snapshots[-1].valuation
    managed_cash = before.managed_portfolio.cash_balance.amount
    quantity = before.benchmark_portfolio.portfolio.positions[0].quantity
    cost_basis = before.benchmark_portfolio.portfolio.positions[0].total_cost_basis

    SQLitePriceRefreshState(store).apply_price_refresh((_quote(spy, "600", START + timedelta(minutes=5)),))

    after = SQLiteLocalRunStore(tmp_path / "run.sqlite").open_run()
    assert after is not None
    assert len(after.managed_history.snapshots) == len(before.managed_history.snapshots) + 1
    assert len(after.benchmark_history.snapshots) == len(before.benchmark_history.snapshots) + 1
    assert after.managed_portfolio.cash_balance.amount == managed_cash
    latest = after.benchmark_history.snapshots[-1].valuation
    assert latest.total_value > before_benchmark.total_value
    assert latest.position_valuations[0].quantity == quantity
    assert latest.position_valuations[0].total_cost_basis == cost_basis
    assert PerformanceComparison(after.managed_history, after.benchmark_history).benchmark_cumulative_return > Decimal("0")


def _state_with_crm_position(tmp_path):
    store, spy = _fulfilled_store(tmp_path)
    state = store.open_run()
    assert state is not None
    crm = SecurityIdentity("CRM", "EQUITY", "NYSE", "USD")
    portfolio = Portfolio(
        state.managed_portfolio.portfolio_id, state.managed_portfolio.portfolio_name, "USD", state.managed_portfolio.starting_capital,
        CashBalance("USD", Decimal("900")), state.managed_portfolio.created_at,
        (Position(crm, Decimal("1"), Decimal("100"), Decimal("100")),), state.managed_portfolio.status,
    )
    at = START + timedelta(minutes=5)
    crm_quote, spy_quote = _quote(crm, "100", at), _quote(spy, "500", at)
    managed = PortfolioValuation.from_portfolio(portfolio, (crm_quote,), as_of_timestamp=at, market_date=at.date(), source_price_timestamp=at, source_provider_identity="test-prices", price_convention="test-quote")
    benchmark = PortfolioValuation.from_benchmark(state.benchmark_portfolio, (spy_quote,), as_of_timestamp=at, market_date=at.date(), source_price_timestamp=at, source_provider_identity="test-prices", price_convention="test-quote")
    prepared = replace(
        state, managed_portfolio=portfolio,
        managed_history=state.managed_history.append(portfolio, managed),
        benchmark_history=state.benchmark_history.append(state.benchmark_portfolio, benchmark),
        price_observations=(*state.price_observations, crm_quote, spy_quote),
    )
    store.save_transition(prepared)
    return store, crm, spy


def test_mark_to_market_revalues_held_crm_without_changing_trade_state_or_history(tmp_path) -> None:
    store, crm, spy = _state_with_crm_position(tmp_path)
    before = store.open_run()
    assert before is not None
    crm_quote, spy_quote = _quote(crm, "110", START + timedelta(minutes=6)), _quote(spy, "600", START + timedelta(minutes=7))
    refreshed = replace(before, price_observations=(*before.price_observations, crm_quote, spy_quote))
    after = MarkToMarketService.propose(refreshed, (crm_quote, spy_quote))
    valuation = after.managed_history.snapshots[-1].valuation
    position = valuation.position_valuations[0]
    assert valuation.cash_value == Decimal("900")
    assert position.quantity == Decimal("1") and position.total_cost_basis == Decimal("100")
    assert position.market_value == Decimal("110") and position.unrealized_gain_loss == Decimal("10")
    assert after.managed_history.snapshots[:-1] == before.managed_history.snapshots
    assert after.benchmark_history.snapshots[:-1] == before.benchmark_history.snapshots
    comparison = PerformanceComparison(after.managed_history, after.benchmark_history)
    assert comparison.managed_history.snapshots[-1].timestamp == comparison.benchmark_history.snapshots[-1].timestamp
    store.save_transition(after)
    reopened = SQLiteLocalRunStore(tmp_path / "run.sqlite").open_run()
    assert reopened is not None and reopened.managed_history == after.managed_history


def test_refresh_reuses_an_unchanged_held_quote_alongside_a_new_held_quote(tmp_path) -> None:
    store, crm, spy = _state_with_crm_position(tmp_path)
    state = store.open_run()
    assert state is not None
    unchanged_spy = next(item for item in state.price_observations if item.security == spy and item.observed_at == START + timedelta(minutes=5))
    new_crm = _quote(crm, "110", START + timedelta(minutes=6))
    SQLitePriceRefreshState(store).apply_price_refresh((new_crm, unchanged_spy))
    reopened = store.open_run()
    assert reopened is not None
    assert new_crm in reopened.price_observations
    assert reopened.managed_history.snapshots[-1].valuation.position_valuations[0].market_value == Decimal("110")


def test_mark_to_market_restores_a_comparable_tail_after_managed_only_transition(tmp_path) -> None:
    store, crm, spy = _state_with_crm_position(tmp_path)
    state = store.open_run()
    assert state is not None
    execution_time = START + timedelta(minutes=6)
    execution_quote = _quote(crm, "105", execution_time)
    execution_valuation = PortfolioValuation.from_portfolio(
        state.managed_portfolio, (execution_quote,), as_of_timestamp=execution_time, market_date=execution_time.date(),
        source_price_timestamp=execution_time, source_provider_identity="test-prices", price_convention="test-quote",
    )
    skewed = replace(
        state,
        managed_history=state.managed_history.append(state.managed_portfolio, execution_valuation),
        price_observations=(*state.price_observations, execution_quote),
    )
    store.save_transition(skewed)
    crm_quote, spy_quote = _quote(crm, "110", START + timedelta(minutes=7)), _quote(spy, "600", START + timedelta(minutes=8))
    SQLitePriceRefreshState(store).apply_price_refresh((crm_quote, spy_quote))
    reopened = store.open_run()
    assert reopened is not None
    assert len(reopened.managed_history.snapshots) == len(reopened.benchmark_history.snapshots) + 1
    comparison = PerformanceComparison(reopened.managed_history, reopened.benchmark_history)
    assert comparison.managed_history.snapshots[-1].timestamp == comparison.benchmark_history.snapshots[-1].timestamp
    assert SQLiteMvpReadState(store).snapshot().comparison is not None
    tampered_first = replace(
        reopened.benchmark_history.snapshots[0],
        valuation=replace(reopened.benchmark_history.snapshots[0].valuation, source_provider_identity="tampered-provider"),
    )
    tampered_history = replace(
        reopened.benchmark_history,
        snapshots=(tampered_first, *reopened.benchmark_history.snapshots[1:]),
    )
    with pytest.raises(ValueError, match="source_provider_identity"):
        PerformanceComparison(reopened.managed_history, tampered_history)


def test_missing_or_wrong_held_security_price_fails_without_a_valuation(tmp_path) -> None:
    store, crm, spy = _state_with_crm_position(tmp_path)
    state = store.open_run()
    assert state is not None
    crm_quote = _quote(crm, "110", START + timedelta(minutes=6))
    with pytest.raises(ValueError, match="missing prices"):
        MarkToMarketService.propose(replace(state, price_observations=(*state.price_observations, crm_quote)), (crm_quote,))
    wrong_crm = _quote(SecurityIdentity("CRM", "EQUITY", "NASDAQ", "USD"), "110", START + timedelta(minutes=6))
    with pytest.raises(ValueError, match="missing prices"):
        MarkToMarketService.propose(replace(state, price_observations=(*state.price_observations, wrong_crm)), (wrong_crm, _quote(spy, "600", START + timedelta(minutes=7))))
