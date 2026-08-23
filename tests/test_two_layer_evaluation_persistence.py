"""Lane 3 durable two-layer evaluation lineage and legacy compatibility."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from agentic_portfolio_lab.application.local_state import PersistedRunState
from agentic_portfolio_lab.application.local_state_codec import decode_run_state, encode
from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
from agentic_portfolio_lab.domain.policy import (
    CurrentPolicyReference,
    EvidenceCoverageAssessment,
    InvestmentConstitutionReference,
    PolicyLoader,
    RiskEvaluationSnapshot,
    LegacyPolicyReference,
)
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.provider_fundamentals import FreshnessClass, ProviderEndpoint, ReliabilityClass, ReuseStatus
from agentic_portfolio_lab.domain.recommendations import PortfolioRecommendation, RecommendationEvidenceReference, ReviewTrigger
from agentic_portfolio_lab.domain.research import DerivedMetric, EvidenceItem, MissingData, MissingDataReason, PacketComponentCoverage, PacketFundamentals, ResearchBatch, ResearchPacket, ResearchSection
from agentic_portfolio_lab.domain.risk_validation import ManagerAssessmentSeverity, TwoLayerRiskEvaluator
from agentic_portfolio_lab.domain.valuation import PortfolioValuation, PriceObservation
from agentic_portfolio_lab.domain.value_manager import ValueManagerDecisionContext
from agentic_portfolio_lab.domain.value_manager_workflow import ValueManagerDecisionResult
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore


UTC = timezone.utc
AT = datetime(2026, 8, 23, 0, 5, tzinfo=UTC)


def _packet() -> ResearchPacket:
    evidence = EvidenceItem("ev_crm", "PROVIDER", "Research v2", date(2026, 8, 22), "Attributable CRM fundamentals.")
    coverage = tuple(
        PacketComponentCoverage(
            endpoint=endpoint,
            reuse_status=ReuseStatus.REUSED_CURRENT if endpoint is ProviderEndpoint.OVERVIEW else ReuseStatus.FETCHED_THIS_CYCLE,
            freshness=FreshnessClass.FRESH,
            reliability=ReliabilityClass.PROVIDER_COMPUTED if endpoint is ProviderEndpoint.OVERVIEW else ReliabilityClass.PRIMARY_STATEMENT,
            fiscal_period=None if endpoint is ProviderEndpoint.OVERVIEW else date(2026, 6, 30),
            source_date=date(2026, 8, 22), fetched_at=AT,
        )
        for endpoint in ProviderEndpoint
    )
    metric_ids = ("net_debt", "current_ratio", "gross_margin", "operating_margin", "net_margin", "fcf", "ttm_ocf", "ttm_capex", "ttm_fcf", "ttm_net_income", "ttm_revenue", "cash_conversion", "share_count_change", "market_cap", "enterprise_value", "fcf_yield")
    metrics = tuple(DerivedMetric(metric_id, MissingData(MissingDataReason.NOT_AVAILABLE, "explicitly unavailable") if metric_id == "share_count_change" else Decimal("1"), metric_id, ("source",), ReliabilityClass.DERIVED_DETERMINISTIC, FreshnessClass.FRESH) for metric_id in metric_ids)
    return ResearchPacket(
        packet_id="packet_crm", candidate_id="candidate_crm", ticker="CRM", security_type="EQUITY",
        exchange="NYSE", currency="USD", company_name="Salesforce", as_of_timestamp=AT,
        evidence_items=(evidence,), sections=(ResearchSection("SUMMARY", "Research v2 evidence.", (evidence.evidence_id,)),),
        fundamentals=PacketFundamentals(coverage=coverage, derived=metrics),
    )


def _evaluated_state(base: PersistedRunState, target: Decimal) -> PersistedRunState:
    portfolio = base.managed_portfolio
    packet = _packet()
    batch = ResearchBatch("batch_crm", uuid4(), portfolio.portfolio_id, "VALUE", AT, AT, (packet,))
    evidence = packet.evidence_items[0]
    recommendation = PortfolioRecommendation("BUY", "CRM", target, "Evidence supports the proposal.", "CRM can compound cash flow.", "Valuation considered acceptable.", ("Execution risk.",), 70, (RecommendationEvidenceReference(evidence.evidence_id, evidence.source_type, evidence.source_title, evidence.source_date, evidence.claim_supported),), "The active thesis is more compelling.", ("Cash flow weakens.",), (ReviewTrigger("EVENT_BASED", "Review at earnings."),))
    decision = ValueManagerDecisionResult(ValueManagerDecisionContext(portfolio, batch, ConstitutionLoader.load_value_manager_constitution_v2()), recommendation, AT)
    security = SecurityIdentity("CRM", "EQUITY", "NYSE", "USD")
    quote = PriceObservation(security, Decimal("100"), AT.date(), AT, "USD", "test-provider", "close")
    investment = InvestmentConstitutionReference.from_constitution(decision.context.constitution)
    risk = PolicyLoader.load_value_manager_risk_constitution_v2(compatible_investment_constitution=investment)
    coverage = EvidenceCoverageAssessment.evaluate(packet, security=security, band_definitions=risk.evidence_bands)
    valuation = PortfolioValuation.from_portfolio(portfolio, (), as_of_timestamp=AT, market_date=AT.date(), source_price_timestamp=AT, source_provider_identity="test-provider", price_convention="close")
    snapshot = RiskEvaluationSnapshot.from_state(portfolio=portfolio, valuation=valuation, security=security, price_observation=quote, evidence_coverage=coverage, proposed_target_weight=target)
    envelope = PolicyLoader.load_system_safety_envelope_v1()
    evaluation = TwoLayerRiskEvaluator().evaluate(decision, validation_timestamp=AT, price_observation=quote, system_safety_envelope=envelope, manager_risk_constitution=risk, risk_evaluation_snapshot=snapshot)
    journal = DecisionJournalEntry(decision, evaluation.safety_validation, AT, policy_reference=CurrentPolicyReference(investment, envelope, risk), two_layer_evaluation=evaluation)
    return replace(base, price_observations=(quote,), research_batches=(batch,), journal_entries=(journal,))


@pytest.mark.parametrize("target", (Decimal("0.25"), Decimal("0.80"), Decimal("1")))
def test_current_two_layer_evaluations_reopen_without_advisory_gate(tmp_path: Path, target: Decimal) -> None:
    store = SQLiteLocalRunStore(tmp_path / "state.sqlite")
    base = store.initialize_run(initialized_at=AT)
    state = _evaluated_state(base, target)
    store.save_transition(state)

    reopened = store.open_run()
    assert reopened is not None
    journal = reopened.journal_entries[0]
    assert journal.risk_validation_result.passed
    assert journal.risk_validation_result.validated_trade is not None
    assert journal.risk_validation_result.validated_trade.proposal.target_weight == target
    assert isinstance(journal.policy_reference, CurrentPolicyReference)
    assert journal.policy_reference.investment_constitution.content_hash == InvestmentConstitutionReference.from_constitution(ConstitutionLoader.load_value_manager_constitution_v2()).content_hash
    assert journal.policy_reference.manager_risk_constitution.content_hash == PolicyLoader.load_value_manager_risk_constitution_v2(compatible_investment_constitution=journal.policy_reference.investment_constitution).content_hash
    assert journal.policy_reference.system_safety_envelope.content_hash == PolicyLoader.load_system_safety_envelope_v1().content_hash
    assert journal.policy_reference.system_safety_envelope.loading_source == PolicyLoader.load_system_safety_envelope_v1().loading_source
    assert journal.two_layer_evaluation is not None and journal.two_layer_evaluation.passed
    assessment = journal.two_layer_evaluation.manager_assessment
    assert assessment is not None
    deviation = next(item for item in assessment.findings if item.finding_id == "NORMAL_STARTER_GUIDANCE_DEVIATION")
    assert deviation.severity is (ManagerAssessmentSeverity.MATERIAL if target > Decimal("0.10") else ManagerAssessmentSeverity.INFO)
    assert deviation.actual_value == target
    assert journal.two_layer_evaluation.safety_validation.validated_trade is not None
    assert journal.two_layer_evaluation.safety_validation.validated_trade.proposal.proposed_notional_amount == Decimal("1000") * target
    assert assessment.risk_evaluation_snapshot is not None
    assert assessment.risk_evaluation_snapshot.proposed_post_trade_cash_value == Decimal("1000") * (Decimal("1") - target)


def test_legacy_journal_omitting_two_layer_fields_reopens_without_fabricated_policy(tmp_path: Path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "state.sqlite")
    base = store.initialize_run(initialized_at=AT)
    current = _evaluated_state(base, Decimal("0.25"))
    current_journal = current.journal_entries[0]
    legacy_journal = DecisionJournalEntry(current_journal.decision_result, current_journal.risk_validation_result, AT)
    raw = encode(replace(current, journal_entries=(legacy_journal,)))
    journal_fields = raw["fields"]["journal_entries"]["items"][0]["fields"]
    journal_fields.pop("policy_reference")
    journal_fields.pop("two_layer_evaluation")

    reopened = decode_run_state(raw)
    journal = reopened.journal_entries[0]
    assert isinstance(journal.policy_reference, LegacyPolicyReference)
    assert journal.two_layer_evaluation is None
    assert journal.risk_validation_result == legacy_journal.risk_validation_result


def test_persisted_evaluation_cannot_be_rewritten_by_a_stale_writer(tmp_path: Path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "state.sqlite")
    base = store.initialize_run(initialized_at=AT)
    persisted = _evaluated_state(base, Decimal("0.25"))
    store.save_transition(persisted)
    journal = persisted.journal_entries[0]
    assert journal.two_layer_evaluation is not None and journal.two_layer_evaluation.manager_assessment is not None
    finding = next(item for item in journal.two_layer_evaluation.manager_assessment.findings if item.finding_id == "NORMAL_STARTER_GUIDANCE_DEVIATION")
    altered_assessment = replace(journal.two_layer_evaluation.manager_assessment, findings=tuple(replace(item, severity=ManagerAssessmentSeverity.INFO) if item == finding else item for item in journal.two_layer_evaluation.manager_assessment.findings))
    altered_evaluation = replace(journal.two_layer_evaluation, manager_assessment=altered_assessment)
    altered_journal = replace(journal, two_layer_evaluation=altered_evaluation)
    with pytest.raises(ValueError, match="decision journals must not rewrite"):
        store.save_transition(replace(persisted, journal_entries=(altered_journal,)))


def test_current_journal_rejects_cross_portfolio_snapshot_lineage(tmp_path: Path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "state.sqlite")
    journal = _evaluated_state(store.initialize_run(initialized_at=AT), Decimal("0.25")).journal_entries[0]
    other = _evaluated_state(SQLiteLocalRunStore._initial_state(AT), Decimal("0.25")).journal_entries[0]
    assert journal.two_layer_evaluation is not None and other.two_layer_evaluation is not None
    assert journal.two_layer_evaluation.manager_assessment is not None and other.two_layer_evaluation.manager_assessment is not None
    crossed_assessment = replace(journal.two_layer_evaluation.manager_assessment, risk_evaluation_snapshot=other.two_layer_evaluation.manager_assessment.risk_evaluation_snapshot)
    with pytest.raises(ValueError, match="RiskEvaluationSnapshot portfolio must match"):
        replace(journal, two_layer_evaluation=replace(journal.two_layer_evaluation, manager_assessment=crossed_assessment))


def test_current_journal_includes_advisory_assessment_in_chronology(tmp_path: Path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "state.sqlite")
    journal = _evaluated_state(store.initialize_run(initialized_at=AT), Decimal("0.25")).journal_entries[0]
    assert journal.two_layer_evaluation is not None and journal.two_layer_evaluation.manager_assessment is not None
    later_assessment = replace(journal.two_layer_evaluation.manager_assessment, assessment_timestamp=AT.replace(minute=AT.minute + 1))
    with pytest.raises(ValueError, match="latest included"):
        replace(journal, two_layer_evaluation=replace(journal.two_layer_evaluation, manager_assessment=later_assessment))
