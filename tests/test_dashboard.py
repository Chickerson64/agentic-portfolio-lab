from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest

from agentic_portfolio_lab.dashboard import (
    _display_reviewer,
    _display_ticker,
    _metric_delta,
    _portfolio_heading,
    build_dashboard_view,
    format_decimal,
    format_percent,
)
from agentic_portfolio_lab.dashboard_demo import build_demo_dashboard_data, build_demo_dashboard_view
from agentic_portfolio_lab.domain.performance import BenchmarkPerformanceHistory, PerformanceComparison, PortfolioPerformanceHistory
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio
from agentic_portfolio_lab.domain.valuation import BenchmarkPortfolio, PortfolioValuation


def test_decimal_and_percent_formatting_is_deterministic() -> None:
    assert format_decimal(Decimal("10.5000")) == "10.5"
    assert format_decimal(Decimal("10.555"), places=2) == "10.56"
    assert format_percent(Decimal("0.1234")) == "12.34%"


def test_decimal_formatting_is_ambient_context_independent() -> None:
    with localcontext() as context:
        context.prec = 2
        assert format_decimal(Decimal("123456789.555"), places=2) == "123456789.56"
        assert format_percent(Decimal("0.123456")) == "12.35%"
        assert format_percent(Decimal("-0.123456")) == "-12.35%"


def test_demo_dashboard_view_has_managed_benchmark_and_comparison_sections() -> None:
    view = build_demo_dashboard_view()

    assert view.managed.portfolio_name == "Managed Value"
    assert view.managed.positions
    assert view.benchmark.spy_quantity == "5"
    assert view.comparison.managed_cumulative_return.endswith("%")
    assert view.comparison.absolute_alpha.endswith("%")
    assert _portfolio_heading(view.managed) == "Managed Value"
    assert view.managed.portfolio_id not in _portfolio_heading(view.managed)


def test_demo_dashboard_includes_latest_decision_summary() -> None:
    view = build_demo_dashboard_view()

    assert view.latest_decision is not None
    assert view.latest_decision.manager_action == "HOLD"
    assert view.latest_decision.human_approval_status == "APPROVED"
    assert _display_ticker(view.latest_decision) == "n/a"
    assert _display_reviewer(view.latest_decision) == "Not reviewed"


def test_buy_decision_displays_actual_ticker_and_reviewer_state() -> None:
    decision = build_demo_dashboard_view().latest_decision
    assert decision is not None
    buy = replace(decision, manager_action="BUY", ticker="AAPL", reviewer_decision="APPROVE")

    assert _display_ticker(buy) == "AAPL"
    assert _display_reviewer(buy) == "APPROVE"


def test_signed_performance_values_have_presentation_only_semantic_colors() -> None:
    assert _metric_delta("4.2%") == ("Positive", "normal")
    assert _metric_delta("-4.2%") == ("Negative", "inverse")
    assert _metric_delta("0%") == ("Neutral", "off")


def test_demo_dashboard_data_is_deterministic() -> None:
    assert build_demo_dashboard_data() == build_demo_dashboard_data()


def test_demo_dashboard_data_is_immutable_from_the_view_layer() -> None:
    data = build_demo_dashboard_data()
    managed_before = data.managed_history.snapshots
    benchmark_before = data.benchmark_history.snapshots

    build_dashboard_view(
        managed_history=data.managed_history,
        benchmark_history=data.benchmark_history,
        comparison=data.comparison,
        journal_entry=data.journal_entry,
        approval=data.approval,
    )

    assert data.managed_history.snapshots == managed_before
    assert data.benchmark_history.snapshots == benchmark_before
    assert data.managed_history.snapshots[-1].valuation.total_value == Decimal("1120")


def test_empty_position_state_renders_without_rows() -> None:
    created_at = datetime(2026, 8, 13, tzinfo=timezone.utc)
    managed_portfolio = Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Empty",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance("USD", Decimal("1000")),
        created_at=created_at,
    )
    spy = build_demo_dashboard_data().benchmark.benchmark_security
    benchmark_portfolio = BenchmarkPortfolio(
        Portfolio(
            portfolio_id=uuid4(),
            portfolio_name="Empty Benchmark",
            base_currency="USD",
            starting_capital=Decimal("1000"),
            cash_balance=CashBalance("USD", Decimal("1000")),
            created_at=created_at,
        ),
        spy,
    )
    managed_history = PortfolioPerformanceHistory(managed_portfolio.portfolio_id, "USD").append(
        managed_portfolio,
        PortfolioValuation.from_portfolio(
            managed_portfolio,
            (),
            as_of_timestamp=created_at,
            market_date=created_at.date(),
            source_price_timestamp=created_at,
            source_provider_identity="demo-provider",
            price_convention="regular-session-close",
        ),
    )
    benchmark_history = BenchmarkPerformanceHistory.for_benchmark(benchmark_portfolio).append(
        benchmark_portfolio,
        PortfolioValuation.from_benchmark(
            benchmark_portfolio,
            (),
            as_of_timestamp=created_at,
            market_date=created_at.date(),
            source_price_timestamp=created_at,
            source_provider_identity="demo-provider",
            price_convention="regular-session-close",
        ),
    )
    comparison = PerformanceComparison(managed_history, benchmark_history)
    view = build_dashboard_view(
        managed_history=managed_history,
        benchmark_history=benchmark_history,
        comparison=comparison,
    )

    assert view.managed.positions == ()
    assert view.benchmark.spy_quantity is None
    assert view.benchmark.spy_value is None
    assert view.benchmark.cash_value == "USD 1000"
    assert view.latest_decision is None


def test_optional_latest_decision_can_be_omitted() -> None:
    data = build_demo_dashboard_data()
    view = build_dashboard_view(
        managed_history=data.managed_history,
        benchmark_history=data.benchmark_history,
        comparison=data.comparison,
    )

    assert view.latest_decision is None


def test_reordered_valuation_is_mapped_by_security_and_uses_valuation_pnl() -> None:
    data = build_demo_dashboard_data()
    snapshot = data.managed_history.snapshots[-1]
    reordered_valuation = replace(
        snapshot.valuation,
        position_valuations=tuple(reversed(snapshot.valuation.position_valuations)),
    )
    reordered_snapshot = replace(snapshot, valuation=reordered_valuation)
    reordered_history = replace(data.managed_history, snapshots=(*data.managed_history.snapshots[:-1], reordered_snapshot))

    view = build_dashboard_view(
        managed_history=reordered_history,
        benchmark_history=data.benchmark_history,
    )

    rows = {row.ticker: row for row in view.managed.positions}
    assert rows["AAPL"].market_value == "USD 330"
    assert rows["AAPL"].portfolio_weight == "29.46%"
    assert rows["AAPL"].unrealized_pnl == "USD 50"
    assert rows["MSFT"].market_value == "USD 340"


def test_dashboard_rejects_comparison_that_does_not_reference_displayed_history_instances() -> None:
    data = build_demo_dashboard_data()
    cloned_managed_history = replace(data.managed_history)
    unrelated_comparison = PerformanceComparison(cloned_managed_history, data.benchmark_history)

    with pytest.raises(ValueError, match="comparison histories"):
        build_dashboard_view(
            managed_history=data.managed_history,
            benchmark_history=data.benchmark_history,
            comparison=unrelated_comparison,
        )
