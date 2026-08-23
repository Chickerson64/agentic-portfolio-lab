from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from dataclasses import replace
from uuid import uuid4

import pytest
from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.policy import (
    EvidenceCoverageAssessment,
    InvestmentConstitutionReference,
    PolicyLoader,
    RiskEvaluationSnapshot,
)
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio, SecurityIdentity
from agentic_portfolio_lab.domain.provider_fundamentals import (
    FreshnessClass,
    ProviderEndpoint,
    ReliabilityClass,
    ReuseStatus,
)
from agentic_portfolio_lab.domain.recommendations import (
    PortfolioRecommendation,
    RecommendationEvidenceReference,
    ReviewTrigger,
)
from agentic_portfolio_lab.domain.research import (
    DerivedMetric,
    EvidenceItem,
    MissingData,
    MissingDataReason,
    PacketComponentCoverage,
    PacketFundamentals,
    ResearchBatch,
    ResearchPacket,
    ResearchSection,
)
from agentic_portfolio_lab.domain.risk_validation import (
    ManagerAssessmentSeverity,
    RiskRuleLayer,
    TwoLayerRiskEvaluator,
)
from agentic_portfolio_lab.domain.valuation import PortfolioValuation, PriceObservation
from agentic_portfolio_lab.domain.value_manager import ValueManagerDecisionContext
from agentic_portfolio_lab.domain.value_manager_workflow import ValueManagerDecisionResult


UTC = timezone.utc
PRODUCED_AT = datetime(2026, 8, 23, 0, 0, tzinfo=UTC)
VALIDATED_AT = datetime(2026, 8, 23, 0, 5, tzinfo=UTC)


def _security(*, security_type: str = "EQUITY") -> SecurityIdentity:
    return SecurityIdentity("CRM", security_type, "NYSE", "USD")


def _portfolio() -> Portfolio:
    return Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Managed",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance("USD", Decimal("1000")),
        created_at=PRODUCED_AT,
    )


def _coverage() -> tuple[PacketComponentCoverage, ...]:
    reliabilities = {
        ProviderEndpoint.OVERVIEW: ReliabilityClass.PROVIDER_COMPUTED,
        ProviderEndpoint.INCOME_STATEMENT: ReliabilityClass.PRIMARY_STATEMENT,
        ProviderEndpoint.BALANCE_SHEET: ReliabilityClass.PRIMARY_STATEMENT,
        ProviderEndpoint.CASH_FLOW: ReliabilityClass.PRIMARY_STATEMENT,
        ProviderEndpoint.EARNINGS: ReliabilityClass.PRIMARY_STATEMENT,
    }
    return tuple(
        PacketComponentCoverage(
            endpoint=endpoint,
            reuse_status=(ReuseStatus.REUSED_CURRENT if endpoint is ProviderEndpoint.OVERVIEW else ReuseStatus.FETCHED_THIS_CYCLE),
            freshness=FreshnessClass.FRESH,
            reliability=reliability,
            fiscal_period=None if endpoint is ProviderEndpoint.OVERVIEW else date(2026, 6, 30),
            source_date=date(2026, 8, 22),
            fetched_at=PRODUCED_AT,
        )
        for endpoint, reliability in reliabilities.items()
    )


def _metrics() -> tuple[DerivedMetric, ...]:
    names = (
        "net_debt", "current_ratio", "gross_margin", "operating_margin", "net_margin", "fcf",
        "ttm_ocf", "ttm_capex", "ttm_fcf", "ttm_net_income", "ttm_revenue", "cash_conversion",
        "share_count_change", "market_cap", "enterprise_value", "fcf_yield",
    )
    return tuple(
        DerivedMetric(
            metric_id=name,
            value=(MissingData(MissingDataReason.NOT_AVAILABLE, "explicitly unavailable") if name == "share_count_change" else Decimal("1")),
            formula_id=name,
            input_keys=("source",),
            reliability=ReliabilityClass.DERIVED_DETERMINISTIC,
            freshness=FreshnessClass.FRESH,
        )
        for name in names
    )


def _packet(*, security: SecurityIdentity | None = None) -> ResearchPacket:
    identity = security or _security()
    evidence = EvidenceItem("ev_crm", "PROVIDER", "Research v2", date(2026, 8, 22), "Attributable CRM fundamentals.")
    return ResearchPacket(
        packet_id="packet_crm",
        candidate_id="candidate_crm",
        ticker=identity.ticker,
        security_type=identity.security_type,
        exchange=identity.exchange,
        currency=identity.currency,
        company_name="Salesforce",
        as_of_timestamp=PRODUCED_AT,
        evidence_items=(evidence,),
        sections=(ResearchSection("SUMMARY", "Research v2 evidence.", (evidence.evidence_id,)),),
        fundamentals=PacketFundamentals(coverage=_coverage(), derived=_metrics()),
    )


def _decision(portfolio: Portfolio, *, target_weight: Decimal, confidence: int = 70, security: SecurityIdentity | None = None) -> ValueManagerDecisionResult:
    packet = _packet(security=security)
    batch = ResearchBatch(
        batch_id="batch_crm",
        decision_cycle_id=uuid4(),
        portfolio_id=portfolio.portfolio_id,
        manager_type="VALUE",
        created_at=PRODUCED_AT,
        as_of_timestamp=PRODUCED_AT,
        packets=(packet,),
    )
    evidence = packet.evidence_items[0]
    recommendation = PortfolioRecommendation(
        action="BUY",
        ticker="CRM",
        target_weight=target_weight,
        decision_rationale="The evidence supports the proposal.",
        investment_thesis="CRM can compound cash flow.",
        valuation="Valuation is considered acceptable.",
        risks=("Execution risk.",),
        confidence_score=confidence,
        evidence=(RecommendationEvidenceReference(evidence.evidence_id, evidence.source_type, evidence.source_title, evidence.source_date, evidence.claim_supported),),
        why_not_spy="The active thesis is more compelling.",
        thesis_invalidation=("Cash flow weakens.",),
        review_triggers=(ReviewTrigger("EVENT_BASED", "Review at earnings."),),
    )
    return ValueManagerDecisionResult(
        context=ValueManagerDecisionContext(
            portfolio=portfolio,
            research_batch=batch,
            constitution=ConstitutionLoader.load_value_manager_constitution_v2(),
        ),
        recommendation=recommendation,
        produced_at=PRODUCED_AT,
    )


def _observation(*, security: SecurityIdentity | None = None) -> PriceObservation:
    identity = security or _security()
    return PriceObservation(identity, Decimal("100"), VALIDATED_AT.date(), VALIDATED_AT, "USD", "test-provider", "close")


def _evaluation(target_weight: Decimal, *, confidence: int = 70, security: SecurityIdentity | None = None):
    identity = security or _security()
    portfolio = _portfolio()
    decision = _decision(portfolio, target_weight=target_weight, confidence=confidence, security=identity)
    observation = _observation(security=identity)
    investment = InvestmentConstitutionReference.from_constitution(ConstitutionLoader.load_value_manager_constitution_v2())
    risk = PolicyLoader.load_value_manager_risk_constitution_v2(compatible_investment_constitution=investment)
    coverage = EvidenceCoverageAssessment.evaluate(_packet(security=identity), security=identity, band_definitions=risk.evidence_bands)
    valuation = PortfolioValuation.from_portfolio(
        portfolio,
        price_observations=(),
        as_of_timestamp=VALIDATED_AT,
        market_date=VALIDATED_AT.date(),
        source_price_timestamp=VALIDATED_AT,
        source_provider_identity="test-provider",
        price_convention="close",
    )
    snapshot = RiskEvaluationSnapshot.from_state(
        portfolio=portfolio,
        valuation=valuation,
        security=identity,
        price_observation=observation,
        evidence_coverage=coverage,
        proposed_target_weight=target_weight,
    )
    return TwoLayerRiskEvaluator().evaluate(
        decision,
        validation_timestamp=VALIDATED_AT,
        price_observation=observation,
        system_safety_envelope=PolicyLoader.load_system_safety_envelope_v1(),
        manager_risk_constitution=risk,
        risk_evaluation_snapshot=snapshot,
    )


def _finding(result, finding_id: str):
    assert result.manager_assessment is not None
    return next(finding for finding in result.manager_assessment.findings if finding.finding_id == finding_id)


def test_crm_twenty_five_percent_is_safe_but_materially_advisory() -> None:
    result = _evaluation(Decimal("0.25"), confidence=70)

    assert result.passed
    assert result.validated_trade is not None
    assert result.safety_validation.decision_result.recommendation.target_weight == Decimal("0.25")
    assert all(rule.layer is RiskRuleLayer.SYSTEM_SAFETY for rule in result.safety_validation.rule_results)
    assert all(rule.passed for rule in result.safety_validation.rule_results)
    deviation = _finding(result, "NORMAL_STARTER_GUIDANCE_DEVIATION")
    assert deviation.severity is ManagerAssessmentSeverity.MATERIAL
    assert deviation.actual_value == Decimal("0.25")
    assert deviation.guidance_value == Decimal("0.10")
    assert result.manager_assessment is not None and result.manager_assessment.requires_stronger_justification


def test_eighty_and_one_hundred_percent_funded_buys_remain_safe_with_advisory_findings() -> None:
    for target_weight in (Decimal("0.80"), Decimal("1")):
        result = _evaluation(target_weight)
        assert result.passed
        assert result.validated_trade is not None
        assert result.validated_trade.proposal.target_weight == target_weight
        assert _finding(result, "NORMAL_STARTER_GUIDANCE_DEVIATION").severity is ManagerAssessmentSeverity.MATERIAL


def test_confidence_does_not_change_safety_or_advisory_guidance() -> None:
    low = _evaluation(Decimal("0.25"), confidence=1)
    high = _evaluation(Decimal("0.25"), confidence=100)

    assert low.passed and high.passed
    assert low.validated_trade is not None and high.validated_trade is not None
    assert low.validated_trade.proposal.target_weight == high.validated_trade.proposal.target_weight
    assert low.validated_trade.proposal.proposed_notional_amount == high.validated_trade.proposal.proposed_notional_amount
    assert low.validated_trade.proposal.proposed_quantity == high.validated_trade.proposal.proposed_quantity
    assert _finding(low, "NORMAL_STARTER_GUIDANCE_DEVIATION") == _finding(high, "NORMAL_STARTER_GUIDANCE_DEVIATION")


def test_unsupported_instrument_fails_system_safety_without_advisory_gating() -> None:
    result = _evaluation(Decimal("0.25"), security=_security(security_type="OPTION"))

    assert not result.passed
    assert result.validated_trade is None
    mechanics = next(rule for rule in result.safety_validation.rule_results if rule.rule_id == "PROHIBITED_TRADE_MECHANICS")
    assert not mechanics.passed
    assert result.manager_assessment is not None


def test_current_buy_hold_contract_does_not_model_rotation_actions() -> None:
    result = _evaluation(Decimal("0.80"))

    assert result.safety_validation.decision_result.recommendation.action.value == "BUY"
    assert result.safety_validation.validated_trade is not None
    assert all(rule.rule_id != "SELL_SUPPORTED" for rule in result.safety_validation.rule_results)


def test_incompatible_constitution_artifacts_fail_assessment_configuration_not_safety() -> None:
    portfolio = _portfolio()
    decision = _decision(portfolio, target_weight=Decimal("0.25"))
    observation = _observation()
    legacy_investment = InvestmentConstitutionReference.from_constitution(ConstitutionLoader.load_value_manager_constitution())
    legacy_risk = PolicyLoader.load_value_manager_risk_constitution_v1(
        compatible_investment_constitution=legacy_investment
    )
    advisory_investment = InvestmentConstitutionReference.from_constitution(ConstitutionLoader.load_value_manager_constitution_v2())
    advisory_risk = PolicyLoader.load_value_manager_risk_constitution_v2(
        compatible_investment_constitution=advisory_investment
    )
    coverage = EvidenceCoverageAssessment.evaluate(_packet(), security=_security(), band_definitions=advisory_risk.evidence_bands)
    snapshot = RiskEvaluationSnapshot.from_state(
        portfolio=portfolio,
        valuation=PortfolioValuation.from_portfolio(
            portfolio,
            price_observations=(),
            as_of_timestamp=VALIDATED_AT,
            market_date=VALIDATED_AT.date(),
            source_price_timestamp=VALIDATED_AT,
            source_provider_identity="test-provider",
            price_convention="close",
        ),
        security=_security(),
        price_observation=observation,
        evidence_coverage=coverage,
        proposed_target_weight=Decimal("0.25"),
    )

    with pytest.raises(ValueError, match="not compatible"):
        TwoLayerRiskEvaluator().evaluate(
            decision,
            validation_timestamp=VALIDATED_AT,
            price_observation=observation,
            manager_risk_constitution=legacy_risk,
            risk_evaluation_snapshot=snapshot,
        )


def test_lane_two_rejects_unimplemented_future_system_safety_envelope_semantics() -> None:
    approved = PolicyLoader.load_system_safety_envelope_v1()
    changed = replace(approved, supported_actions=("HOLD",), content_hash=None)
    portfolio = _portfolio()
    decision = _decision(portfolio, target_weight=Decimal("0.25"))

    with pytest.raises(ValueError, match="only the approved system-safety-v1.0.0 envelope"):
        TwoLayerRiskEvaluator().evaluate(
            decision,
            validation_timestamp=VALIDATED_AT,
            price_observation=_observation(),
            system_safety_envelope=changed,
        )


def test_advisory_snapshot_must_bind_to_the_validated_quote_and_packet() -> None:
    portfolio = _portfolio()
    decision = _decision(portfolio, target_weight=Decimal("0.25"))
    observation = _observation()
    investment = InvestmentConstitutionReference.from_constitution(ConstitutionLoader.load_value_manager_constitution_v2())
    risk = PolicyLoader.load_value_manager_risk_constitution_v2(compatible_investment_constitution=investment)
    coverage = EvidenceCoverageAssessment.evaluate(_packet(), security=_security(), band_definitions=risk.evidence_bands)
    mismatched_quote = replace(observation, observed_price=Decimal("120"))
    snapshot = RiskEvaluationSnapshot.from_state(
        portfolio=portfolio,
        valuation=PortfolioValuation.from_portfolio(
            portfolio,
            price_observations=(),
            as_of_timestamp=VALIDATED_AT,
            market_date=VALIDATED_AT.date(),
            source_price_timestamp=VALIDATED_AT,
            source_provider_identity="test-provider",
            price_convention="close",
        ),
        security=_security(),
        price_observation=mismatched_quote,
        evidence_coverage=coverage,
        proposed_target_weight=Decimal("0.25"),
    )

    with pytest.raises(ValueError, match="price_observation must match"):
        TwoLayerRiskEvaluator().evaluate(
            decision,
            validation_timestamp=VALIDATED_AT,
            price_observation=observation,
            manager_risk_constitution=risk,
            risk_evaluation_snapshot=snapshot,
        )
