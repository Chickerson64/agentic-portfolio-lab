"""Presentation-only dashboard models and rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from .domain.approval import DecisionApproval
from .domain.journal import DecisionJournalEntry
from .domain.performance import BenchmarkPerformanceHistory, PerformanceComparison, PortfolioPerformanceHistory
from .domain.portfolio import Portfolio, Position
from .domain.valuation import PortfolioValuation


def format_decimal(value: Decimal, *, places: int | None = None) -> str:
    """Format a Decimal for display without mutating or recalculating it."""
    if places is not None:
        quantizer = Decimal("1").scaleb(-places)
        value = value.quantize(quantizer, rounding=ROUND_HALF_UP)
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_currency(value: Decimal, currency: str) -> str:
    return f"{currency} {format_decimal(value, places=2)}"


def format_percent(value: Decimal) -> str:
    return f"{format_decimal(value * Decimal('100'), places=2)}%"


@dataclass(frozen=True, slots=True)
class PositionRow:
    ticker: str
    quantity: str
    market_value: str
    portfolio_weight: str
    total_cost_basis: str | None = None
    average_cost_basis: str | None = None
    unrealized_pnl: str | None = None


@dataclass(frozen=True, slots=True)
class PortfolioPanel:
    portfolio_id: str
    portfolio_name: str
    total_value: str
    cash_value: str
    invested_value: str
    positions: tuple[PositionRow, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkPanel:
    total_value: str
    cash_value: str
    spy_quantity: str | None
    spy_value: str | None


@dataclass(frozen=True, slots=True)
class ComparisonPanel:
    managed_cumulative_return: str
    benchmark_cumulative_return: str
    absolute_alpha: str
    relative_alpha: str


@dataclass(frozen=True, slots=True)
class LatestDecisionPanel:
    manager_action: str
    ticker: str | None
    target_weight: str | None
    confidence: str
    reviewer_decision: str | None
    human_approval_status: str | None


@dataclass(frozen=True, slots=True)
class DashboardView:
    managed: PortfolioPanel
    benchmark: BenchmarkPanel
    comparison: ComparisonPanel
    latest_decision: LatestDecisionPanel | None = None


def _format_position_row(position: Position, *, market_value: Decimal, weight: Decimal) -> PositionRow:
    return PositionRow(
        ticker=position.security.ticker,
        quantity=format_decimal(position.quantity),
        market_value=format_currency(market_value, position.security.currency),
        portfolio_weight=format_percent(weight),
        total_cost_basis=format_currency(position.total_cost_basis, position.security.currency),
        average_cost_basis=format_currency(position.average_cost_basis, position.security.currency),
        unrealized_pnl=format_currency(position.unrealized_pnl, position.security.currency),
    )


def _portfolio_panel(portfolio: Portfolio, valuation: PortfolioValuation) -> PortfolioPanel:
    weights = {security: weight for security, weight in valuation.position_weights}
    positions = tuple(
        _format_position_row(position, market_value=position_valuation.market_value, weight=weights[position.security])
        for position, position_valuation in zip(portfolio.positions, valuation.position_valuations, strict=True)
    )
    return PortfolioPanel(
        portfolio_id=str(portfolio.portfolio_id),
        portfolio_name=portfolio.portfolio_name,
        total_value=format_currency(valuation.total_value, valuation.currency),
        cash_value=format_currency(valuation.cash_value, valuation.currency),
        invested_value=format_currency(valuation.invested_value, valuation.currency),
        positions=positions,
    )


def _benchmark_panel(portfolio: Portfolio, valuation: PortfolioValuation) -> BenchmarkPanel:
    spy_position = portfolio.positions[0] if portfolio.positions else None
    spy_valuation = valuation.position_valuations[0] if valuation.position_valuations else None
    return BenchmarkPanel(
        total_value=format_currency(valuation.total_value, valuation.currency),
        cash_value=format_currency(valuation.cash_value, valuation.currency),
        spy_quantity=None if spy_position is None else format_decimal(spy_position.quantity),
        spy_value=None if spy_valuation is None else format_currency(spy_valuation.market_value, valuation.currency),
    )


def _comparison_panel(comparison: PerformanceComparison) -> ComparisonPanel:
    return ComparisonPanel(
        managed_cumulative_return=format_percent(comparison.managed_cumulative_return),
        benchmark_cumulative_return=format_percent(comparison.benchmark_cumulative_return),
        absolute_alpha=format_percent(comparison.absolute_alpha),
        relative_alpha=format_percent(comparison.relative_alpha),
    )


def _decision_panel(
    *,
    journal_entry: DecisionJournalEntry | None = None,
    approval: DecisionApproval | None = None,
) -> LatestDecisionPanel | None:
    if journal_entry is None and approval is None:
        return None
    source = approval.journal_entry if approval is not None else journal_entry
    assert source is not None
    recommendation = source.decision_result.recommendation
    reviewer_decision = None
    if source.reviewer_result is not None:
        reviewer_decision = source.reviewer_result.decision.value
    human_approval_status = None if approval is None else approval.decision.value
    target_weight = None if recommendation.target_weight is None else format_percent(recommendation.target_weight)
    confidence = f"{recommendation.confidence_score}/100"
    return LatestDecisionPanel(
        manager_action=recommendation.action.value,
        ticker=recommendation.ticker,
        target_weight=target_weight,
        confidence=confidence,
        reviewer_decision=reviewer_decision,
        human_approval_status=human_approval_status,
    )


def build_dashboard_view(
    *,
    managed_history: PortfolioPerformanceHistory,
    benchmark_history: BenchmarkPerformanceHistory,
    comparison: PerformanceComparison,
    journal_entry: DecisionJournalEntry | None = None,
    approval: DecisionApproval | None = None,
) -> DashboardView:
    """Transform immutable domain objects into a compact dashboard view model."""
    if not managed_history.snapshots:
        raise ValueError("managed_history must contain at least one snapshot")
    if not benchmark_history.snapshots:
        raise ValueError("benchmark_history must contain at least one snapshot")
    managed_snapshot = managed_history.snapshots[-1]
    benchmark_snapshot = benchmark_history.snapshots[-1]
    managed_panel = _portfolio_panel(managed_snapshot.portfolio, managed_snapshot.valuation)
    benchmark_panel = _benchmark_panel(benchmark_snapshot.portfolio, benchmark_snapshot.valuation)
    comparison_panel = _comparison_panel(comparison)
    decision_panel = _decision_panel(journal_entry=journal_entry, approval=approval)
    return DashboardView(
        managed=managed_panel,
        benchmark=benchmark_panel,
        comparison=comparison_panel,
        latest_decision=decision_panel,
    )


def _write_position_rows(rows: Iterable[PositionRow]) -> list[dict[str, str | None]]:
    return [
        {
            "Ticker": row.ticker,
            "Quantity": row.quantity,
            "Market Value": row.market_value,
            "Weight": row.portfolio_weight,
            "Cost Basis": row.total_cost_basis,
            "Avg Cost": row.average_cost_basis,
            "Unrealized P&L": row.unrealized_pnl,
        }
        for row in rows
    ]


def render_streamlit_dashboard(view: DashboardView) -> None:
    """Render a compact dashboard with lazy Streamlit import."""
    import streamlit as st

    st.set_page_config(page_title="Agentic Portfolio Lab", layout="wide")
    st.title("Agentic Portfolio Lab")
    st.caption("Deterministic portfolio state, benchmark tracking, and decision summary.")

    left, right = st.columns(2)
    with left:
        st.subheader("Managed Portfolio")
        st.metric("Portfolio", f"{view.managed.portfolio_name} ({view.managed.portfolio_id})")
        st.metric("Total Value", view.managed.total_value)
        st.metric("Cash", view.managed.cash_value)
        st.metric("Invested Value", view.managed.invested_value)
        st.table(_write_position_rows(view.managed.positions) if view.managed.positions else [{"Ticker": "No positions", "Quantity": "", "Market Value": "", "Weight": "", "Cost Basis": "", "Avg Cost": "", "Unrealized P&L": ""}])

    with right:
        st.subheader("Passive Benchmark")
        st.metric("Benchmark Total Value", view.benchmark.total_value)
        st.metric("Benchmark Cash", view.benchmark.cash_value)
        st.metric("SPY Quantity", view.benchmark.spy_quantity or "0")
        st.metric("SPY Value", view.benchmark.spy_value or view.benchmark.cash_value)

    st.subheader("Comparison")
    comparison_cols = st.columns(4)
    comparison_cols[0].metric("Managed Return", view.comparison.managed_cumulative_return)
    comparison_cols[1].metric("Benchmark Return", view.comparison.benchmark_cumulative_return)
    comparison_cols[2].metric("Absolute Alpha", view.comparison.absolute_alpha)
    comparison_cols[3].metric("Relative Alpha", view.comparison.relative_alpha)

    if view.latest_decision is not None:
        st.subheader("Latest Decision")
        decision_cols = st.columns(5)
        decision_cols[0].metric("Action", view.latest_decision.manager_action)
        decision_cols[1].metric("Ticker", view.latest_decision.ticker or "HOLD")
        decision_cols[2].metric("Target Weight", view.latest_decision.target_weight or "n/a")
        decision_cols[3].metric("Confidence", view.latest_decision.confidence)
        decision_cols[4].metric("Reviewer", view.latest_decision.reviewer_decision or "n/a")
        approval_status = view.latest_decision.human_approval_status
        if approval_status is not None:
            st.caption(f"Human approval: {approval_status}")
