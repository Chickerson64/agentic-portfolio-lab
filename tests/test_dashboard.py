from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from uuid import UUID

import pytest

from agentic_portfolio_lab.dashboard import (
    DASHBOARD_TAB_LABELS,
    _allocation_chart_data,
    _format_ticker,
    _metric_delta,
    _portfolio_heading,
    _semantic_color,
    build_dashboard_view,
    format_decimal,
    format_percent,
)
from agentic_portfolio_lab.dashboard_demo import build_demo_dashboard_data, build_demo_dashboard_view
from agentic_portfolio_lab.domain.approval import ApprovalDecision, DecisionApproval
from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
from agentic_portfolio_lab.domain.performance import BenchmarkPerformanceHistory, PerformanceComparison, PortfolioPerformanceHistory
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio, Position, SecurityIdentity
from agentic_portfolio_lab.domain.recommendations import PortfolioRecommendation, RecommendationAction, RecommendationEvidenceReference, ReviewTrigger, ReviewTriggerType
from agentic_portfolio_lab.domain.research import EvidenceItem, ResearchBatch, ResearchPacket, ResearchSection
from agentic_portfolio_lab.domain.risk_validation import DeterministicRiskValidator, RiskRuleResult, RiskValidationResult, RiskValidationStatus
from agentic_portfolio_lab.domain.reviewer import AIReviewerReviewContext, ReviewDecision, ReviewFinding, ReviewFindingCategory, ReviewFindingSeverity, ReviewerResult
from agentic_portfolio_lab.domain.valuation import BenchmarkPortfolio, PortfolioValuation, PriceObservation
from agentic_portfolio_lab.domain.value_manager_workflow import ValueManagerDecisionResult
from agentic_portfolio_lab.domain.value_manager import ValueManagerDecisionContext

UTC = timezone.utc
CREATED_AT = datetime(2026, 8, 12, 12, tzinfo=UTC)
VALIDATED_AT = datetime(2026, 8, 12, 13, tzinfo=UTC)
REVIEWED_AT = datetime(2026, 8, 12, 13, 10, tzinfo=UTC)
JOURNALED_AT = datetime(2026, 8, 12, 13, 20, tzinfo=UTC)
APPROVED_AT = datetime(2026, 8, 12, 13, 30, tzinfo=UTC)
BUY_DECISION_CYCLE_ID = UUID("00000000-0000-0000-0000-000000000031")
BUY_PORTFOLIO_ID = UUID("00000000-0000-0000-0000-000000000032")


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


def test_dashboard_uses_streamlit_tabs_for_main_read_only_sections() -> None:
    assert DASHBOARD_TAB_LABELS == ("Overview", "Holdings", "Performance", "Decision Memo", "Research")


def test_demo_dashboard_includes_latest_decision_summary() -> None:
    view = build_demo_dashboard_view()

    assert view.latest_decision is not None
    assert view.latest_decision.summary.action == "HOLD"
    assert view.latest_decision.summary.ticker == "n/a"
    assert view.latest_decision.summary.target_weight == "n/a"
    assert view.latest_decision.approval.decision == "APPROVED"
    assert view.latest_decision.reviewer.decision == "APPROVE"


def test_research_tab_exposes_deterministic_candidate_packets_and_metadata() -> None:
    view = build_demo_dashboard_view()

    assert view.research is not None
    assert view.research.manager_type == "VALUE"
    assert view.research.candidate_count == 3
    assert tuple(packet.candidate_id for packet in view.research.packets) == (
        "demo_candidate_001",
        "demo_candidate_002",
        "demo_candidate_003",
    )
    aapl = view.research.packets[0]
    assert aapl.selector_label == "AAPL — Demo Apple"
    assert aapl.security_type == "EQUITY"
    assert aapl.exchange == "NASDAQ"
    assert len(aapl.sections) == 2


def test_research_evidence_linkage_and_missing_data_are_display_only() -> None:
    view = build_demo_dashboard_view()

    assert view.research is not None
    aapl_evidence = {evidence.evidence_id: evidence for evidence in view.research.packets[0].evidence}
    assert aapl_evidence["demo_ev_001"].cited_by_decision is True
    assert aapl_evidence["demo_ev_001"].referenced_by_reviewer is True
    assert aapl_evidence["demo_ev_002"].cited_by_decision is False
    googl = view.research.packets[2]
    assert googl.exchange is None
    assert googl.currency is None
    assert {missing.field_name for missing in googl.missing_data} == {
        "Exchange",
        "Currency",
        "Section: VALUATION_CONTEXT",
    }


def test_research_without_journal_has_no_decision_or_reviewer_evidence_badges() -> None:
    data = build_demo_dashboard_data()
    research_batch = data.journal_entry.decision_result.context.research_batch

    view = build_dashboard_view(
        managed_history=data.managed_history,
        benchmark_history=data.benchmark_history,
        research_batch=research_batch,
    )

    assert view.research is not None
    assert not any(
        evidence.cited_by_decision or evidence.referenced_by_reviewer
        for packet in view.research.packets
        for evidence in packet.evidence
    )


def test_journal_research_batch_is_authoritative_when_a_journal_exists() -> None:
    data = build_demo_dashboard_data()
    research_batch = data.journal_entry.decision_result.context.research_batch

    with pytest.raises(ValueError, match="authoritative ResearchBatch"):
        build_dashboard_view(
            managed_history=data.managed_history,
            benchmark_history=data.benchmark_history,
            journal_entry=data.journal_entry,
            research_batch=replace(research_batch, batch_id="different_batch"),
        )


def test_latest_decision_view_uses_the_journal_decision_cycle_for_every_artifact() -> None:
    data = build_demo_dashboard_data()
    view = build_demo_dashboard_view()

    assert view.latest_decision is not None
    assert view.latest_decision.summary.decision_cycle_id == str(data.journal_entry.decision_result.decision_cycle_id)
    assert data.journal_entry.risk_validation_result.decision_result is data.journal_entry.decision_result
    assert data.journal_entry.reviewer_result is not None
    assert data.journal_entry.reviewer_result.context.decision_result is data.journal_entry.decision_result
    assert data.approval.journal_entry is data.journal_entry


def test_buy_recommendation_rendering_uses_actual_ticker_and_colors() -> None:
    view = build_buy_review_view()

    assert view.latest_decision is not None
    assert view.latest_decision.summary.action == "BUY"
    assert view.latest_decision.summary.ticker == "AAPL"
    assert view.latest_decision.summary.ticker != "n/a"
    assert view.latest_decision.summary.target_weight == "25%"
    assert view.latest_decision.narrative.thesis == "The business compounds with durable economics."
    assert view.latest_decision.narrative.decision_rationale == "The stock is attractive on quality and valuation."
    assert view.latest_decision.narrative.valuation == "Valuation is supported by cash generation."
    assert view.latest_decision.narrative.why_not_spy == "The opportunity is stronger than the baseline index allocation."
    assert _semantic_color("BUY") == "normal"
    assert _semantic_color("APPROVED") == "normal"


def test_presentation_metric_colors_and_allocation_use_existing_view_values() -> None:
    view = build_buy_review_view()

    assert _metric_delta("2.5%") == ("Positive", "normal")
    assert _metric_delta("-2.5%") == ("Negative", "inverse")
    assert _metric_delta("0%") == ("Neutral", "off")
    assert _allocation_chart_data(view.managed.positions) == {
        row.ticker: row.allocation_weight for row in view.managed.positions
    }


def test_reviewer_request_changes_and_absent_states_are_supported() -> None:
    view = build_buy_review_view()
    pending = build_buy_pending_review_view()
    assert view.latest_decision is not None
    assert pending.latest_decision is not None
    review = view.latest_decision.reviewer
    assert review.decision == "APPROVE"
    request_changes = replace(review, decision="REQUEST_CHANGES")
    absent = pending.latest_decision.reviewer
    assert request_changes.decision == "REQUEST_CHANGES"
    assert absent.decision is None


def test_real_reviewer_request_changes_is_rendered_from_the_journal() -> None:
    data = build_demo_dashboard_data()
    original_review = data.journal_entry.reviewer_result
    assert original_review is not None
    request_changes = ReviewerResult(
        context=original_review.context,
        decision=ReviewDecision.REQUEST_CHANGES,
        findings=original_review.findings,
        reviewed_at=original_review.reviewed_at,
    )
    journal_entry = replace(data.journal_entry, reviewer_result=request_changes)

    view = build_dashboard_view(
        managed_history=data.managed_history,
        benchmark_history=data.benchmark_history,
        journal_entry=journal_entry,
    )

    assert view.latest_decision is not None
    assert view.latest_decision.reviewer.decision == "REQUEST_CHANGES"
    assert view.latest_decision.reviewer.findings[0].message == original_review.findings[0].message


def test_human_approval_rejected_and_absent_states_are_supported() -> None:
    view = build_buy_review_view()
    pending = build_buy_pending_review_view()
    assert view.latest_decision is not None
    assert pending.latest_decision is not None
    approval = view.latest_decision.approval
    rejected = replace(approval, decision="REJECTED")
    absent = pending.latest_decision.approval
    assert rejected.decision == "REJECTED"
    assert absent.decision is None


def test_real_rejected_human_approval_is_rendered_separately() -> None:
    data = build_demo_dashboard_data()
    rejected = DecisionApproval(
        journal_entry=data.journal_entry,
        decision_maker_id="rejecting-human",
        decision=ApprovalDecision.REJECTED,
        decided_at=data.approval.decided_at,
        comment="Rejected after human review.",
    )

    view = build_dashboard_view(
        managed_history=data.managed_history,
        benchmark_history=data.benchmark_history,
        journal_entry=data.journal_entry,
        approval=rejected,
    )

    assert view.latest_decision is not None
    assert view.latest_decision.reviewer.decision == "APPROVE"
    assert view.latest_decision.approval.decision == "REJECTED"
    assert view.latest_decision.approval.decision_maker_id == "rejecting-human"


def test_demo_dashboard_data_is_deterministic() -> None:
    assert build_demo_dashboard_data() == build_demo_dashboard_data()


def test_demo_dashboard_data_is_immutable_from_the_view_layer() -> None:
    data = build_demo_dashboard_data()
    managed_before = data.managed_history.snapshots
    benchmark_before = data.benchmark_history.snapshots
    research_before = data.journal_entry.decision_result.context.research_batch

    build_dashboard_view(
        managed_history=data.managed_history,
        benchmark_history=data.benchmark_history,
        comparison=data.comparison,
        journal_entry=data.journal_entry,
        approval=data.approval,
    )

    assert data.managed_history.snapshots == managed_before
    assert data.benchmark_history.snapshots == benchmark_before
    assert data.journal_entry.decision_result.context.research_batch == research_before
    assert data.managed_history.snapshots[-1].valuation.total_value == Decimal("1120")


def test_empty_position_state_renders_without_rows() -> None:
    created_at = datetime(2026, 8, 13, tzinfo=UTC)
    managed_portfolio = Portfolio(
        portfolio_id=UUID("00000000-0000-0000-0000-000000000040"),
        portfolio_name="Empty",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance("USD", Decimal("1000")),
        created_at=created_at,
    )
    benchmark_portfolio = BenchmarkPortfolio(
        Portfolio(
            portfolio_id=UUID("00000000-0000-0000-0000-000000000041"),
            portfolio_name="Empty Benchmark",
            base_currency="USD",
            starting_capital=Decimal("1000"),
            cash_balance=CashBalance("USD", Decimal("1000")),
            created_at=created_at,
        ),
        SecurityIdentity(ticker="SPY", security_type="ETF", exchange="NYSEARCA", currency="USD"),
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
    view = build_dashboard_view(
        managed_history=managed_history,
        benchmark_history=benchmark_history,
        comparison=PerformanceComparison(managed_history, benchmark_history),
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


def test_reviewer_absent_and_evidence_rendering_fields_remain_read_only() -> None:
    view = build_buy_review_view()
    assert view.latest_decision is not None
    evidence = view.latest_decision.evidence[0]
    assert evidence.evidence_id == "buy_ev_001"
    assert evidence.source_type == "FILING"
    assert evidence.source_title == "Quarterly Report"
    assert evidence.source_date == CREATED_AT.date().isoformat()
    assert evidence.claim_supported == "Strong quarterly cash generation supports the buy case."


def test_risk_rule_rendering_includes_actual_and_threshold_values() -> None:
    view = build_buy_review_view()
    assert view.latest_decision is not None
    rule = next(rule for rule in view.latest_decision.validation.rules if rule.rule_id == "CASH_FEASIBILITY")
    assert rule.actual_value is not None
    assert rule.allowed_threshold is not None


def test_thesis_absent_and_present_paths_are_supported() -> None:
    demo = build_demo_dashboard_view()
    assert demo.latest_decision is not None
    assert demo.latest_decision.narrative.thesis is None
    buy = build_buy_review_view()
    assert buy.latest_decision is not None
    assert buy.latest_decision.narrative.thesis is not None


def test_dashboard_rejects_mismatched_comparison_histories() -> None:
    data = build_demo_dashboard_data()
    cloned_managed_history = replace(data.managed_history)
    unrelated_comparison = PerformanceComparison(cloned_managed_history, data.benchmark_history)

    with pytest.raises(ValueError, match="comparison histories"):
        build_dashboard_view(
            managed_history=data.managed_history,
            benchmark_history=data.benchmark_history,
            comparison=unrelated_comparison,
        )


def test_dashboard_rejects_mismatched_journal_and_approval() -> None:
    data = build_demo_dashboard_data()
    mismatched_journal = replace(
        data.journal_entry,
        journaled_at=data.journal_entry.journaled_at + timedelta(seconds=1),
    )

    with pytest.raises(ValueError, match="approval journal_entry"):
        build_dashboard_view(
            managed_history=data.managed_history,
            benchmark_history=data.benchmark_history,
            journal_entry=mismatched_journal,
            approval=data.approval,
        )


def build_buy_review_view():
    portfolio = Portfolio(
        portfolio_id=BUY_PORTFOLIO_ID,
        portfolio_name="Core Growth",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance("USD", Decimal("1000")),
        created_at=CREATED_AT,
    )
    security = SecurityIdentity(ticker="AAPL", security_type="EQUITY", exchange="NASDAQ", currency="USD")
    research_batch = ResearchBatch(
        batch_id="buy_batch_001",
        decision_cycle_id=BUY_DECISION_CYCLE_ID,
        portfolio_id=portfolio.portfolio_id,
        manager_type="VALUE",
        created_at=CREATED_AT,
        as_of_timestamp=CREATED_AT,
        packets=(
            ResearchPacket(
                packet_id="buy_packet_001",
                candidate_id="buy_candidate_001",
                ticker="AAPL",
                security_type="EQUITY",
                exchange="NASDAQ",
                currency="USD",
                company_name="Apple",
                sector="Technology",
                industry="Consumer Electronics",
                as_of_timestamp=CREATED_AT,
                evidence_items=(
                    EvidenceItem(
                        evidence_id="buy_ev_001",
                        source_type="FILING",
                        source_title="Quarterly Report",
                        source_date=CREATED_AT.date(),
                        claim_supported="Strong quarterly cash generation supports the buy case.",
                    ),
                ),
                sections=(
                    ResearchSection(
                        section_id="BUSINESS_OVERVIEW",
                        content="Business overview.",
                        evidence_ids=("buy_ev_001",),
                    ),
                ),
            ),
        ),
    )
    constitution = ConstitutionLoader.load_value_manager_constitution()
    recommendation = PortfolioRecommendation(
        action=RecommendationAction.BUY,
        ticker="AAPL",
        target_weight=Decimal("0.25"),
        decision_rationale="The stock is attractive on quality and valuation.",
        investment_thesis="The business compounds with durable economics.",
        valuation="Valuation is supported by cash generation.",
        risks=("Valuation could compress if growth stalls.",),
        confidence_score=82,
        evidence=(
            RecommendationEvidenceReference(
                evidence_id="buy_ev_001",
                source_type="FILING",
                source_title="Quarterly Report",
                source_date=CREATED_AT.date(),
                claim_supported="Strong quarterly cash generation supports the buy case.",
            ),
        ),
        why_not_spy="The opportunity is stronger than the baseline index allocation.",
        thesis_invalidation=("Operating cash flow deteriorates materially.",),
        review_triggers=(ReviewTrigger(ReviewTriggerType.EVENT_BASED, "Refresh on next earnings release."),),
    )
    decision_result = ValueManagerDecisionResult(
        context=ValueManagerDecisionContext(portfolio=portfolio, research_batch=research_batch, constitution=constitution),
        recommendation=recommendation,
        produced_at=CREATED_AT,
    )
    price_observation = PriceObservation(
        security=security,
        observed_price=Decimal("100"),
        market_date=CREATED_AT.date(),
        observed_at=VALIDATED_AT - timedelta(minutes=5),
        currency="USD",
        source_provider_identity="demo-provider",
        price_convention="regular-session-close",
    )
    validation = DeterministicRiskValidator().validate(
        decision_result,
        validation_timestamp=VALIDATED_AT,
        price_observation=price_observation,
    )
    reviewer_context = AIReviewerReviewContext(
        decision_result=decision_result,
        risk_validation_result=validation,
        constitution=constitution,
    )
    reviewer_result = ReviewerResult(
        context=reviewer_context,
        decision=ReviewDecision.APPROVE,
        findings=(
            ReviewFinding(
                severity=ReviewFindingSeverity.INFO,
                category=ReviewFindingCategory.EVIDENCE_USAGE,
                message="Evidence is directly linked to the recommendation.",
                related_evidence_ids=("buy_ev_001",),
                related_recommendation_field="evidence",
            ),
        ),
        reviewed_at=REVIEWED_AT,
    )
    journal_entry = DecisionJournalEntry(
        decision_result=decision_result,
        risk_validation_result=validation,
        journaled_at=JOURNALED_AT,
        reviewer_result=reviewer_result,
    )
    approval = DecisionApproval(
        journal_entry=journal_entry,
        decision_maker_id="demo-human",
        decision=ApprovalDecision.APPROVED,
        decided_at=APPROVED_AT,
        comment="Approved for demo.",
    )
    managed_history = PortfolioPerformanceHistory(portfolio.portfolio_id, "USD").append(
        portfolio,
        PortfolioValuation.from_portfolio(
            portfolio,
            (),
            as_of_timestamp=VALIDATED_AT,
            market_date=VALIDATED_AT.date(),
            source_price_timestamp=price_observation.observed_at,
            source_provider_identity="demo-provider",
            price_convention="regular-session-close",
        ),
    )
    benchmark_portfolio = BenchmarkPortfolio(
        Portfolio(
            portfolio_id=UUID("00000000-0000-0000-0000-000000000033"),
            portfolio_name="Passive Index",
            base_currency="USD",
            starting_capital=Decimal("1000"),
            cash_balance=CashBalance("USD", Decimal("1000")),
            created_at=CREATED_AT,
            positions=(Position(SecurityIdentity("SPY", "ETF", "NYSEARCA", "USD"), Decimal("5"), Decimal("1000"), Decimal("200")),),
        ),
        SecurityIdentity("SPY", "ETF", "NYSEARCA", "USD"),
    )
    benchmark_history = BenchmarkPerformanceHistory.for_benchmark(benchmark_portfolio).append(
        benchmark_portfolio,
        PortfolioValuation.from_benchmark(
            benchmark_portfolio,
            (
                PriceObservation(
                    security=benchmark_portfolio.benchmark_security,
                    observed_price=Decimal("200"),
                    market_date=VALIDATED_AT.date(),
                    observed_at=VALIDATED_AT - timedelta(minutes=5),
                    currency="USD",
                    source_provider_identity="demo-provider",
                    price_convention="regular-session-close",
                ),
            ),
            as_of_timestamp=VALIDATED_AT,
            market_date=VALIDATED_AT.date(),
            source_price_timestamp=VALIDATED_AT - timedelta(minutes=5),
            source_provider_identity="demo-provider",
            price_convention="regular-session-close",
        ),
    )
    return build_dashboard_view(
        managed_history=managed_history,
        benchmark_history=benchmark_history,
        journal_entry=journal_entry,
        approval=approval,
    )


def build_buy_pending_review_view():
    portfolio = Portfolio(
        portfolio_id=BUY_PORTFOLIO_ID,
        portfolio_name="Core Growth",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance("USD", Decimal("1000")),
        created_at=CREATED_AT,
    )
    security = SecurityIdentity(ticker="AAPL", security_type="EQUITY", exchange="NASDAQ", currency="USD")
    research_batch = ResearchBatch(
        batch_id="buy_batch_001",
        decision_cycle_id=BUY_DECISION_CYCLE_ID,
        portfolio_id=portfolio.portfolio_id,
        manager_type="VALUE",
        created_at=CREATED_AT,
        as_of_timestamp=CREATED_AT,
        packets=(
            ResearchPacket(
                packet_id="buy_packet_001",
                candidate_id="buy_candidate_001",
                ticker="AAPL",
                security_type="EQUITY",
                exchange="NASDAQ",
                currency="USD",
                company_name="Apple",
                sector="Technology",
                industry="Consumer Electronics",
                as_of_timestamp=CREATED_AT,
                evidence_items=(
                    EvidenceItem(
                        evidence_id="buy_ev_001",
                        source_type="FILING",
                        source_title="Quarterly Report",
                        source_date=CREATED_AT.date(),
                        claim_supported="Strong quarterly cash generation supports the buy case.",
                    ),
                ),
                sections=(
                    ResearchSection(
                        section_id="BUSINESS_OVERVIEW",
                        content="Business overview.",
                        evidence_ids=("buy_ev_001",),
                    ),
                ),
            ),
        ),
    )
    constitution = ConstitutionLoader.load_value_manager_constitution()
    recommendation = PortfolioRecommendation(
        action=RecommendationAction.BUY,
        ticker="AAPL",
        target_weight=Decimal("0.25"),
        decision_rationale="The stock is attractive on quality and valuation.",
        investment_thesis="The business compounds with durable economics.",
        valuation="Valuation is supported by cash generation.",
        risks=("Valuation could compress if growth stalls.",),
        confidence_score=82,
        evidence=(
            RecommendationEvidenceReference(
                evidence_id="buy_ev_001",
                source_type="FILING",
                source_title="Quarterly Report",
                source_date=CREATED_AT.date(),
                claim_supported="Strong quarterly cash generation supports the buy case.",
            ),
        ),
        why_not_spy="The opportunity is stronger than the baseline index allocation.",
        thesis_invalidation=("Operating cash flow deteriorates materially.",),
        review_triggers=(ReviewTrigger(ReviewTriggerType.EVENT_BASED, "Refresh on next earnings release."),),
    )
    decision_result = ValueManagerDecisionResult(
        context=ValueManagerDecisionContext(portfolio=portfolio, research_batch=research_batch, constitution=constitution),
        recommendation=recommendation,
        produced_at=CREATED_AT,
    )
    price_observation = PriceObservation(
        security=security,
        observed_price=Decimal("100"),
        market_date=CREATED_AT.date(),
        observed_at=VALIDATED_AT - timedelta(minutes=5),
        currency="USD",
        source_provider_identity="demo-provider",
        price_convention="regular-session-close",
    )
    validation = DeterministicRiskValidator().validate(
        decision_result,
        validation_timestamp=VALIDATED_AT,
        price_observation=price_observation,
    )
    journal_entry = DecisionJournalEntry(
        decision_result=decision_result,
        risk_validation_result=validation,
        journaled_at=JOURNALED_AT,
    )
    managed_history = PortfolioPerformanceHistory(portfolio.portfolio_id, "USD").append(
        portfolio,
        PortfolioValuation.from_portfolio(
            portfolio,
            (),
            as_of_timestamp=VALIDATED_AT,
            market_date=VALIDATED_AT.date(),
            source_price_timestamp=price_observation.observed_at,
            source_provider_identity="demo-provider",
            price_convention="regular-session-close",
        ),
    )
    benchmark_portfolio = BenchmarkPortfolio(
        Portfolio(
            portfolio_id=UUID("00000000-0000-0000-0000-000000000033"),
            portfolio_name="Passive Index",
            base_currency="USD",
            starting_capital=Decimal("1000"),
            cash_balance=CashBalance("USD", Decimal("1000")),
            created_at=CREATED_AT,
            positions=(Position(security=SecurityIdentity(ticker="SPY", security_type="ETF", exchange="NYSEARCA", currency="USD"), quantity=Decimal("5"), total_cost_basis=Decimal("1000"), market_price=Decimal("200")),),
        ),
        SecurityIdentity(ticker="SPY", security_type="ETF", exchange="NYSEARCA", currency="USD"),
    )
    benchmark_history = BenchmarkPerformanceHistory.for_benchmark(benchmark_portfolio).append(
        benchmark_portfolio,
        PortfolioValuation.from_benchmark(
            benchmark_portfolio,
            (
                PriceObservation(
                    security=benchmark_portfolio.benchmark_security,
                    observed_price=Decimal("200"),
                    market_date=VALIDATED_AT.date(),
                    observed_at=VALIDATED_AT - timedelta(minutes=5),
                    currency="USD",
                    source_provider_identity="demo-provider",
                    price_convention="regular-session-close",
                ),
            ),
            as_of_timestamp=VALIDATED_AT,
            market_date=VALIDATED_AT.date(),
            source_price_timestamp=VALIDATED_AT - timedelta(minutes=5),
            source_provider_identity="demo-provider",
            price_convention="regular-session-close",
        ),
    )
    return build_dashboard_view(
        managed_history=managed_history,
        benchmark_history=benchmark_history,
        journal_entry=journal_entry,
    )
