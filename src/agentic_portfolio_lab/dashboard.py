"""Presentation-only dashboard models and rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Context, Decimal, MAX_EMAX, MAX_PREC, MIN_EMIN, ROUND_HALF_UP, localcontext
from typing import Iterable

from .domain.approval import DecisionApproval
from .domain.journal import DecisionJournalEntry
from .domain.performance import BenchmarkPerformanceHistory, PerformanceComparison, PortfolioPerformanceHistory
from .domain.portfolio import Portfolio, Position, SecurityIdentity
from .domain.recommendations import PortfolioRecommendation
from .domain.research import MissingData, ResearchBatch, ResearchPacket, ResearchSection
from .domain.risk_validation import RiskRuleResult
from .domain.reviewer import ReviewFinding
from .domain.valuation import PortfolioValuation, PositionValuation

_PRESENTATION_DECIMAL_CONTEXT = Context(prec=MAX_PREC, Emax=MAX_EMAX, Emin=MIN_EMIN)
DASHBOARD_TAB_LABELS = ("Overview", "Holdings", "Performance", "Decision Memo", "Research")


def format_decimal(value: Decimal, *, places: int | None = None) -> str:
    """Format a Decimal for display without mutating or recalculating it."""
    with localcontext(_PRESENTATION_DECIMAL_CONTEXT):
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
    with localcontext(_PRESENTATION_DECIMAL_CONTEXT):
        percentage = value * Decimal("100")
    return f"{format_decimal(percentage, places=2)}%"


@dataclass(frozen=True, slots=True)
class PositionRow:
    ticker: str
    quantity: str
    market_value: str
    portfolio_weight: str
    allocation_weight: Decimal
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
class DecisionSummaryPanel:
    action: str
    ticker: str
    target_weight: str
    confidence: str
    constitution_version: str
    decision_cycle_id: str
    decision_timestamp: str


@dataclass(frozen=True, slots=True)
class DecisionNarrativePanel:
    thesis: str | None
    decision_rationale: str
    valuation: str
    why_not_spy: str
    risks: tuple[str, ...]
    thesis_invalidation: tuple[str, ...]
    review_triggers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidencePanel:
    evidence_id: str
    source_type: str
    source_title: str
    source_date: str
    claim_supported: str


@dataclass(frozen=True, slots=True)
class ValidationRulePanel:
    rule_id: str
    status: str
    reason: str
    actual_value: str | None
    allowed_threshold: str | None


@dataclass(frozen=True, slots=True)
class ValidationPanel:
    status: str
    rules: tuple[ValidationRulePanel, ...]


@dataclass(frozen=True, slots=True)
class ReviewerFindingPanel:
    severity: str
    category: str
    message: str
    related_evidence_ids: tuple[str, ...]
    related_recommendation_field: str | None


@dataclass(frozen=True, slots=True)
class ReviewerPanel:
    decision: str | None
    findings: tuple[ReviewerFindingPanel, ...]
    reviewed_at: str | None


@dataclass(frozen=True, slots=True)
class ApprovalPanel:
    decision: str | None
    decision_maker_id: str | None
    decided_at: str | None
    comment: str | None


@dataclass(frozen=True, slots=True)
class LatestDecisionPanel:
    summary: DecisionSummaryPanel
    narrative: DecisionNarrativePanel
    evidence: tuple[EvidencePanel, ...]
    validation: ValidationPanel
    reviewer: ReviewerPanel
    approval: ApprovalPanel


@dataclass(frozen=True, slots=True)
class MissingDataPanel:
    field_name: str
    reason: str
    details: str | None


@dataclass(frozen=True, slots=True)
class ResearchSectionPanel:
    section_id: str
    content: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResearchEvidencePanel:
    evidence_id: str
    source_type: str
    source_title: str
    source_date: str
    claim_supported: str
    cited_by_decision: bool
    referenced_by_reviewer: bool


@dataclass(frozen=True, slots=True)
class ResearchPacketPanel:
    packet_id: str
    candidate_id: str
    selector_label: str
    ticker: str
    company_name: str | None
    security_type: str
    exchange: str | None
    currency: str | None
    as_of_timestamp: str
    sections: tuple[ResearchSectionPanel, ...]
    evidence: tuple[ResearchEvidencePanel, ...]
    missing_data: tuple[MissingDataPanel, ...]


@dataclass(frozen=True, slots=True)
class ResearchBatchPanel:
    batch_id: str
    decision_cycle_id: str
    manager_type: str
    created_at: str
    as_of_timestamp: str
    candidate_count: int
    packets: tuple[ResearchPacketPanel, ...]


@dataclass(frozen=True, slots=True)
class DashboardView:
    managed: PortfolioPanel
    benchmark: BenchmarkPanel
    comparison: ComparisonPanel
    latest_decision: LatestDecisionPanel | None = None
    research: ResearchBatchPanel | None = None


def _format_position_row(
    position: Position,
    *,
    market_value: Decimal,
    weight: Decimal,
    unrealized_pnl: Decimal,
) -> PositionRow:
    return PositionRow(
        ticker=position.security.ticker,
        quantity=format_decimal(position.quantity),
        market_value=format_currency(market_value, position.security.currency),
        portfolio_weight=format_percent(weight),
        allocation_weight=weight,
        total_cost_basis=format_currency(position.total_cost_basis, position.security.currency),
        average_cost_basis=format_currency(position.average_cost_basis, position.security.currency),
        unrealized_pnl=format_currency(unrealized_pnl, position.security.currency),
    )


def _portfolio_panel(portfolio: Portfolio, valuation: PortfolioValuation) -> PortfolioPanel:
    weights = {security: weight for security, weight in valuation.position_weights}
    valuations_by_security: dict[SecurityIdentity, PositionValuation] = {}
    for position_valuation in valuation.position_valuations:
        if position_valuation.security in valuations_by_security:
            raise ValueError("valuation contains ambiguous position security identity")
        valuations_by_security[position_valuation.security] = position_valuation
    if set(valuations_by_security) != {position.security for position in portfolio.positions}:
        raise ValueError("valuation position securities must match portfolio positions")
    positions = tuple(
        _format_position_row(
            position,
            market_value=valuations_by_security[position.security].market_value,
            weight=weights[position.security],
            unrealized_pnl=valuations_by_security[position.security].unrealized_gain_loss,
        )
        for position in portfolio.positions
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
    spy_position = next((position for position in portfolio.positions if position.security.ticker == "SPY"), None)
    spy_valuation = next(
        (position_valuation for position_valuation in valuation.position_valuations if position_valuation.security.ticker == "SPY"),
        None,
    )
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


def _format_datetime(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _format_ticker(recommendation: PortfolioRecommendation) -> str:
    return recommendation.ticker if recommendation.ticker is not None else "n/a"


def _format_target_weight(recommendation: PortfolioRecommendation) -> str:
    return "n/a" if recommendation.target_weight is None else format_percent(recommendation.target_weight)


def _format_validation_rule(rule: RiskRuleResult) -> ValidationRulePanel:
    actual_value = None if rule.actual_value is None else format_decimal(rule.actual_value) if isinstance(rule.actual_value, Decimal) else str(rule.actual_value)
    allowed_threshold = None if rule.allowed_threshold is None else format_decimal(rule.allowed_threshold) if isinstance(rule.allowed_threshold, Decimal) else str(rule.allowed_threshold)
    return ValidationRulePanel(
        rule_id=rule.rule_id,
        status=rule.status.value,
        reason=rule.reason,
        actual_value=actual_value,
        allowed_threshold=allowed_threshold,
    )


def _format_finding(finding: ReviewFinding) -> ReviewerFindingPanel:
    return ReviewerFindingPanel(
        severity=finding.severity.value,
        category=finding.category.value,
        message=finding.message,
        related_evidence_ids=finding.related_evidence_ids,
        related_recommendation_field=finding.related_recommendation_field,
    )


def _format_evidence(reference) -> EvidencePanel:
    return EvidencePanel(
        evidence_id=reference.evidence_id,
        source_type=reference.source_type,
        source_title=reference.source_title,
        source_date=reference.source_date.isoformat(),
        claim_supported=reference.claim_supported,
    )


def _missing_data_panel(field_name: str, value: MissingData) -> MissingDataPanel:
    return MissingDataPanel(field_name=field_name, reason=value.reason.value, details=value.details)


def _research_value(value: str | MissingData, *, field_name: str) -> tuple[str | None, MissingDataPanel | None]:
    if isinstance(value, MissingData):
        return None, _missing_data_panel(field_name, value)
    return value, None


def _research_section_panel(section: ResearchSection) -> tuple[ResearchSectionPanel, MissingDataPanel | None]:
    if isinstance(section.content, MissingData):
        return (
            ResearchSectionPanel(section_id=section.section_id, content=None, evidence_ids=section.evidence_ids),
            _missing_data_panel(f"Section: {section.section_id}", section.content),
        )
    return ResearchSectionPanel(section_id=section.section_id, content=section.content, evidence_ids=section.evidence_ids), None


def _research_packet_panel(
    packet: ResearchPacket,
    *,
    cited_evidence_ids: frozenset[str],
    reviewer_evidence_ids: frozenset[str],
) -> ResearchPacketPanel:
    missing_data: list[MissingDataPanel] = []
    company_name, company_missing = _research_value(packet.company_name, field_name="Company name")
    exchange, exchange_missing = _research_value(packet.exchange, field_name="Exchange")
    currency, currency_missing = _research_value(packet.currency, field_name="Currency")
    _, sector_missing = _research_value(packet.sector, field_name="Sector")
    _, industry_missing = _research_value(packet.industry, field_name="Industry")
    for missing in (company_missing, exchange_missing, currency_missing, sector_missing, industry_missing):
        if missing is not None:
            missing_data.append(missing)
    sections: list[ResearchSectionPanel] = []
    for section in packet.sections:
        section_panel, section_missing = _research_section_panel(section)
        sections.append(section_panel)
        if section_missing is not None:
            missing_data.append(section_missing)
    evidence = tuple(
        ResearchEvidencePanel(
            evidence_id=item.evidence_id,
            source_type=item.source_type,
            source_title=item.source_title,
            source_date=item.source_date.isoformat(),
            claim_supported=item.claim_supported,
            cited_by_decision=item.evidence_id in cited_evidence_ids,
            referenced_by_reviewer=item.evidence_id in reviewer_evidence_ids,
        )
        for item in packet.evidence_items
    )
    selector_label = f"{packet.ticker} — {company_name or 'Company not provided'}"
    return ResearchPacketPanel(
        packet_id=packet.packet_id,
        candidate_id=packet.candidate_id,
        selector_label=selector_label,
        ticker=packet.ticker,
        company_name=company_name,
        security_type=packet.security_type,
        exchange=exchange,
        currency=currency,
        as_of_timestamp=_format_datetime(packet.as_of_timestamp),
        sections=tuple(sections),
        evidence=evidence,
        missing_data=tuple(missing_data),
    )


def _research_batch_panel(
    research_batch: ResearchBatch,
    *,
    journal_entry: DecisionJournalEntry | None,
) -> ResearchBatchPanel:
    cited_evidence_ids = frozenset() if journal_entry is None else frozenset(journal_entry.cited_evidence_ids)
    reviewer_evidence_ids = frozenset() if journal_entry is None else frozenset(journal_entry.reviewer_evidence_ids)
    return ResearchBatchPanel(
        batch_id=research_batch.batch_id,
        decision_cycle_id=str(research_batch.decision_cycle_id),
        manager_type=research_batch.manager_type,
        created_at=_format_datetime(research_batch.created_at),
        as_of_timestamp=_format_datetime(research_batch.as_of_timestamp),
        candidate_count=len(research_batch.packets),
        packets=tuple(
            _research_packet_panel(
                packet,
                cited_evidence_ids=cited_evidence_ids,
                reviewer_evidence_ids=reviewer_evidence_ids,
            )
            for packet in research_batch.packets
        ),
    )


def _decision_panel(
    *,
    journal_entry: DecisionJournalEntry | None = None,
    approval: DecisionApproval | None = None,
) -> LatestDecisionPanel | None:
    if journal_entry is None and approval is None:
        return None
    if journal_entry is not None and approval is not None and approval.journal_entry != journal_entry:
        raise ValueError("approval journal_entry must match supplied journal_entry")
    source = approval.journal_entry if approval is not None else journal_entry
    assert source is not None
    decision_result = source.decision_result
    recommendation = decision_result.recommendation
    risk_validation = source.risk_validation_result
    reviewer_result = source.reviewer_result

    summary = DecisionSummaryPanel(
        action=recommendation.action.value,
        ticker=_format_ticker(recommendation),
        target_weight=_format_target_weight(recommendation),
        confidence=f"{recommendation.confidence_score}/100",
        constitution_version=decision_result.constitution_version,
        decision_cycle_id=str(decision_result.decision_cycle_id),
        decision_timestamp=_format_datetime(decision_result.produced_at),
    )
    narrative = DecisionNarrativePanel(
        thesis=recommendation.investment_thesis,
        decision_rationale=recommendation.decision_rationale,
        valuation=recommendation.valuation,
        why_not_spy=recommendation.why_not_spy,
        risks=recommendation.risks,
        thesis_invalidation=recommendation.thesis_invalidation,
        review_triggers=tuple(trigger.description for trigger in recommendation.review_triggers),
    )
    validation = ValidationPanel(
        status=risk_validation.status.value,
        rules=tuple(_format_validation_rule(rule) for rule in risk_validation.rule_results),
    )
    reviewer = ReviewerPanel(
        decision=None if reviewer_result is None else reviewer_result.decision.value,
        findings=() if reviewer_result is None else tuple(_format_finding(finding) for finding in reviewer_result.findings),
        reviewed_at=None if reviewer_result is None else _format_datetime(reviewer_result.reviewed_at),
    )
    approval_panel = ApprovalPanel(
        decision=None if approval is None else approval.decision.value,
        decision_maker_id=None if approval is None else approval.decision_maker_id,
        decided_at=None if approval is None else _format_datetime(approval.decided_at),
        comment=None if approval is None else approval.comment,
    )
    return LatestDecisionPanel(
        summary=summary,
        narrative=narrative,
        evidence=tuple(_format_evidence(reference) for reference in recommendation.evidence),
        validation=validation,
        reviewer=reviewer,
        approval=approval_panel,
    )


def build_dashboard_view(
    *,
    managed_history: PortfolioPerformanceHistory,
    benchmark_history: BenchmarkPerformanceHistory,
    comparison: PerformanceComparison | None = None,
    journal_entry: DecisionJournalEntry | None = None,
    approval: DecisionApproval | None = None,
    research_batch: ResearchBatch | None = None,
) -> DashboardView:
    """Transform immutable domain objects into a compact dashboard view model."""
    if not managed_history.snapshots:
        raise ValueError("managed_history must contain at least one snapshot")
    if not benchmark_history.snapshots:
        raise ValueError("benchmark_history must contain at least one snapshot")
    managed_snapshot = managed_history.snapshots[-1]
    benchmark_snapshot = benchmark_history.snapshots[-1]
    derived_comparison = PerformanceComparison(managed_history, benchmark_history)
    if comparison is not None and (
        comparison.managed_history is not managed_history or comparison.benchmark_history is not benchmark_history
    ):
        raise ValueError("comparison histories must match the displayed histories")
    managed_panel = _portfolio_panel(managed_snapshot.portfolio, managed_snapshot.valuation)
    benchmark_panel = _benchmark_panel(benchmark_snapshot.portfolio, benchmark_snapshot.valuation)
    comparison_panel = _comparison_panel(derived_comparison)
    decision_panel = _decision_panel(journal_entry=journal_entry, approval=approval)
    journal_source = approval.journal_entry if approval is not None else journal_entry
    if journal_source is not None:
        authoritative_research_batch = journal_source.decision_result.context.research_batch
        if research_batch is not None and research_batch is not authoritative_research_batch:
            raise ValueError("research_batch must be the journal entry's authoritative ResearchBatch")
    else:
        authoritative_research_batch = research_batch
    return DashboardView(
        managed=managed_panel,
        benchmark=benchmark_panel,
        comparison=comparison_panel,
        latest_decision=decision_panel,
        research=None
        if authoritative_research_batch is None
        else _research_batch_panel(authoritative_research_batch, journal_entry=journal_source),
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


def _semantic_color(label: str) -> str:
    if label in {"BUY", "APPROVED", "PASSED", "APPROVE"}:
        return "normal"
    if label in {"HOLD"}:
        return "off"
    if label in {"REQUEST_CHANGES", "FAILED"}:
        return "inverse"
    if label in {"REJECTED", "CRITICAL", "EXPIRED"}:
        return "inverse"
    return "off"


def _portfolio_heading(panel: PortfolioPanel) -> str:
    """Keep the human portfolio name, not its technical UUID, in the primary label."""
    return panel.portfolio_name


def _metric_delta(value: str) -> tuple[str, str]:
    """Classify a formatted signed value for Streamlit's presentation color only."""
    if value.startswith("-"):
        return "Negative", "inverse"
    if value.startswith("0"):
        return "Neutral", "off"
    return "Positive", "normal"


def _allocation_chart_data(rows: Iterable[PositionRow]) -> dict[str, Decimal]:
    """Expose the valuation-provided allocation weights without recalculation."""
    return {row.ticker: row.allocation_weight for row in rows}


def render_streamlit_dashboard(view: DashboardView) -> None:
    """Render a compact dashboard with lazy Streamlit import."""
    import streamlit as st

    st.set_page_config(page_title="Agentic Portfolio Lab", layout="wide")
    st.markdown(
        "<style>div[data-testid='stMetric'] {border-left: 3px solid #4f8bf9; padding-left: 0.6rem;}</style>",
        unsafe_allow_html=True,
    )
    st.title("Agentic Portfolio Lab — Demo")
    st.caption("Demo mode — synthetic in-memory data; nothing shown here is persisted.")

    summary_cols = st.columns(4)
    summary_cols[0].metric("Managed Portfolio Value", view.managed.total_value)
    summary_cols[1].metric("SPY Benchmark Value", view.benchmark.total_value)
    alpha_delta, alpha_color = _metric_delta(view.comparison.absolute_alpha)
    summary_cols[2].metric("Absolute Alpha", view.comparison.absolute_alpha, delta=alpha_delta, delta_color=alpha_color)
    summary_cols[3].metric("Cash", view.managed.cash_value)

    overview_tab, holdings_tab, performance_tab, decision_tab, research_tab = st.tabs(DASHBOARD_TAB_LABELS)

    with overview_tab:
        st.subheader("Portfolio Overview")
        left, right = st.columns(2)
        with left:
            st.subheader("Managed Portfolio")
            st.metric("Portfolio", _portfolio_heading(view.managed))
            st.caption(f"Portfolio ID: {view.managed.portfolio_id}")
            st.metric("Invested Value", view.managed.invested_value)

        with right:
            st.subheader("Passive Benchmark")
            st.metric("Benchmark Total Value", view.benchmark.total_value)
            st.metric("Benchmark Cash", view.benchmark.cash_value)
            st.metric("SPY Quantity", view.benchmark.spy_quantity or "0")
            st.metric("SPY Value", view.benchmark.spy_value or "Not held")

    with holdings_tab:
        st.subheader("Holdings")
        st.table(
            _write_position_rows(view.managed.positions)
            if view.managed.positions
            else [{"Ticker": "No positions", "Quantity": "", "Market Value": "", "Weight": "", "Cost Basis": "", "Avg Cost": "", "Unrealized P&L": ""}]
        )
        if view.managed.positions:
            st.caption("Allocation by existing valuation weight")
            st.bar_chart(_allocation_chart_data(view.managed.positions))

    with performance_tab:
        st.subheader("Performance")
        comparison_cols = st.columns(4)
        for column, label, value in zip(
            comparison_cols,
            ("Managed Return", "Benchmark Return", "Absolute Alpha", "Relative Alpha"),
            (
                view.comparison.managed_cumulative_return,
                view.comparison.benchmark_cumulative_return,
                view.comparison.absolute_alpha,
                view.comparison.relative_alpha,
            ),
            strict=True,
        ):
            delta, delta_color = _metric_delta(value)
            column.metric(label, value, delta=delta, delta_color=delta_color)

    with decision_tab:
        st.subheader("Decision Memo")
        if view.latest_decision is None:
            st.write("No journaled decision is available.")
        else:
            st.caption("Synthetic, in-memory, read-only decision memo.")
            summary = view.latest_decision.summary
            summary_cols = st.columns(4)
            summary_cols[0].metric("Action", summary.action, delta_color=_semantic_color(summary.action))
            summary_cols[1].metric("Ticker", summary.ticker)
            summary_cols[2].metric("Target Weight", summary.target_weight)
            summary_cols[3].metric("Confidence", summary.confidence)
            meta_cols = st.columns(3)
            meta_cols[0].metric("Constitution", summary.constitution_version)
            meta_cols[1].metric("Decision Cycle", summary.decision_cycle_id)
            meta_cols[2].metric("Timestamp", summary.decision_timestamp)

            st.divider()
            st.subheader("Investment Thesis")
            st.write(f"**Thesis:** {view.latest_decision.narrative.thesis or 'Not provided'}")
            st.write(f"**Rationale:** {view.latest_decision.narrative.decision_rationale}")
            st.write(f"**Valuation:** {view.latest_decision.narrative.valuation}")
            st.write(f"**Why not SPY:** {view.latest_decision.narrative.why_not_spy}")

            st.divider()
            st.subheader("Risks")
            st.write("Risk items:")
            for item in view.latest_decision.narrative.risks:
                st.write(f"- {item}")
            if view.latest_decision.narrative.thesis_invalidation:
                with st.expander("Thesis invalidation conditions", expanded=False):
                    for item in view.latest_decision.narrative.thesis_invalidation:
                        st.write(f"- {item}")
            if view.latest_decision.narrative.review_triggers:
                with st.expander("Review triggers", expanded=False):
                    for item in view.latest_decision.narrative.review_triggers:
                        st.write(f"- {item}")

            st.divider()
            st.subheader("Evidence")
            for evidence in view.latest_decision.evidence:
                with st.expander(f"{evidence.evidence_id}: {evidence.source_title}", expanded=False):
                    st.write(f"Source type: {evidence.source_type}")
                    st.write(f"Source date: {evidence.source_date}")
                    st.write(f"Claim supported: {evidence.claim_supported}")

            st.divider()
            st.subheader("Deterministic Validation")
            st.metric("Overall Status", view.latest_decision.validation.status, delta_color=_semantic_color(view.latest_decision.validation.status))
            for rule in view.latest_decision.validation.rules:
                with st.expander(rule.rule_id, expanded=False):
                    st.write(f"Status: {rule.status}")
                    st.write(f"Reason: {rule.reason}")
                    st.write(f"Actual value: {rule.actual_value or 'n/a'}")
                    st.write(f"Allowed threshold: {rule.allowed_threshold or 'n/a'}")

            st.divider()
            st.subheader("AI Reviewer")
            if view.latest_decision.reviewer.decision is None:
                st.write("Not reviewed")
            else:
                st.metric("Reviewer Decision", view.latest_decision.reviewer.decision, delta_color=_semantic_color(view.latest_decision.reviewer.decision))
                st.write(f"Reviewed at: {view.latest_decision.reviewer.reviewed_at}")
                if view.latest_decision.reviewer.findings:
                    for finding in view.latest_decision.reviewer.findings:
                        with st.expander(f"{finding.severity} - {finding.category}", expanded=False):
                            st.write(finding.message)
                            if finding.related_evidence_ids:
                                st.write(f"Related evidence: {', '.join(finding.related_evidence_ids)}")
                            if finding.related_recommendation_field is not None:
                                st.write(f"Related recommendation field: {finding.related_recommendation_field}")
                else:
                    st.write("No findings")

            st.divider()
            st.subheader("Human Approval")
            if view.latest_decision.approval.decision is None:
                st.write("Awaiting human decision")
            else:
                st.metric("Approval", view.latest_decision.approval.decision, delta_color=_semantic_color(view.latest_decision.approval.decision))
                st.write(f"Approver: {view.latest_decision.approval.decision_maker_id}")
                st.write(f"Timestamp: {view.latest_decision.approval.decided_at}")
                if view.latest_decision.approval.comment is not None:
                    st.write(f"Comment: {view.latest_decision.approval.comment}")

    with research_tab:
        st.subheader("Research")
        if view.research is None:
            st.write("No research batch is available.")
        else:
            research = view.research
            st.caption("Synthetic, in-memory, read-only research inputs.")
            st.markdown("#### Batch Summary")
            batch_cols = st.columns(4)
            batch_cols[0].metric("Manager Type", research.manager_type)
            batch_cols[1].metric("As of", research.as_of_timestamp)
            batch_cols[2].metric("Created", research.created_at)
            batch_cols[3].metric("Candidates", str(research.candidate_count))
            st.caption(f"Decision cycle: {research.decision_cycle_id} · Batch ID: {research.batch_id}")

            st.divider()
            st.markdown("#### Candidate Selector")
            packets_by_candidate_id = {packet.candidate_id: packet for packet in research.packets}
            selected_candidate_id = st.selectbox(
                "Candidate",
                options=tuple(packets_by_candidate_id),
                format_func=lambda candidate_id: packets_by_candidate_id[candidate_id].selector_label,
                key="research_candidate_id",
            )
            packet = packets_by_candidate_id[selected_candidate_id]

            st.divider()
            st.markdown("#### Security")
            security_cols = st.columns(4)
            security_cols[0].metric("Ticker", packet.ticker)
            security_cols[1].metric("Security Type", packet.security_type)
            security_cols[2].metric("Exchange", packet.exchange or "Not provided")
            security_cols[3].metric("Currency", packet.currency or "Not provided")
            st.caption(
                f"Packet ID: {packet.packet_id} · Candidate ID: {packet.candidate_id} · "
                f"Packet as of: {packet.as_of_timestamp}"
            )

            st.divider()
            st.markdown("#### Research Sections")
            for section in packet.sections:
                with st.expander(section.section_id.replace("_", " ").title(), expanded=False):
                    st.write(section.content or "Not provided")
                    if section.evidence_ids:
                        st.caption(f"Evidence IDs: {', '.join(section.evidence_ids)}")

            st.divider()
            st.markdown("#### Evidence")
            for evidence in packet.evidence:
                badges = []
                if evidence.cited_by_decision:
                    badges.append("Cited by decision")
                if evidence.referenced_by_reviewer:
                    badges.append("Referenced by reviewer")
                badge_text = " · ".join(badges)
                with st.expander(f"{evidence.evidence_id}: {evidence.source_title}", expanded=False):
                    if badge_text:
                        st.caption(badge_text)
                    st.write(f"Source type: {evidence.source_type}")
                    st.write(f"Source date: {evidence.source_date}")
                    st.write(f"Claim supported: {evidence.claim_supported}")

            st.divider()
            st.markdown("#### Missing Data")
            if not packet.missing_data:
                st.write("No missing data was supplied for this packet.")
            else:
                for missing in packet.missing_data:
                    details = f" — {missing.details}" if missing.details is not None else ""
                    st.warning(f"{missing.field_name}: {missing.reason}{details}")
