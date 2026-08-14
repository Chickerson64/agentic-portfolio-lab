"""Explicit JSON response models for the read-only application API.

Financial values are serialized as decimal strings. This preserves the exact
Decimal values held by immutable domain artifacts and avoids binary-float loss.
All timestamps are serialized as timezone-aware ISO 8601 strings.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict

from agentic_portfolio_lab.dashboard import HistoryPanel
from agentic_portfolio_lab.domain.approval import DecisionApproval
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
from agentic_portfolio_lab.domain.performance import PerformanceComparison, PerformanceSnapshot
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.research import MissingData, ResearchBatch, ResearchPacket
from agentic_portfolio_lab.domain.trades import ExecutedTrade


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def _timestamp(value: datetime) -> str:
    return value.isoformat()


class SecurityResponse(ApiModel):
    ticker: str
    security_type: str
    exchange: str
    currency: str


class PositionValuationResponse(ApiModel):
    security: SecurityResponse
    quantity: str
    observed_price: str
    total_cost_basis: str
    market_value: str
    unrealized_gain_loss: str


class PortfolioSnapshotResponse(ApiModel):
    portfolio_id: str
    portfolio_name: str
    base_currency: str
    starting_capital: str
    created_at: str
    decision_cycle_id: str | None
    status: str
    as_of_timestamp: str
    cash_value: str
    invested_value: str
    total_value: str
    unrealized_gain_loss: str
    source_provider_identity: str
    market_date: str
    source_price_timestamp: str
    price_convention: str
    positions: tuple[PositionValuationResponse, ...]


class BenchmarkSnapshotResponse(ApiModel):
    benchmark_security: SecurityResponse
    snapshot: PortfolioSnapshotResponse


class PerformanceResponse(ApiModel):
    managed_portfolio_id: str
    benchmark_portfolio_id: str
    currency: str
    managed_cumulative_return: str
    benchmark_cumulative_return: str
    absolute_alpha: str
    relative_alpha: str
    as_of_timestamp: str


class EvidenceReferenceResponse(ApiModel):
    evidence_id: str
    source_type: str
    source_title: str
    source_date: str
    claim_supported: str


class RecommendationResponse(ApiModel):
    action: str
    ticker: str | None
    target_weight: str | None
    decision_rationale: str
    investment_thesis: str | None
    valuation: str
    risks: tuple[str, ...]
    confidence_score: int
    evidence: tuple[EvidenceReferenceResponse, ...]
    why_not_spy: str
    thesis_invalidation: tuple[str, ...]
    review_triggers: tuple[str, ...]


class ValidationRuleResponse(ApiModel):
    rule_id: str
    status: str
    reason: str
    actual_value: str | None
    allowed_threshold: str | None


class ValidationResponse(ApiModel):
    status: str
    validation_timestamp: str
    rules: tuple[ValidationRuleResponse, ...]
    validated_trade_id: str | None


class ReviewerFindingResponse(ApiModel):
    severity: str
    category: str
    message: str
    related_evidence_ids: tuple[str, ...]
    related_recommendation_field: str | None


class ReviewerResponse(ApiModel):
    decision: str
    reviewed_at: str
    findings: tuple[ReviewerFindingResponse, ...]


class ApprovalResponse(ApiModel):
    decision: str
    decision_maker_id: str
    decided_at: str
    comment: str | None


class ExecutionReadinessResponse(ApiModel):
    """Authoritative pre-execution status; no fill preview is calculated here."""

    executable: bool
    reason_code: str
    decision_cycle_id: str
    action: str
    security: SecurityResponse | None
    approval_status: str | None
    validation_status: str


class ExecutionResponse(ApiModel):
    executed_trade_id: str
    validated_trade_id: str
    security: SecurityResponse
    action: str
    executed_quantity: str
    execution_price: str
    executed_notional: str
    currency: str
    source_provider_identity: str
    market_date: str
    price_convention: str
    executed_at: str
    execution_source: str


class DecisionMemoResponse(ApiModel):
    decision_cycle_id: str
    portfolio_id: str
    manager_type: str
    constitution_version: str
    research_batch_id: str
    journaled_at: str
    produced_at: str
    recommendation: RecommendationResponse
    validation: ValidationResponse
    reviewer: ReviewerResponse | None
    approval: ApprovalResponse | None
    execution: ExecutionResponse | None
    execution_readiness: ExecutionReadinessResponse


class MissingDataResponse(ApiModel):
    value: None = None
    reason: str
    details: str | None


class ResearchSectionResponse(ApiModel):
    section_id: str
    content: str | None
    missing_data: MissingDataResponse | None
    evidence_ids: tuple[str, ...]


class ResearchEvidenceResponse(ApiModel):
    evidence_id: str
    source_type: str
    source_title: str
    source_date: str
    claim_supported: str


class ResearchPacketResponse(ApiModel):
    packet_id: str
    candidate_id: str
    ticker: str
    security_type: str
    exchange: str | None
    currency: str | None
    company_name: str | None
    sector: str | None
    industry: str | None
    as_of_timestamp: str
    evidence: tuple[ResearchEvidenceResponse, ...]
    sections: tuple[ResearchSectionResponse, ...]


class ResearchBatchResponse(ApiModel):
    batch_id: str
    decision_cycle_id: str
    portfolio_id: str
    manager_type: str
    created_at: str
    as_of_timestamp: str
    packets: tuple[ResearchPacketResponse, ...]


class HistoryExecutionResponse(ApiModel):
    status: str
    executed_trade_id: str | None
    validated_trade_id: str | None
    security: SecurityResponse | None
    action: str | None
    execution_price: str | None
    quantity: str | None
    notional: str | None
    executed_at: str | None


class HistoryEntryResponse(ApiModel):
    history_entry_id: str
    decision_cycle_id: str
    decision_timestamp: str
    action: str
    ticker: str
    target_weight: str
    reviewer_outcome: str
    approval_outcome: str
    research_batch_id: str
    research_packet_id: str | None
    execution: HistoryExecutionResponse


class HistoryChartPointResponse(ApiModel):
    timestamp: str
    portfolio_value: str
    managed_return: str
    benchmark_return: str
    absolute_alpha: str


class HistoryResponse(ApiModel):
    entries_newest_first: tuple[HistoryEntryResponse, ...]
    chart_points_oldest_first: tuple[HistoryChartPointResponse, ...]


class HealthResponse(ApiModel):
    status: str
    state_mode: str
    persisted: bool
    synthetic: bool


class PriceRefreshResponse(ApiModel):
    refreshed_tickers: tuple[str, ...]
    provider_identity: str
    latest_source_timestamp: str
    price_convention: str


class BuildResearchResponse(ApiModel):
    batch_id: str
    decision_cycle_id: str
    packet_count: int
    source_provider_identity: str
    as_of_timestamp: str


class CashEventCommand(ApiModel):
    amount: Decimal
    currency: str
    source: str
    effective_at: datetime


class CashEventResponse(ApiModel):
    event_id: str
    managed_cash: str
    benchmark_cash: str
    currency: str
    effective_at: str


class BenchmarkFulfillmentResponse(ApiModel):
    status: str
    fulfillment_id: str | None
    quantity: str | None
    notional: str | None
    provider_identity: str | None
    observed_at: str | None
    market_date: str | None
    price_convention: str | None


class RunValueManagerCommand(ApiModel):
    occurred_at: datetime


class DecisionApprovalCommand(ApiModel):
    decision_maker_id: str
    decided_at: datetime
    comment: str | None = None


class DashboardResponse(ApiModel):
    portfolio: PortfolioSnapshotResponse
    benchmark: BenchmarkSnapshotResponse
    performance: PerformanceResponse
    latest_decision: DecisionMemoResponse | None
    research: ResearchBatchResponse | None
    history: HistoryResponse
    benchmark_fulfillment_status: str


def security_response(security: SecurityIdentity) -> SecurityResponse:
    return SecurityResponse(
        ticker=security.ticker,
        security_type=security.security_type,
        exchange=security.exchange,
        currency=security.currency,
    )


def portfolio_snapshot_response(snapshot: PerformanceSnapshot) -> PortfolioSnapshotResponse:
    portfolio = snapshot.portfolio
    valuation = snapshot.valuation
    return PortfolioSnapshotResponse(
        portfolio_id=str(portfolio.portfolio_id),
        portfolio_name=portfolio.portfolio_name,
        base_currency=portfolio.base_currency,
        starting_capital=_decimal(portfolio.starting_capital),
        created_at=_timestamp(portfolio.created_at),
        decision_cycle_id=None if portfolio.decision_cycle_id is None else str(portfolio.decision_cycle_id),
        status=portfolio.status,
        as_of_timestamp=_timestamp(valuation.as_of_timestamp),
        cash_value=_decimal(valuation.cash_value),
        invested_value=_decimal(valuation.invested_value),
        total_value=_decimal(valuation.total_value),
        unrealized_gain_loss=_decimal(valuation.unrealized_gain_loss),
        source_provider_identity=valuation.source_provider_identity,
        market_date=valuation.market_date.isoformat(),
        source_price_timestamp=_timestamp(valuation.source_price_timestamp),
        price_convention=valuation.price_convention,
        positions=tuple(
            PositionValuationResponse(
                security=security_response(position.security),
                quantity=_decimal(position.quantity),
                observed_price=_decimal(position.observed_price),
                total_cost_basis=_decimal(position.total_cost_basis),
                market_value=_decimal(position.market_value),
                unrealized_gain_loss=_decimal(position.unrealized_gain_loss),
            )
            for position in valuation.position_valuations
        ),
    )


def benchmark_snapshot_response(
    snapshot: PerformanceSnapshot, benchmark_security: SecurityIdentity
) -> BenchmarkSnapshotResponse:
    return BenchmarkSnapshotResponse(
        benchmark_security=security_response(benchmark_security),
        snapshot=portfolio_snapshot_response(snapshot),
    )


def performance_response(comparison: PerformanceComparison) -> PerformanceResponse:
    return PerformanceResponse(
        managed_portfolio_id=str(comparison.managed_history.portfolio_id),
        benchmark_portfolio_id=str(comparison.benchmark_history.benchmark_portfolio_id),
        currency=comparison.managed_history.currency,
        managed_cumulative_return=_decimal(comparison.managed_cumulative_return),
        benchmark_cumulative_return=_decimal(comparison.benchmark_cumulative_return),
        absolute_alpha=_decimal(comparison.absolute_alpha),
        relative_alpha=_decimal(comparison.relative_alpha),
        as_of_timestamp=_timestamp(comparison.managed_history.snapshots[-1].timestamp),
    )


def _audit_value(value: Decimal | str | None) -> str | None:
    return None if value is None else _decimal(value) if isinstance(value, Decimal) else value


def _recommendation_response(journal: DecisionJournalEntry) -> RecommendationResponse:
    recommendation = journal.decision_result.recommendation
    return RecommendationResponse(
        action=recommendation.action.value,
        ticker=recommendation.ticker,
        target_weight=None if recommendation.target_weight is None else _decimal(recommendation.target_weight),
        decision_rationale=recommendation.decision_rationale,
        investment_thesis=recommendation.investment_thesis,
        valuation=recommendation.valuation,
        risks=recommendation.risks,
        confidence_score=recommendation.confidence_score,
        evidence=tuple(
            EvidenceReferenceResponse(
                evidence_id=item.evidence_id,
                source_type=item.source_type,
                source_title=item.source_title,
                source_date=item.source_date.isoformat(),
                claim_supported=item.claim_supported,
            )
            for item in recommendation.evidence
        ),
        why_not_spy=recommendation.why_not_spy,
        thesis_invalidation=recommendation.thesis_invalidation,
        review_triggers=tuple(trigger.description for trigger in recommendation.review_triggers),
    )


def _reviewer_response(journal: DecisionJournalEntry) -> ReviewerResponse | None:
    reviewer = journal.reviewer_result
    if reviewer is None:
        return None
    return ReviewerResponse(
        decision=reviewer.decision.value,
        reviewed_at=_timestamp(reviewer.reviewed_at),
        findings=tuple(
            ReviewerFindingResponse(
                severity=finding.severity.value,
                category=finding.category.value,
                message=finding.message,
                related_evidence_ids=tuple(finding.related_evidence_ids),
                related_recommendation_field=finding.related_recommendation_field,
            )
            for finding in reviewer.findings
        ),
    )


def _approval_response(approval: DecisionApproval | None) -> ApprovalResponse | None:
    if approval is None:
        return None
    return ApprovalResponse(
        decision=approval.decision.value,
        decision_maker_id=approval.decision_maker_id,
        decided_at=_timestamp(approval.decided_at),
        comment=approval.comment,
    )


def execution_response(executed_trade: ExecutedTrade | None) -> ExecutionResponse | None:
    if executed_trade is None:
        return None
    return ExecutionResponse(
        executed_trade_id=str(executed_trade.executed_trade_id),
        validated_trade_id=str(executed_trade.validated_trade_id),
        security=security_response(executed_trade.security),
        action=executed_trade.action,
        executed_quantity=_decimal(executed_trade.executed_quantity),
        execution_price=_decimal(executed_trade.execution_price),
        executed_notional=_decimal(executed_trade.executed_notional),
        currency=executed_trade.currency,
        source_provider_identity=executed_trade.source_provider_identity,
        market_date=executed_trade.market_date.isoformat(),
        price_convention=executed_trade.price_convention,
        executed_at=_timestamp(executed_trade.executed_at),
        execution_source=executed_trade.execution_source,
    )


def execution_readiness_response(
    journal: DecisionJournalEntry,
    approval: DecisionApproval | None,
    executed_trade: ExecutedTrade | None,
) -> ExecutionReadinessResponse:
    recommendation = journal.decision_result.recommendation
    validation = journal.risk_validation_result
    security = None
    if validation.validated_trade is not None:
        security = security_response(validation.validated_trade.proposal.security)
    if executed_trade is not None:
        code = "ALREADY_EXECUTED"
    elif recommendation.action.value == "HOLD":
        code = "HOLD"
    elif not validation.passed:
        code = "VALIDATION_FAILED"
    elif approval is None:
        code = "NOT_APPROVED"
    elif approval.decision.value != "APPROVED":
        code = "REJECTED"
    else:
        code = "READY"
    return ExecutionReadinessResponse(
        executable=code == "READY",
        reason_code=code,
        decision_cycle_id=str(journal.decision_cycle_id),
        action=recommendation.action.value,
        security=security,
        approval_status=None if approval is None else approval.decision.value,
        validation_status=validation.status.value,
    )


def decision_memo_response(
    journal: DecisionJournalEntry,
    approval: DecisionApproval | None,
    executed_trade: ExecutedTrade | None,
) -> DecisionMemoResponse:
    validation = journal.risk_validation_result
    return DecisionMemoResponse(
        decision_cycle_id=str(journal.decision_cycle_id),
        portfolio_id=str(journal.portfolio_id),
        manager_type=journal.manager_type,
        constitution_version=journal.constitution_version,
        research_batch_id=journal.research_batch_id,
        journaled_at=_timestamp(journal.journaled_at),
        produced_at=_timestamp(journal.decision_result.produced_at),
        recommendation=_recommendation_response(journal),
        validation=ValidationResponse(
            status=validation.status.value,
            validation_timestamp=_timestamp(validation.validation_timestamp),
            rules=tuple(
                ValidationRuleResponse(
                    rule_id=rule.rule_id,
                    status=rule.status.value,
                    reason=rule.reason,
                    actual_value=_audit_value(rule.actual_value),
                    allowed_threshold=_audit_value(rule.allowed_threshold),
                )
                for rule in validation.rule_results
            ),
            validated_trade_id=None if validation.validated_trade is None else str(validation.validated_trade.validated_trade_id),
        ),
        reviewer=_reviewer_response(journal),
        approval=_approval_response(approval),
        execution=execution_response(executed_trade),
        execution_readiness=execution_readiness_response(journal, approval, executed_trade),
    )


def _text_or_missing(value: str | MissingData) -> tuple[str | None, MissingDataResponse | None]:
    if isinstance(value, MissingData):
        return None, MissingDataResponse(reason=value.reason.value, details=value.details)
    return value, None


def _packet_text(value: str | MissingData) -> str | None:
    return None if isinstance(value, MissingData) else value


def _research_packet_response(packet: ResearchPacket) -> ResearchPacketResponse:
    return ResearchPacketResponse(
        packet_id=packet.packet_id,
        candidate_id=packet.candidate_id,
        ticker=packet.ticker,
        security_type=packet.security_type,
        exchange=_packet_text(packet.exchange),
        currency=_packet_text(packet.currency),
        company_name=_packet_text(packet.company_name),
        sector=_packet_text(packet.sector),
        industry=_packet_text(packet.industry),
        as_of_timestamp=_timestamp(packet.as_of_timestamp),
        evidence=tuple(
            ResearchEvidenceResponse(
                evidence_id=item.evidence_id,
                source_type=item.source_type,
                source_title=item.source_title,
                source_date=item.source_date.isoformat(),
                claim_supported=item.claim_supported,
            )
            for item in packet.evidence_items
        ),
        sections=tuple(
            ResearchSectionResponse(
                section_id=section.section_id,
                content=_text_or_missing(section.content)[0],
                missing_data=_text_or_missing(section.content)[1],
                evidence_ids=tuple(section.evidence_ids),
            )
            for section in packet.sections
        ),
    )


def research_batch_response(batch: ResearchBatch) -> ResearchBatchResponse:
    return ResearchBatchResponse(
        batch_id=batch.batch_id,
        decision_cycle_id=str(batch.decision_cycle_id),
        portfolio_id=str(batch.portfolio_id),
        manager_type=batch.manager_type,
        created_at=_timestamp(batch.created_at),
        as_of_timestamp=_timestamp(batch.as_of_timestamp),
        packets=tuple(_research_packet_response(packet) for packet in batch.packets),
    )


def history_response(history: HistoryPanel, artifacts_by_entry_id: dict[str, ExecutedTrade | None]) -> HistoryResponse:
    return HistoryResponse(
        entries_newest_first=tuple(
            HistoryEntryResponse(
                history_entry_id=entry.history_entry_id,
                decision_cycle_id=entry.history_entry_id,
                decision_timestamp=entry.decision_timestamp,
                action=entry.action,
                ticker=entry.ticker,
                target_weight=entry.target_weight,
                reviewer_outcome=entry.reviewer_outcome,
                approval_outcome=entry.approval_outcome,
                research_batch_id=entry.research_batch_id,
                research_packet_id=entry.research_packet_id,
                execution=HistoryExecutionResponse(
                    status=entry.execution.status,
                    executed_trade_id=None
                    if artifacts_by_entry_id[entry.history_entry_id] is None
                    else str(artifacts_by_entry_id[entry.history_entry_id].executed_trade_id),
                    validated_trade_id=None
                    if artifacts_by_entry_id[entry.history_entry_id] is None
                    else str(artifacts_by_entry_id[entry.history_entry_id].validated_trade_id),
                    security=None
                    if artifacts_by_entry_id[entry.history_entry_id] is None
                    else security_response(artifacts_by_entry_id[entry.history_entry_id].security),
                    action=None
                    if artifacts_by_entry_id[entry.history_entry_id] is None
                    else artifacts_by_entry_id[entry.history_entry_id].action,
                    execution_price=None
                    if artifacts_by_entry_id[entry.history_entry_id] is None
                    else _decimal(artifacts_by_entry_id[entry.history_entry_id].execution_price),
                    quantity=None
                    if artifacts_by_entry_id[entry.history_entry_id] is None
                    else _decimal(artifacts_by_entry_id[entry.history_entry_id].executed_quantity),
                    notional=None
                    if artifacts_by_entry_id[entry.history_entry_id] is None
                    else _decimal(artifacts_by_entry_id[entry.history_entry_id].executed_notional),
                    executed_at=None
                    if artifacts_by_entry_id[entry.history_entry_id] is None
                    else _timestamp(artifacts_by_entry_id[entry.history_entry_id].executed_at),
                ),
            )
            for entry in history.entries_newest_first
        ),
        chart_points_oldest_first=tuple(
            HistoryChartPointResponse(
                timestamp=point.timestamp,
                portfolio_value=_decimal(point.portfolio_value),
                managed_return=_decimal(point.managed_return),
                benchmark_return=_decimal(point.benchmark_return),
                absolute_alpha=_decimal(point.absolute_alpha),
            )
            for point in history.chart_points_oldest_first
        ),
    )
