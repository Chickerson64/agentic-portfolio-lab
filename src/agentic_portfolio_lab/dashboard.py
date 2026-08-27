"""Presentation-only dashboard models and rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Context, Decimal, MAX_EMAX, MAX_PREC, MIN_EMIN, ROUND_HALF_UP, localcontext
from typing import Iterable
from uuid import UUID

from .domain.approval import DecisionApproval
from .domain.journal import DecisionJournalEntry
from .domain.performance import (
    BenchmarkPerformanceHistory,
    PerformanceComparison,
    PerformanceSnapshot,
    PortfolioPerformanceHistory,
)
from .domain.portfolio import Portfolio, Position, SecurityIdentity
from .domain.recommendations import PortfolioRecommendation
from .domain.research import MissingData, ResearchBatch, ResearchPacket, ResearchSection
from .domain.risk_validation import RiskRuleResult
from .domain.reviewer import ReviewFinding, ReviewerResult
from .domain.trades import ExecutedTrade
from .domain.valuation import PortfolioValuation, PositionValuation

_PRESENTATION_DECIMAL_CONTEXT = Context(prec=MAX_PREC, Emax=MAX_EMAX, Emin=MIN_EMIN)
DASHBOARD_TAB_LABELS = ("Overview", "Holdings", "Performance", "Decision Memo", "Research", "History")


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
class DecisionHistoryArtifacts:
    """Read-only source artifacts for one history entry.

    This is a presentation input, not a domain journal or execution record.
    """

    journal_entry: DecisionJournalEntry
    approval: DecisionApproval | None = None
    executed_trade: ExecutedTrade | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.journal_entry, DecisionJournalEntry):
            raise TypeError("journal_entry must be a DecisionJournalEntry")
        if self.approval is not None and self.approval.journal_entry is not self.journal_entry:
            raise ValueError("approval must reference the history entry journal_entry")
        if self.executed_trade is not None:
            if not isinstance(self.executed_trade, ExecutedTrade):
                raise TypeError("executed_trade must be an ExecutedTrade or None")
            if self.journal_entry.decision_result.recommendation.action.value == "HOLD":
                raise ValueError("HOLD history entries must not include an executed_trade")
            if self.executed_trade.decision_cycle_id != self.journal_entry.decision_cycle_id:
                raise ValueError("executed_trade decision_cycle_id must match history entry")
            if self.executed_trade.portfolio_id != self.journal_entry.portfolio_id:
                raise ValueError("executed_trade portfolio_id must match history entry")
            authoritative_validated_trade = self.journal_entry.risk_validation_result.validated_trade
            if self.executed_trade.validated_trade is not authoritative_validated_trade:
                raise ValueError("executed_trade must descend from the journal's authoritative validated_trade")

    @property
    def history_entry_id(self) -> UUID:
        """Use the immutable journal decision-cycle identity as the selector key."""
        return self.journal_entry.decision_cycle_id


@dataclass(frozen=True, slots=True)
class HistoryContributionPanel:
    timestamp: str
    amount: str
    source: str


@dataclass(frozen=True, slots=True)
class HistoryExecutionPanel:
    status: str
    execution_price: str | None
    quantity: str | None
    notional: str | None
    executed_at: str | None


@dataclass(frozen=True, slots=True)
class HistorySnapshotPanel:
    timestamp: str
    portfolio_value: str
    cash_value: str
    positions_value: str
    managed_return: str
    benchmark_return: str
    absolute_alpha: str


@dataclass(frozen=True, slots=True)
class HistoryEntryPanel:
    history_entry_id: str
    selector_label: str
    decision_timestamp_at: datetime
    decision_timestamp: str
    action: str
    ticker: str
    target_weight: str
    reviewer_outcome: str
    approval_outcome: str
    research_batch_id: str
    research_packet_id: str | None
    execution: HistoryExecutionPanel
    snapshot: HistorySnapshotPanel | None
    contributions: tuple[HistoryContributionPanel, ...]


@dataclass(frozen=True, slots=True)
class HistoryChartPoint:
    timestamp_at: datetime
    timestamp: str
    portfolio_value: Decimal
    managed_return: Decimal
    benchmark_return: Decimal
    absolute_alpha: Decimal


@dataclass(frozen=True, slots=True)
class HistoryPanel:
    entries_newest_first: tuple[HistoryEntryPanel, ...]
    chart_points_oldest_first: tuple[HistoryChartPoint, ...]


@dataclass(frozen=True, slots=True)
class DashboardView:
    managed: PortfolioPanel
    benchmark: BenchmarkPanel
    comparison: ComparisonPanel | None
    latest_decision: LatestDecisionPanel | None = None
    research: ResearchBatchPanel | None = None
    history: HistoryPanel | None = None


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


def _datetime_instant(value: datetime) -> datetime:
    """Normalize an aware datetime for absolute chronological ordering."""
    return value.astimezone(timezone.utc)


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


def _snapshot_index_for_decision_cycle(
    history: PortfolioPerformanceHistory,
    *,
    journal_entry: DecisionJournalEntry,
    executed_trade: ExecutedTrade | None = None,
) -> int | None:
    """Return the first lifecycle-eligible managed snapshot for one decision.

    A portfolio retains its latest decision-cycle identity across later
    mark-to-market valuations.  Those valuations are not separate decision
    outcomes, so this helper deliberately selects the first snapshot at or
    after the relevant lifecycle event rather than requiring a one-to-one
    cycle-to-snapshot relationship.
    """
    if journal_entry.portfolio_id != history.portfolio_id:
        raise ValueError("history entry journal portfolio_id must match managed performance history")
    lifecycle_at = journal_entry.journaled_at if executed_trade is None else executed_trade.executed_at
    matching_indexes = tuple(
        index
        for index, snapshot in enumerate(history.snapshots)
        if snapshot.portfolio.decision_cycle_id == journal_entry.decision_cycle_id
        and snapshot.timestamp >= lifecycle_at
    )
    if not matching_indexes:
        return None
    snapshot_index = matching_indexes[0]
    snapshot = history.snapshots[snapshot_index]
    _validate_history_snapshot_lineage(snapshot, journal_entry=journal_entry)
    return snapshot_index


def _synchronized_snapshot_pair_for_decision_cycle(
    managed_history: PortfolioPerformanceHistory,
    benchmark_history: BenchmarkPerformanceHistory,
    *,
    journal_entry: DecisionJournalEntry,
    executed_trade: ExecutedTrade | None,
) -> tuple[int, int] | None:
    """Return the first synchronized valuation pair after a decision event.

    Managed execution is intentionally allowed to be unpaired.  A historical
    performance attachment therefore starts at the first later synchronized
    mark-to-market pair, never at an arbitrary later valuation.
    """
    managed_index = _snapshot_index_for_decision_cycle(
        managed_history, journal_entry=journal_entry, executed_trade=executed_trade,
    )
    if managed_index is None:
        return None
    for index in range(managed_index, len(managed_history.snapshots)):
        managed_snapshot = managed_history.snapshots[index]
        if managed_snapshot.portfolio.decision_cycle_id != journal_entry.decision_cycle_id:
            continue
        benchmark_indexes = tuple(
            benchmark_index
            for benchmark_index, benchmark_snapshot in enumerate(benchmark_history.snapshots)
            if benchmark_snapshot.timestamp == managed_snapshot.timestamp
        )
        if len(benchmark_indexes) > 1:
            raise ValueError("a synchronized managed snapshot must not match multiple benchmark snapshots")
        if benchmark_indexes:
            _validate_history_snapshot_chronology(
                managed_snapshot, journal_entry=journal_entry, executed_trade=executed_trade,
            )
            return index, benchmark_indexes[0]
    return None


def _synchronized_snapshot_pairs(
    managed_history: PortfolioPerformanceHistory,
    benchmark_history: BenchmarkPerformanceHistory,
) -> tuple[tuple[int, int], ...]:
    """Return every unique timestamp pair in append-only history order."""
    pairs: list[tuple[int, int]] = []
    for managed_index, managed_snapshot in enumerate(managed_history.snapshots):
        benchmark_indexes = tuple(
            benchmark_index
            for benchmark_index, benchmark_snapshot in enumerate(benchmark_history.snapshots)
            if benchmark_snapshot.timestamp == managed_snapshot.timestamp
        )
        if len(benchmark_indexes) > 1:
            raise ValueError("a synchronized managed snapshot must not match multiple benchmark snapshots")
        if benchmark_indexes:
            pairs.append((managed_index, benchmark_indexes[0]))
    return tuple(pairs)


def _validate_history_snapshot_lineage(
    snapshot: PerformanceSnapshot,
    *,
    journal_entry: DecisionJournalEntry,
) -> None:
    if snapshot.portfolio.portfolio_id != journal_entry.portfolio_id:
        raise ValueError("matched performance snapshot portfolio_id must match history entry journal")
    if snapshot.portfolio.decision_cycle_id != journal_entry.decision_cycle_id:
        raise ValueError("matched performance snapshot decision_cycle_id must match history entry journal")


def _validate_history_snapshot_chronology(
    snapshot: PerformanceSnapshot,
    *,
    journal_entry: DecisionJournalEntry,
    executed_trade: ExecutedTrade | None,
) -> None:
    if snapshot.timestamp < journal_entry.journaled_at:
        raise ValueError("matched performance snapshot must not predate journaled decision state")
    if executed_trade is not None and snapshot.timestamp < executed_trade.executed_at:
        raise ValueError("post-execution performance snapshot must not predate execution")


def _history_execution_panel(executed_trade: ExecutedTrade | None, *, action: str) -> HistoryExecutionPanel:
    if executed_trade is None:
        status = "No execution — HOLD" if action == "HOLD" else "No execution recorded"
        return HistoryExecutionPanel(status, None, None, None, None)
    return HistoryExecutionPanel(
        status="Simulated execution",
        execution_price=format_currency(executed_trade.execution_price, executed_trade.currency),
        quantity=format_decimal(executed_trade.executed_quantity),
        notional=format_currency(executed_trade.executed_notional, executed_trade.currency),
        executed_at=_format_datetime(executed_trade.executed_at),
    )


def _history_snapshot_panel(
    managed_snapshot: PerformanceSnapshot,
    benchmark_snapshot: PerformanceSnapshot,
    comparison: PerformanceComparison,
) -> HistorySnapshotPanel:
    return HistorySnapshotPanel(
        timestamp=_format_datetime(managed_snapshot.timestamp),
        portfolio_value=format_currency(managed_snapshot.portfolio_value, managed_snapshot.valuation.currency),
        cash_value=format_currency(managed_snapshot.cash_value, managed_snapshot.valuation.currency),
        positions_value=format_currency(managed_snapshot.positions_value, managed_snapshot.valuation.currency),
        managed_return=format_percent(comparison.managed_cumulative_return),
        benchmark_return=format_percent(comparison.benchmark_cumulative_return),
        absolute_alpha=format_percent(comparison.absolute_alpha),
    )


def _history_prefix_comparison(
    managed_history: PortfolioPerformanceHistory,
    benchmark_history: BenchmarkPerformanceHistory,
    *,
    managed_snapshot_index: int,
    benchmark_snapshot_index: int,
) -> PerformanceComparison:
    """Reuse the domain comparison for an existing immutable history prefix."""
    return PerformanceComparison(
        replace(managed_history, snapshots=managed_history.snapshots[: managed_snapshot_index + 1]),
        replace(benchmark_history, snapshots=benchmark_history.snapshots[: benchmark_snapshot_index + 1]),
    )


def _history_entry_panel(
    artifacts: DecisionHistoryArtifacts,
    *,
    managed_history: PortfolioPerformanceHistory,
    benchmark_history: BenchmarkPerformanceHistory,
    comparison_available: bool = True,
    reviewer_result: ReviewerResult | None = None,
) -> HistoryEntryPanel:
    journal_entry = artifacts.journal_entry
    decision_result = journal_entry.decision_result
    recommendation = decision_result.recommendation
    snapshot_pair = _synchronized_snapshot_pair_for_decision_cycle(
        managed_history, benchmark_history, journal_entry=journal_entry, executed_trade=artifacts.executed_trade,
    )
    snapshot = None
    contributions: tuple[HistoryContributionPanel, ...] = ()
    if snapshot_pair is not None and comparison_available:
        managed_snapshot_index, benchmark_snapshot_index = snapshot_pair
        managed_snapshot = managed_history.snapshots[managed_snapshot_index]
        benchmark_snapshot = benchmark_history.snapshots[benchmark_snapshot_index]
        comparison = _history_prefix_comparison(
            managed_history,
            benchmark_history,
            managed_snapshot_index=managed_snapshot_index,
            benchmark_snapshot_index=benchmark_snapshot_index,
        )
        snapshot = _history_snapshot_panel(managed_snapshot, benchmark_snapshot, comparison)
        contributions = tuple(
            HistoryContributionPanel(
                timestamp=_format_datetime(cash_event.effective_at),
                amount=format_currency(cash_event.amount, cash_event.currency),
                source=cash_event.source,
            )
            for cash_event in managed_snapshot.cash_events
        )
    research_batch = decision_result.context.research_batch
    matching_packets = tuple(
        packet for packet in research_batch.packets if packet.ticker == recommendation.ticker
    )
    research_packet_id = matching_packets[0].packet_id if len(matching_packets) == 1 else None
    effective_reviewer = journal_entry.reviewer_result if reviewer_result is None else reviewer_result
    reviewer_outcome = "Not reviewed" if effective_reviewer is None else effective_reviewer.decision.value
    approval_outcome = "No approval recorded" if artifacts.approval is None else artifacts.approval.decision.value
    ticker = _format_ticker(recommendation)
    action = recommendation.action.value
    return HistoryEntryPanel(
        history_entry_id=str(artifacts.history_entry_id),
        selector_label=f"{_format_datetime(decision_result.produced_at)} · {action} {ticker}",
        decision_timestamp_at=decision_result.produced_at,
        decision_timestamp=_format_datetime(decision_result.produced_at),
        action=action,
        ticker=ticker,
        target_weight=_format_target_weight(recommendation),
        reviewer_outcome=reviewer_outcome,
        approval_outcome=approval_outcome,
        research_batch_id=research_batch.batch_id,
        research_packet_id=research_packet_id,
        execution=_history_execution_panel(artifacts.executed_trade, action=action),
        snapshot=snapshot,
        contributions=contributions,
    )


def _newest_first_history_panels(entries: tuple[HistoryEntryPanel, ...]) -> tuple[HistoryEntryPanel, ...]:
    """Order selector rows by their timezone-aware decision instants."""
    return tuple(
        sorted(
            entries,
            key=lambda entry: (_datetime_instant(entry.decision_timestamp_at), entry.history_entry_id),
            reverse=True,
        )
    )


def _history_panel(
    history_entries: tuple[DecisionHistoryArtifacts, ...] | list[DecisionHistoryArtifacts],
    *,
    managed_history: PortfolioPerformanceHistory,
    benchmark_history: BenchmarkPerformanceHistory,
    comparison_available: bool = True,
    reviewer_results: dict[UUID, ReviewerResult] | None = None,
) -> HistoryPanel:
    if not isinstance(history_entries, (tuple, list)):
        raise TypeError("history_entries must be a tuple or list of DecisionHistoryArtifacts")
    entries = tuple(history_entries)
    if not all(isinstance(entry, DecisionHistoryArtifacts) for entry in entries):
        raise TypeError("history_entries must contain DecisionHistoryArtifacts")
    entry_ids = tuple(entry.history_entry_id for entry in entries)
    if len(set(entry_ids)) != len(entry_ids):
        raise ValueError("history_entries must not contain duplicate journal identities")
    panels = tuple(
        _history_entry_panel(
            entry, managed_history=managed_history, benchmark_history=benchmark_history,
            comparison_available=comparison_available,
            reviewer_result=None if reviewer_results is None else reviewer_results.get(entry.journal_entry.decision_cycle_id),
        )
        for entry in entries
    )
    newest_first = _newest_first_history_panels(panels)
    chart_pairs = _synchronized_snapshot_pairs(managed_history, benchmark_history)
    chart_points = () if not comparison_available else tuple(
        HistoryChartPoint(
            timestamp_at=managed_snapshot.timestamp,
            timestamp=_format_datetime(managed_snapshot.timestamp),
            portfolio_value=managed_snapshot.portfolio_value,
            managed_return=comparison.managed_cumulative_return,
            benchmark_return=comparison.benchmark_cumulative_return,
            absolute_alpha=comparison.absolute_alpha,
        )
        for managed_index, benchmark_index in chart_pairs
        for managed_snapshot in (managed_history.snapshots[managed_index],)
        for comparison in (_history_prefix_comparison(
            managed_history, benchmark_history,
            managed_snapshot_index=managed_index, benchmark_snapshot_index=benchmark_index,
        ),)
    )
    return HistoryPanel(entries_newest_first=newest_first, chart_points_oldest_first=chart_points)


def _decision_panel(
    *,
    journal_entry: DecisionJournalEntry | None = None,
    approval: DecisionApproval | None = None,
    reviewer_result: ReviewerResult | None = None,
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
    reviewer_result = source.reviewer_result if reviewer_result is None else reviewer_result

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
    history_entries: tuple[DecisionHistoryArtifacts, ...] | list[DecisionHistoryArtifacts] = (),
    reviewer_results: tuple[ReviewerResult, ...] | list[ReviewerResult] = (),
) -> DashboardView:
    """Transform immutable domain objects into a compact dashboard view model."""
    if not managed_history.snapshots:
        raise ValueError("managed_history must contain at least one snapshot")
    if not benchmark_history.snapshots:
        raise ValueError("benchmark_history must contain at least one snapshot")
    managed_snapshot = managed_history.snapshots[-1]
    benchmark_snapshot = benchmark_history.snapshots[-1]
    if comparison is None:
        try:
            derived_comparison = PerformanceComparison(managed_history, benchmark_history)
        except ValueError as error:
            if str(error) != "managed and benchmark histories must have equal snapshot counts":
                raise
            derived_comparison = None
    else:
        derived_comparison = comparison
    if comparison is not None and (
        comparison.managed_history is not managed_history or comparison.benchmark_history is not benchmark_history
    ):
        raise ValueError("comparison histories must match the displayed histories")
    managed_panel = _portfolio_panel(managed_snapshot.portfolio, managed_snapshot.valuation)
    benchmark_panel = _benchmark_panel(benchmark_snapshot.portfolio, benchmark_snapshot.valuation)
    comparison_panel = None if derived_comparison is None else _comparison_panel(derived_comparison)
    reviewer_by_cycle = {item.decision_cycle_id: item for item in reviewer_results}
    if len(reviewer_by_cycle) != len(reviewer_results):
        raise ValueError("reviewer_results must not contain duplicate decision cycles")
    decision_cycle_id = None if journal_entry is None else journal_entry.decision_cycle_id
    decision_panel = _decision_panel(
        journal_entry=journal_entry, approval=approval,
        reviewer_result=None if decision_cycle_id is None else reviewer_by_cycle.get(decision_cycle_id),
    )
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
        history=_history_panel(
            history_entries, managed_history=managed_history, benchmark_history=benchmark_history,
            comparison_available=derived_comparison is not None, reviewer_results=reviewer_by_cycle,
        ),
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

    overview_tab, holdings_tab, performance_tab, decision_tab, research_tab, history_tab = st.tabs(DASHBOARD_TAB_LABELS)

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

    with history_tab:
        st.subheader("History")
        history = view.history
        if history is None or not history.entries_newest_first:
            st.write("No decision history is available.")
        else:
            entries_by_id = {entry.history_entry_id: entry for entry in history.entries_newest_first}
            selected_entry_id = st.selectbox(
                "Decision cycle",
                options=tuple(entries_by_id),
                format_func=lambda entry_id: entries_by_id[entry_id].selector_label,
                key="history_journal_entry_id",
            )
            entry = entries_by_id[selected_entry_id]

            st.divider()
            st.markdown("#### Decision Summary")
            decision_cols = st.columns(4)
            decision_cols[0].metric("Action", entry.action, delta_color=_semantic_color(entry.action))
            decision_cols[1].metric("Ticker", entry.ticker)
            decision_cols[2].metric("Target Weight", entry.target_weight)
            decision_cols[3].metric("Decision Time", entry.decision_timestamp)
            outcome_cols = st.columns(2)
            outcome_cols[0].metric("Reviewer", entry.reviewer_outcome, delta_color=_semantic_color(entry.reviewer_outcome))
            outcome_cols[1].metric("Human Approval", entry.approval_outcome, delta_color=_semantic_color(entry.approval_outcome))

            st.divider()
            st.markdown("#### Portfolio & Performance Snapshot")
            if entry.snapshot is None:
                st.write("No performance snapshot is linked to this decision cycle.")
            else:
                snapshot_cols = st.columns(4)
                snapshot_cols[0].metric("Portfolio Value", entry.snapshot.portfolio_value)
                snapshot_cols[1].metric("Cash", entry.snapshot.cash_value)
                snapshot_cols[2].metric("Positions Value", entry.snapshot.positions_value)
                snapshot_cols[3].metric("Snapshot Time", entry.snapshot.timestamp)
                return_cols = st.columns(3)
                for column, label, value in zip(
                    return_cols,
                    ("Managed Return", "Benchmark Return", "Absolute Alpha"),
                    (
                        entry.snapshot.managed_return,
                        entry.snapshot.benchmark_return,
                        entry.snapshot.absolute_alpha,
                    ),
                    strict=True,
                ):
                    delta, delta_color = _metric_delta(value)
                    column.metric(label, value, delta=delta, delta_color=delta_color)

            st.divider()
            st.markdown("#### Research Linkage")
            st.write(f"Research batch: {entry.research_batch_id}")
            st.write(
                f"Research packet: {entry.research_packet_id or 'No single packet is selected for this decision'}"
            )
            st.caption("See the Research tab for the immutable packet inputs.")

            st.divider()
            st.markdown("#### Execution")
            st.metric("Execution Status", entry.execution.status, delta_color=_semantic_color(entry.action))
            if entry.execution.executed_at is not None:
                execution_cols = st.columns(4)
                execution_cols[0].metric("Execution Price", entry.execution.execution_price)
                execution_cols[1].metric("Quantity", entry.execution.quantity)
                execution_cols[2].metric("Notional", entry.execution.notional)
                execution_cols[3].metric("Executed At", entry.execution.executed_at)

            st.divider()
            st.markdown("#### Contributions")
            if not entry.contributions:
                st.write("No CashEvents are linked to this performance snapshot.")
            else:
                st.table(
                    [
                        {"Timestamp": contribution.timestamp, "Amount": contribution.amount, "Type": contribution.source}
                        for contribution in entry.contributions
                    ]
                )

            st.divider()
            st.markdown("#### Performance Over Time")
            value_data = {point.timestamp: point.portfolio_value for point in history.chart_points_oldest_first}
            return_data = {
                point.timestamp: {
                    "Managed Return": point.managed_return,
                    "Benchmark Return": point.benchmark_return,
                    "Absolute Alpha": point.absolute_alpha,
                }
                for point in history.chart_points_oldest_first
            }
            st.caption("Historical snapshots shown oldest to newest.")
            st.line_chart(value_data)
            st.line_chart(return_data)
