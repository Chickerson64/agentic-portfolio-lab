from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.policy import (
    EvidenceBand,
    EvidenceCoverageAssessment,
    InvestmentConstitutionArtifact,
    InvestmentConstitutionReference,
    PolicyLoader,
    PositionSizingCase,
    RiskConstitutionVersion,
    RiskEvaluationSnapshot,
    SizingGuidance,
    canonical_policy_json_bytes,
    stable_policy_hash,
)
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio, Position, SecurityIdentity
from agentic_portfolio_lab.domain.provider_fundamentals import (
    FreshnessClass,
    ProviderEndpoint,
    ReliabilityClass,
    ReuseStatus,
)
from agentic_portfolio_lab.domain.research import (
    DerivedMetric,
    EvidenceItem,
    MissingData,
    MissingDataReason,
    PacketComponentCoverage,
    PacketFundamentals,
    ResearchPacket,
    ResearchSection,
)
from agentic_portfolio_lab.domain.valuation import PortfolioValuation, PriceObservation


UTC = timezone.utc
OBSERVED_AT = datetime(2026, 8, 22, 15, 30, tzinfo=UTC)
MARKET_DATE = date(2026, 8, 22)
SOURCE_DATE = date(2026, 8, 21)


def _security() -> SecurityIdentity:
    return SecurityIdentity("CRM", "EQUITY", "NYSE", "USD")


def _other_security() -> SecurityIdentity:
    return SecurityIdentity("META", "EQUITY", "NASDAQ", "USD")


def _eur_security() -> SecurityIdentity:
    return SecurityIdentity("SAP", "EQUITY", "XETRA", "EUR")


def _packet(
    *,
    security: SecurityIdentity | None = None,
    coverage: tuple[PacketComponentCoverage, ...] | None = None,
    derived: tuple[DerivedMetric, ...] | None = None,
) -> ResearchPacket:
    identity = security or _security()
    return ResearchPacket(
        packet_id="packet-crm",
        candidate_id="candidate-crm",
        ticker=identity.ticker,
        security_type=identity.security_type,
        exchange=identity.exchange,
        currency=identity.currency,
        company_name="Salesforce",
        as_of_timestamp=OBSERVED_AT,
        evidence_items=(
            EvidenceItem(
                evidence_id="ev-crm-001",
                source_type="PROVIDER",
                source_title="Alpha Vantage packet",
                source_date=SOURCE_DATE,
                claim_supported="Research packet coverage is attributable.",
            ),
        ),
        sections=(
            ResearchSection(
                section_id="SUMMARY",
                content="Research v2 fundamentals are attached.",
                evidence_ids=("ev-crm-001",),
            ),
        ),
        fundamentals=PacketFundamentals(
            coverage=coverage or _coverage_records(),
            derived=derived or _derived_metrics(),
        ),
    )


def _coverage_records(
    *,
    overview_status: ReuseStatus = ReuseStatus.REUSED_CURRENT,
    overview_freshness: FreshnessClass = FreshnessClass.FRESH,
) -> tuple[PacketComponentCoverage, ...]:
    statuses = {
        ProviderEndpoint.OVERVIEW: (overview_status, overview_freshness),
        ProviderEndpoint.INCOME_STATEMENT: (ReuseStatus.FETCHED_THIS_CYCLE, FreshnessClass.FRESH),
        ProviderEndpoint.BALANCE_SHEET: (ReuseStatus.FETCHED_THIS_CYCLE, FreshnessClass.FRESH),
        ProviderEndpoint.CASH_FLOW: (ReuseStatus.FETCHED_THIS_CYCLE, FreshnessClass.FRESH),
        ProviderEndpoint.EARNINGS: (ReuseStatus.FETCHED_THIS_CYCLE, FreshnessClass.FRESH),
    }
    return tuple(
        PacketComponentCoverage(
            endpoint=endpoint,
            reuse_status=reuse_status,
            freshness=freshness,
            reliability=(
                ReliabilityClass.PROVIDER_COMPUTED
                if endpoint is ProviderEndpoint.OVERVIEW
                else ReliabilityClass.PRIMARY_STATEMENT
            ),
            fiscal_period=date(2026, 6, 30) if endpoint is not ProviderEndpoint.OVERVIEW else None,
            source_date=SOURCE_DATE,
            fetched_at=OBSERVED_AT,
        )
        for endpoint, (reuse_status, freshness) in statuses.items()
    )


def _derived_metrics(*, include_extra_metric: bool = False) -> tuple[DerivedMetric, ...]:
    metrics = []
    for metric_id in (
        "net_debt",
        "current_ratio",
        "gross_margin",
        "operating_margin",
        "net_margin",
        "fcf",
        "ttm_ocf",
        "ttm_capex",
        "ttm_fcf",
        "ttm_net_income",
        "ttm_revenue",
        "cash_conversion",
        "share_count_change",
        "market_cap",
        "enterprise_value",
        "fcf_yield",
    ):
        value: Decimal | MissingData = Decimal("1.23")
        if metric_id == "share_count_change":
            value = MissingData(MissingDataReason.NOT_AVAILABLE, "Quarterly share-count field was absent.")
        metrics.append(
            DerivedMetric(
                metric_id=metric_id,
                value=value,
                formula_id=metric_id,
                input_keys=("field_1", "field_2"),
                reliability=ReliabilityClass.DERIVED_DETERMINISTIC,
                freshness=FreshnessClass.FRESH,
            )
        )
    if include_extra_metric:
        metrics.append(
            DerivedMetric(
                metric_id="unexpected_metric",
                value=Decimal("9"),
                formula_id="unexpected_metric",
                input_keys=("field_1",),
                reliability=ReliabilityClass.DERIVED_DETERMINISTIC,
                freshness=FreshnessClass.FRESH,
            )
        )
    return tuple(metrics)


def _portfolio(*, positions: tuple[Position, ...] = (), cash: Decimal = Decimal("1000")) -> Portfolio:
    return Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Managed",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance("USD", cash),
        created_at=OBSERVED_AT,
        positions=positions,
    )


def _valuation(portfolio: Portfolio, observation: PriceObservation) -> PortfolioValuation:
    return PortfolioValuation.from_portfolio(
        portfolio,
        price_observations=() if not portfolio.positions else (observation,),
        as_of_timestamp=OBSERVED_AT,
        market_date=MARKET_DATE,
        source_price_timestamp=OBSERVED_AT,
        source_provider_identity="TWELVE_DATA",
        price_convention="PROVIDER_ATTRIBUTED_PAPER_QUOTE",
    )


def _observation(*, security: SecurityIdentity | None = None, price: Decimal = Decimal("100")) -> PriceObservation:
    return PriceObservation(
        security=security or _security(),
        observed_price=price,
        market_date=MARKET_DATE,
        observed_at=OBSERVED_AT,
        currency="USD",
        source_provider_identity="TWELVE_DATA",
        price_convention="PROVIDER_ATTRIBUTED_PAPER_QUOTE",
    )


def _investment_reference() -> InvestmentConstitutionReference:
    return InvestmentConstitutionReference.from_constitution(ConstitutionLoader.load_value_manager_constitution())


def test_canonical_policy_json_sorts_keys_and_normalizes_decimals_for_hashing() -> None:
    payload = {"zeta": Decimal("0.10"), "alpha": Decimal("-0.000"), "nested": {"beta": Decimal("1.2300")}}

    canonical = canonical_policy_json_bytes(payload, for_hash=True)

    assert canonical.decode("utf-8") == '{"alpha":"0","nested":{"beta":"1.23"},"zeta":"0.1"}'
    assert stable_policy_hash(payload) == "d00a262e5343b2b091612d832e36039131406f57a020491d9fb8aecbf456bb3c"


def test_policy_hash_is_stable_across_decimal_context_precision() -> None:
    payload = {"weight": Decimal("0.1234567890123456789012345678900")}

    with localcontext() as context:
        context.prec = 6
        low_precision_hash = stable_policy_hash(payload)
    with localcontext() as context:
        context.prec = 50
        high_precision_hash = stable_policy_hash(payload)

    assert low_precision_hash == high_precision_hash


def test_same_version_with_different_value_risk_content_produces_different_hash() -> None:
    investment = _investment_reference()
    base = PolicyLoader.load_value_manager_risk_constitution_v1(
        compatible_investment_constitution=investment
    )
    changed = replace(
        base,
        sizing_guidance=SizingGuidance(
            typical_starter_weight_min=Decimal("0.06"),
            typical_starter_weight_max=Decimal("0.10"),
            minimum_cash_reserve=None,
            confidence_has_sizing_authority=False,
        ),
        content_hash=None,
    )

    assert base.risk_constitution_version == changed.risk_constitution_version
    assert base.content_hash != changed.content_hash


def test_universal_policy_types_allow_non_value_namespaces_without_loader_activation() -> None:
    artifact = InvestmentConstitutionArtifact(
        schema_version="policy-domain.v1",
        constitution_version="growth-v1.0.0",
        manager_type="GROWTH",
        name="Growth Constitution",
        description="Generic future-manager artifact.",
        content="Future prose artifact.",
        loading_source="docs/growth-manager-constitution.md",
    )
    reference = InvestmentConstitutionReference(
        constitution_version=artifact.constitution_version,
        manager_type=artifact.manager_type,
        artifact=artifact,
        loading_source=artifact.loading_source,
        content_hash=stable_policy_hash(artifact.artifact_payload(for_hash=True)),
    )
    version = RiskConstitutionVersion("growth-risk-v1.0.0")

    assert reference.manager_type == "GROWTH"
    assert version.value == "growth-risk-v1.0.0"


def test_value_v1_loader_is_immutable_against_caller_supplied_constitution_variants() -> None:
    approved = _investment_reference()
    altered_artifact = replace(approved.artifact, content=f"{approved.artifact.content}\nvariant")
    altered_reference = InvestmentConstitutionReference(
        constitution_version=altered_artifact.constitution_version,
        manager_type=altered_artifact.manager_type,
        artifact=altered_artifact,
        loading_source=altered_artifact.loading_source,
        content_hash=stable_policy_hash(altered_artifact.artifact_payload(for_hash=True)),
    )

    with pytest.raises(ValueError, match="single approved VALUE constitution artifact"):
        PolicyLoader.load_value_manager_risk_constitution_v1(
            compatible_investment_constitution=altered_reference
        )


def test_loading_source_changes_do_not_change_policy_hash() -> None:
    investment = _investment_reference()
    risk = PolicyLoader.load_value_manager_risk_constitution_v1(
        compatible_investment_constitution=investment
    )

    moved = replace(risk, loading_source="src/agentic_portfolio_lab/domain/policy_alias.py", content_hash=None)

    assert moved.content_hash == risk.content_hash


def test_manager_risk_constitution_requires_exact_investment_constitution_hash_match() -> None:
    investment = _investment_reference()
    risk = PolicyLoader.load_value_manager_risk_constitution_v1(
        compatible_investment_constitution=investment
    )
    altered_constitution = replace(
        investment.artifact,
        content=f"{investment.artifact.content}\nCompatibility drift.",
    )
    mismatched_investment = InvestmentConstitutionReference(
        constitution_version=altered_constitution.constitution_version,
        manager_type=altered_constitution.manager_type,
        artifact=altered_constitution,
        loading_source=altered_constitution.loading_source,
        content_hash=stable_policy_hash(altered_constitution.artifact_payload(for_hash=True)),
    )

    assert risk.compatible_with(investment)
    assert not risk.compatible_with(mismatched_investment)
    with pytest.raises(ValueError, match="not compatible"):
        risk.require_compatible(mismatched_investment)


def test_value_v1_baseline_band_qualifies_with_explicit_missing_data_metric() -> None:
    risk = PolicyLoader.load_value_manager_risk_constitution_v1(
        compatible_investment_constitution=_investment_reference()
    )

    assessment = EvidenceCoverageAssessment.evaluate(
        _packet(),
        security=_security(),
        band_definitions=risk.evidence_bands,
    )

    assert assessment.exact_security_identity_match
    assert assessment.baseline_qualified
    assert assessment.eligible_band is EvidenceBand.BASELINE_RESEARCH_V2
    assert any(metric.metric_id == "share_count_change" and isinstance(metric.value, MissingData) for metric in assessment.derived_metrics)
    enhanced = next(item for item in assessment.assessed_bands if item.band is EvidenceBand.ENHANCED_RESEARCH_UNDEFINED)
    assert not enhanced.reachable
    assert not enhanced.eligible
    assert assessment.research_as_of_timestamp == OBSERVED_AT
    assert assessment.evidence_items[0].evidence_id == "ev-crm-001"


def test_value_v1_artifact_locks_every_approved_policy_value() -> None:
    risk = PolicyLoader.load_value_manager_risk_constitution_v1(
        compatible_investment_constitution=_investment_reference()
    )
    baseline = next(item for item in risk.evidence_bands if item.band is EvidenceBand.BASELINE_RESEARCH_V2)
    enhanced = next(item for item in risk.evidence_bands if item.band is EvidenceBand.ENHANCED_RESEARCH_UNDEFINED)

    assert risk.sizing_guidance.typical_starter_weight_min == Decimal("0.05")
    assert risk.sizing_guidance.typical_starter_weight_max == Decimal("0.10")
    assert risk.sizing_guidance.minimum_cash_reserve is None
    assert not risk.sizing_guidance.confidence_has_sizing_authority
    assert baseline.maximum_initial_target_weight == Decimal("0.10")
    assert enhanced.maximum_initial_target_weight == Decimal("0.15")
    assert risk.sizing_limits.maximum_total_single_name_target_weight == Decimal("0.25")
    assert risk.sizing_limits.maximum_one_cycle_add_weight == Decimal("0.05")


def test_stale_overview_or_unknown_metric_set_disqualifies_baseline_band() -> None:
    risk = PolicyLoader.load_value_manager_risk_constitution_v1(
        compatible_investment_constitution=_investment_reference()
    )

    stale = EvidenceCoverageAssessment.evaluate(
        _packet(coverage=_coverage_records(overview_status=ReuseStatus.STALE, overview_freshness=FreshnessClass.STALE)),
        security=_security(),
        band_definitions=risk.evidence_bands,
    )
    extra_metric = EvidenceCoverageAssessment.evaluate(
        _packet(derived=_derived_metrics(include_extra_metric=True)),
        security=_security(),
        band_definitions=risk.evidence_bands,
    )

    assert not stale.baseline_qualified
    assert "OVERVIEW coverage is not current" in next(
        item for item in stale.assessed_bands if item.band is EvidenceBand.BASELINE_RESEARCH_V2
    ).disqualifications
    assert not extra_metric.baseline_qualified
    assert "derived metrics include an unknown metric set" in next(
        item for item in extra_metric.assessed_bands if item.band is EvidenceBand.BASELINE_RESEARCH_V2
    ).disqualifications


def test_stale_or_misidentified_derived_metrics_disqualify_baseline_band() -> None:
    risk = PolicyLoader.load_value_manager_risk_constitution_v1(
        compatible_investment_constitution=_investment_reference()
    )
    stale_metric = replace(_derived_metrics()[0], freshness=FreshnessClass.STALE)
    wrong_formula = replace(_derived_metrics()[1], formula_id="current_ratio-v2")
    metrics = (stale_metric, wrong_formula, *_derived_metrics()[2:])

    assessment = EvidenceCoverageAssessment.evaluate(
        _packet(derived=metrics),
        security=_security(),
        band_definitions=risk.evidence_bands,
    )

    disqualifications = next(
        item for item in assessment.assessed_bands if item.band is EvidenceBand.BASELINE_RESEARCH_V2
    ).disqualifications
    assert not assessment.baseline_qualified
    assert "net_debt freshness does not match the baseline contract" in disqualifications
    assert "current_ratio formula identity does not match the baseline contract" in disqualifications


def test_mismatched_endpoint_reliability_disqualifies_baseline_band() -> None:
    risk = PolicyLoader.load_value_manager_risk_constitution_v1(
        compatible_investment_constitution=_investment_reference()
    )
    bad_coverage = (
        replace(_coverage_records()[0], reliability=ReliabilityClass.PRIMARY_STATEMENT),
        *_coverage_records()[1:],
    )

    assessment = EvidenceCoverageAssessment.evaluate(
        _packet(coverage=bad_coverage),
        security=_security(),
        band_definitions=risk.evidence_bands,
    )

    disqualifications = next(
        item for item in assessment.assessed_bands if item.band is EvidenceBand.BASELINE_RESEARCH_V2
    ).disqualifications
    assert not assessment.baseline_qualified
    assert "OVERVIEW reliability does not match the baseline contract" in disqualifications


def test_evidence_assessment_rejects_forged_identity_or_band_results() -> None:
    risk = PolicyLoader.load_value_manager_risk_constitution_v1(
        compatible_investment_constitution=_investment_reference()
    )
    packet = _packet()
    canonical = EvidenceCoverageAssessment.evaluate(
        packet,
        security=_security(),
        band_definitions=risk.evidence_bands,
    )
    baseline = next(item for item in canonical.assessed_bands if item.band is EvidenceBand.BASELINE_RESEARCH_V2)

    with pytest.raises(ValueError, match="exact_security_identity_match"):
        EvidenceCoverageAssessment(
            security=canonical.security,
            packet_id=canonical.packet_id,
            research_as_of_timestamp=canonical.research_as_of_timestamp,
            packet_ticker=canonical.packet_ticker,
            packet_security_type=canonical.packet_security_type,
            packet_exchange=canonical.packet_exchange,
            packet_currency=canonical.packet_currency,
            exact_security_identity_match=False,
            evidence_items=canonical.evidence_items,
            endpoint_coverage=canonical.endpoint_coverage,
            derived_metrics=canonical.derived_metrics,
            band_definitions=canonical.band_definitions,
            assessed_bands=canonical.assessed_bands,
        )
    with pytest.raises(ValueError, match="assessed_bands"):
        EvidenceCoverageAssessment(
            security=canonical.security,
            packet_id=canonical.packet_id,
            research_as_of_timestamp=canonical.research_as_of_timestamp,
            packet_ticker=canonical.packet_ticker,
            packet_security_type=canonical.packet_security_type,
            packet_exchange=canonical.packet_exchange,
            packet_currency=canonical.packet_currency,
            exact_security_identity_match=canonical.exact_security_identity_match,
            evidence_items=canonical.evidence_items,
            endpoint_coverage=canonical.endpoint_coverage,
            derived_metrics=canonical.derived_metrics,
            band_definitions=canonical.band_definitions,
            assessed_bands=(replace(baseline, eligible=False, disqualifications=("forged",)),),
        )
    with pytest.raises(TypeError, match="exact_security_identity_match"):
        EvidenceCoverageAssessment(
            security=canonical.security,
            packet_id=canonical.packet_id,
            research_as_of_timestamp=canonical.research_as_of_timestamp,
            packet_ticker=canonical.packet_ticker,
            packet_security_type=canonical.packet_security_type,
            packet_exchange=canonical.packet_exchange,
            packet_currency=canonical.packet_currency,
            exact_security_identity_match=1,  # type: ignore[arg-type]
            evidence_items=canonical.evidence_items,
            endpoint_coverage=canonical.endpoint_coverage,
            derived_metrics=canonical.derived_metrics,
            band_definitions=canonical.band_definitions,
            assessed_bands=canonical.assessed_bands,
        )
    with pytest.raises(TypeError, match="eligible"):
        EvidenceCoverageAssessment(
            security=canonical.security,
            packet_id=canonical.packet_id,
            research_as_of_timestamp=canonical.research_as_of_timestamp,
            packet_ticker=canonical.packet_ticker,
            packet_security_type=canonical.packet_security_type,
            packet_exchange=canonical.packet_exchange,
            packet_currency=canonical.packet_currency,
            exact_security_identity_match=canonical.exact_security_identity_match,
            evidence_items=canonical.evidence_items,
            endpoint_coverage=canonical.endpoint_coverage,
            derived_metrics=canonical.derived_metrics,
            band_definitions=canonical.band_definitions,
            assessed_bands=(replace(baseline, eligible=1),),  # type: ignore[arg-type]
        )


def test_risk_snapshot_from_state_captures_initial_position_context_without_policy_enforcement() -> None:
    security = _security()
    observation = _observation(security=security)
    portfolio = _portfolio()
    valuation = _valuation(portfolio, observation)
    risk = PolicyLoader.load_value_manager_risk_constitution_v1(
        compatible_investment_constitution=_investment_reference()
    )
    coverage = EvidenceCoverageAssessment.evaluate(
        _packet(security=security),
        security=security,
        band_definitions=risk.evidence_bands,
    )

    snapshot = RiskEvaluationSnapshot.from_state(
        portfolio=portfolio,
        valuation=valuation,
        security=security,
        price_observation=observation,
        evidence_coverage=coverage,
        proposed_target_weight=Decimal("0.25"),
    )

    assert snapshot.position_sizing_case is PositionSizingCase.INITIAL_POSITION
    assert snapshot.current_position_weight == Decimal("0")
    assert snapshot.proposed_target_weight == Decimal("0.25")
    assert snapshot.proposed_post_trade_weight == Decimal("0.25")
    assert snapshot.proposed_weight_delta == Decimal("0.25")
    assert snapshot.proposed_post_trade_position_value == Decimal("250.00")
    assert snapshot.proposed_post_trade_cash_value == Decimal("750.00")
    assert snapshot.proposed_post_trade_cash_weight == Decimal("0.75")


def test_risk_snapshot_requires_synchronized_identity_and_add_classification() -> None:
    security = _security()
    position = Position(security, Decimal("2"), Decimal("160"), Decimal("100"))
    portfolio = _portfolio(positions=(position,), cash=Decimal("800"))
    observation = _observation(security=security)
    valuation = _valuation(portfolio, observation)
    risk = PolicyLoader.load_value_manager_risk_constitution_v1(
        compatible_investment_constitution=_investment_reference()
    )
    coverage = EvidenceCoverageAssessment.evaluate(
        _packet(security=security),
        security=security,
        band_definitions=risk.evidence_bands,
    )

    snapshot = RiskEvaluationSnapshot.from_state(
        portfolio=portfolio,
        valuation=valuation,
        security=security,
        price_observation=observation,
        evidence_coverage=coverage,
        proposed_target_weight=Decimal("0.25"),
    )

    assert snapshot.position_sizing_case is PositionSizingCase.ADD_TO_POSITION
    assert snapshot.current_position_weight == Decimal("0.2")
    assert snapshot.proposed_weight_delta == Decimal("0.05")
    assert snapshot.proposed_post_trade_cash_value == Decimal("750.00")
    with pytest.raises(ValueError, match="price_observation security"):
        RiskEvaluationSnapshot.from_state(
            portfolio=portfolio,
            valuation=valuation,
            security=security,
            price_observation=_observation(security=_other_security()),
            evidence_coverage=coverage,
            proposed_target_weight=Decimal("0.25"),
        )
    with pytest.raises(ValueError, match="security currency"):
        RiskEvaluationSnapshot.from_state(
            portfolio=portfolio,
            valuation=valuation,
            security=_eur_security(),
            price_observation=_observation(security=_eur_security(), price=Decimal("120")),
            evidence_coverage=EvidenceCoverageAssessment.evaluate(
                _packet(security=_eur_security()),
                security=_eur_security(),
                band_definitions=risk.evidence_bands,
            ),
            proposed_target_weight=Decimal("0.25"),
        )
    with pytest.raises(ValueError, match="observed_price"):
        RiskEvaluationSnapshot.from_state(
            portfolio=portfolio,
            valuation=valuation,
            security=security,
            price_observation=replace(observation, observed_price=Decimal("120")),
            evidence_coverage=coverage,
            proposed_target_weight=Decimal("0.25"),
        )
