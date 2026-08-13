"""Deterministic in-memory demo state for the dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from .dashboard import DashboardView, build_dashboard_view
from .domain.approval import ApprovalDecision, DecisionApproval
from .domain.cash_events import CashEvent
from .domain.constitution import ConstitutionLoader
from .domain.journal import DecisionJournalEntry
from .domain.performance import BenchmarkPerformanceHistory, PerformanceComparison, PortfolioPerformanceHistory
from .domain.portfolio import CashBalance, Portfolio, Position, SecurityIdentity
from .domain.recommendations import PortfolioRecommendation, RecommendationAction, RecommendationEvidenceReference, ReviewTrigger, ReviewTriggerType
from .domain.research import EvidenceItem, ResearchBatch, ResearchPacket, ResearchSection
from .domain.risk_validation import RiskRuleResult, RiskValidationResult, RiskValidationStatus
from .domain.reviewer import AIReviewerReviewContext, ReviewDecision, ReviewFinding, ReviewFindingCategory, ReviewFindingSeverity, ReviewerResult
from .domain.value_manager_workflow import ValueManagerDecisionResult
from .domain.valuation import BenchmarkPortfolio, PortfolioValuation, PriceObservation
from .domain.value_manager import ValueManagerDecisionContext

UTC = timezone.utc
DEMO_CREATED_AT = datetime(2026, 8, 10, 12, tzinfo=UTC)
BASELINE_AT = datetime(2026, 8, 10, 13, tzinfo=UTC)
LATEST_AT = datetime(2026, 8, 11, 13, tzinfo=UTC)
PRICE_TS = datetime(2026, 8, 11, 12, tzinfo=UTC)
DEMO_MANAGED_ID = UUID("00000000-0000-0000-0000-000000000018")
DEMO_BENCHMARK_ID = UUID("00000000-0000-0000-0000-000000000019")
DEMO_CASH_EVENT_ID = UUID("00000000-0000-0000-0000-000000000020")
DEMO_DECISION_CYCLE_ID = UUID("00000000-0000-0000-0000-000000000021")


@dataclass(frozen=True, slots=True)
class DashboardDemoData:
    managed_history: PortfolioPerformanceHistory
    benchmark_history: BenchmarkPerformanceHistory
    comparison: PerformanceComparison
    journal_entry: DecisionJournalEntry
    approval: DecisionApproval


def _security(ticker: str, *, exchange: str, security_type: str = "EQUITY") -> SecurityIdentity:
    return SecurityIdentity(ticker=ticker, security_type=security_type, exchange=exchange, currency="USD")


def _managed_portfolio(cash: Decimal, *, created_at: datetime, portfolio_id: UUID = DEMO_MANAGED_ID) -> Portfolio:
    aapl = _security("AAPL", exchange="NASDAQ")
    msft = _security("MSFT", exchange="NASDAQ")
    return Portfolio(
        portfolio_id=portfolio_id,
        portfolio_name="Managed Value",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance("USD", cash),
        created_at=created_at,
        positions=(
            Position(aapl, Decimal("2"), Decimal("280"), Decimal("150")),
            Position(msft, Decimal("1"), Decimal("180"), Decimal("320")),
        ),
    )


def _benchmark_portfolio(cash: Decimal, *, created_at: datetime, portfolio_id: UUID = DEMO_BENCHMARK_ID) -> BenchmarkPortfolio:
    spy = _security("SPY", exchange="NYSEARCA", security_type="ETF")
    return BenchmarkPortfolio(
        Portfolio(
            portfolio_id=portfolio_id,
            portfolio_name="Passive Index",
            base_currency="USD",
            starting_capital=Decimal("1000"),
            cash_balance=CashBalance("USD", cash),
            created_at=created_at,
            positions=(Position(spy, Decimal("5"), Decimal("2000"), Decimal("402")),),
        ),
        spy,
    )


def _valuation(portfolio: Portfolio, *, timestamp: datetime, provider: str, prices: dict[SecurityIdentity, Decimal]) -> PortfolioValuation:
    observed_at = timestamp - timedelta(hours=1)
    observations = tuple(
        PriceObservation(
            security=position.security,
            observed_price=prices[position.security],
            market_date=timestamp.date(),
            observed_at=observed_at,
            currency=portfolio.base_currency,
            source_provider_identity=provider,
            price_convention="regular-session-close",
        )
        for position in portfolio.positions
    )
    return PortfolioValuation.from_portfolio(
        portfolio,
        observations,
        as_of_timestamp=timestamp,
        market_date=timestamp.date(),
        source_price_timestamp=observed_at,
        source_provider_identity=provider,
        price_convention="regular-session-close",
    )


def _demo_cash_event() -> CashEvent:
    return CashEvent(
        amount=Decimal("200"),
        currency="USD",
        effective_at=LATEST_AT,
        source="manual contribution",
        event_id=DEMO_CASH_EVENT_ID,
    )


def _demo_research_batch(portfolio: Portfolio) -> ResearchBatch:
    evidence = EvidenceItem(
        evidence_id="demo_ev_001",
        source_type="FILING",
        source_title="Quarterly Report",
        source_date=DEMO_CREATED_AT.date(),
        claim_supported="The portfolio retains cash and a concentrated equity mix.",
    )
    packet = ResearchPacket(
        packet_id="demo_packet_001",
        candidate_id="demo_candidate_001",
        ticker="AAPL",
        security_type="EQUITY",
        exchange="NASDAQ",
        currency="USD",
        company_name="Demo Apple",
        sector="Technology",
        industry="Consumer Electronics",
        as_of_timestamp=DEMO_CREATED_AT,
        evidence_items=(evidence,),
        sections=(
            ResearchSection(
                section_id="BUSINESS_OVERVIEW",
                content="Demo-only business overview.",
                evidence_ids=(evidence.evidence_id,),
            ),
        ),
    )
    return ResearchBatch(
        batch_id="demo_batch_001",
        decision_cycle_id=DEMO_DECISION_CYCLE_ID,
        portfolio_id=portfolio.portfolio_id,
        manager_type="VALUE",
        created_at=DEMO_CREATED_AT,
        as_of_timestamp=DEMO_CREATED_AT,
        packets=(packet,),
    )


def build_demo_dashboard_data() -> DashboardDemoData:
    managed_id = DEMO_MANAGED_ID
    benchmark_id = DEMO_BENCHMARK_ID
    cash_event = _demo_cash_event()

    managed_history = PortfolioPerformanceHistory(managed_id, "USD")
    benchmark_history = BenchmarkPerformanceHistory.for_benchmark(
        _benchmark_portfolio(Decimal("1000"), created_at=DEMO_CREATED_AT, portfolio_id=benchmark_id)
    )

    baseline_managed = _managed_portfolio(Decimal("250"), created_at=DEMO_CREATED_AT, portfolio_id=managed_id)
    baseline_benchmark = _benchmark_portfolio(Decimal("250"), created_at=DEMO_CREATED_AT, portfolio_id=benchmark_id)
    managed_history = managed_history.append(
        baseline_managed,
        _valuation(
            baseline_managed,
            timestamp=BASELINE_AT,
            provider="demo-provider",
            prices={
                baseline_managed.positions[0].security: Decimal("150"),
                baseline_managed.positions[1].security: Decimal("320"),
            },
        ),
    )
    benchmark_history = benchmark_history.append(
        baseline_benchmark,
        _valuation(
            baseline_benchmark.portfolio,
            timestamp=BASELINE_AT,
            provider="demo-provider",
            prices={baseline_benchmark.portfolio.positions[0].security: Decimal("400")},
        ),
    )

    latest_managed = _managed_portfolio(Decimal("450"), created_at=DEMO_CREATED_AT, portfolio_id=managed_id)
    latest_benchmark = _benchmark_portfolio(Decimal("450"), created_at=DEMO_CREATED_AT, portfolio_id=benchmark_id)
    managed_history = managed_history.append(
        latest_managed,
        _valuation(
            latest_managed,
            timestamp=LATEST_AT,
            provider="demo-provider",
            prices={
                latest_managed.positions[0].security: Decimal("165"),
                latest_managed.positions[1].security: Decimal("340"),
            },
        ),
        cash_events=(cash_event,),
    )
    benchmark_history = benchmark_history.append(
        latest_benchmark,
        _valuation(
            latest_benchmark.portfolio,
            timestamp=LATEST_AT,
            provider="demo-provider",
            prices={latest_benchmark.portfolio.positions[0].security: Decimal("410")},
        ),
        cash_events=(cash_event,),
    )

    research_batch = _demo_research_batch(latest_managed)
    constitution = ConstitutionLoader.load_value_manager_constitution()
    context = ValueManagerDecisionContext(
        portfolio=latest_managed,
        research_batch=research_batch,
        constitution=constitution,
    )
    recommendation = PortfolioRecommendation(
        action=RecommendationAction.HOLD,
        ticker=None,
        target_weight=None,
        decision_rationale="No candidate clears the bar for a controlled demonstration dashboard.",
        investment_thesis=None,
        valuation="The current setup is a HOLD demonstration.",
        risks=("No active opportunity is being shown in the demo state.",),
        confidence_score=58,
        evidence=(
            RecommendationEvidenceReference(
                evidence_id="demo_ev_001",
                source_type="FILING",
                source_title="Quarterly Report",
                source_date=DEMO_CREATED_AT.date(),
                claim_supported="The portfolio retains cash and a concentrated equity mix.",
            ),
        ),
        why_not_spy="The dashboard demo is intentionally showing a HOLD summary.",
        thesis_invalidation=(),
        review_triggers=(ReviewTrigger(ReviewTriggerType.EVENT_BASED, "Refresh when the demo fixture changes."),),
    )
    decision_result = ValueManagerDecisionResult(
        context=context,
        recommendation=recommendation,
        produced_at=LATEST_AT,
    )
    rule = RiskRuleResult("DEMO_RULE", RiskValidationStatus.PASSED, "demo passed")
    validation = RiskValidationResult(
        decision_result=decision_result,
        validation_timestamp=LATEST_AT,
        status=RiskValidationStatus.PASSED,
        rule_results=(rule,),
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
                message="The HOLD recommendation cites the supplied quarterly report directly.",
                related_evidence_ids=("demo_ev_001",),
                related_recommendation_field="evidence",
            ),
        ),
        reviewed_at=LATEST_AT + timedelta(minutes=15),
    )
    journal_entry = DecisionJournalEntry(
        decision_result=decision_result,
        risk_validation_result=validation,
        journaled_at=LATEST_AT + timedelta(minutes=20),
        reviewer_result=reviewer_result,
    )
    approval = DecisionApproval(
        journal_entry=journal_entry,
        decision_maker_id="demo-human",
        decision=ApprovalDecision.APPROVED,
        decided_at=LATEST_AT + timedelta(minutes=30),
        comment="Approved for the dashboard demo.",
    )

    return DashboardDemoData(
        managed_history=managed_history,
        benchmark_history=benchmark_history,
        comparison=PerformanceComparison(managed_history, benchmark_history),
        journal_entry=journal_entry,
        approval=approval,
    )


def build_demo_dashboard_view() -> DashboardView:
    data = build_demo_dashboard_data()
    return build_dashboard_view(
        managed_history=data.managed_history,
        benchmark_history=data.benchmark_history,
        comparison=data.comparison,
        journal_entry=data.journal_entry,
        approval=data.approval,
    )
