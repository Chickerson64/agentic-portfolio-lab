"""Immutable audit linkage for one pre-execution investment decision cycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .portfolio import _require_aware_datetime
from .policy import CurrentPolicyReference, LegacyPolicyReference
from .reviewer import ReviewerResult
from .risk_validation import RiskValidationResult, TwoLayerEvaluationResult
from .value_manager_workflow import ValueManagerDecisionResult


def _reviewer_evidence_ids(reviewer_result: ReviewerResult | None) -> tuple[str, ...]:
    """Return unique reviewer-cited evidence IDs in finding order."""
    if reviewer_result is None:
        return ()
    evidence_ids: list[str] = []
    for finding in reviewer_result.findings:
        for evidence_id in finding.related_evidence_ids:
            if evidence_id not in evidence_ids:
                evidence_ids.append(evidence_id)
    return tuple(evidence_ids)


@dataclass(frozen=True, slots=True)
class DecisionJournalEntry:
    """One immutable, verified record of a decision cycle before execution.

    The entry composes verified pipeline artifacts rather than copying research
    content or maintaining parallel lineage fields. Human approval, execution,
    persistence, and portfolio-history mutation are intentionally outside this
    pre-execution journal model.
    """

    decision_result: ValueManagerDecisionResult
    risk_validation_result: RiskValidationResult
    journaled_at: datetime
    reviewer_result: ReviewerResult | None = None
    policy_reference: LegacyPolicyReference | CurrentPolicyReference = LegacyPolicyReference()
    two_layer_evaluation: TwoLayerEvaluationResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.decision_result, ValueManagerDecisionResult):
            raise TypeError("decision_result must be a ValueManagerDecisionResult")
        if not isinstance(self.risk_validation_result, RiskValidationResult):
            raise TypeError("risk_validation_result must be a RiskValidationResult")
        if self.risk_validation_result.decision_result != self.decision_result:
            raise ValueError("risk_validation_result must belong to decision_result")
        if self.reviewer_result is not None:
            if not isinstance(self.reviewer_result, ReviewerResult):
                raise TypeError("reviewer_result must be a ReviewerResult or None")
            if self.reviewer_result.context.decision_result != self.decision_result:
                raise ValueError("reviewer_result must belong to decision_result")
            if self.reviewer_result.context.risk_validation_result != self.risk_validation_result:
                raise ValueError("reviewer_result must belong to risk_validation_result")
            if self.reviewer_result.constitution_version != self.constitution_version:
                raise ValueError("reviewer_result constitution_version must match decision_result")

        if not isinstance(self.policy_reference, (LegacyPolicyReference, CurrentPolicyReference)):
            raise TypeError("policy_reference must be a LegacyPolicyReference or CurrentPolicyReference")
        if isinstance(self.policy_reference, LegacyPolicyReference):
            if self.two_layer_evaluation is not None:
                raise ValueError("legacy policy references must not fabricate a two-layer evaluation")
        else:
            if not isinstance(self.two_layer_evaluation, TwoLayerEvaluationResult):
                raise ValueError("current policy references require a TwoLayerEvaluationResult")
            evaluation = self.two_layer_evaluation
            if evaluation.safety_validation != self.risk_validation_result:
                raise ValueError("two_layer_evaluation safety_validation must match risk_validation_result")
            if evaluation.manager_assessment is None:
                raise ValueError("current policy references require a Manager Constitution assessment")
            assessment = evaluation.manager_assessment
            if assessment.manager_risk_constitution != self.policy_reference.manager_risk_constitution:
                raise ValueError("manager assessment constitution must match policy_reference")
            if assessment.decision_result != self.decision_result:
                raise ValueError("manager assessment must belong to decision_result")
            if assessment.manager_risk_constitution.manager_type != self.decision_result.manager_type:
                raise ValueError("manager policy manager_type must match decision_result")
            if assessment.manager_risk_constitution.loading_source != self.policy_reference.manager_risk_constitution.loading_source:
                raise ValueError("manager policy loading source must match policy_reference")
            from .policy import InvestmentConstitutionReference

            if InvestmentConstitutionReference.from_constitution(self.decision_result.context.constitution) != self.policy_reference.investment_constitution:
                raise ValueError("investment constitution must match policy_reference")
            expected_version = self.policy_reference.system_safety_envelope.system_safety_envelope_version.value
            if any(rule.policy_version != expected_version for rule in self.risk_validation_result.rule_results):
                raise ValueError("System Safety rule policy_version must match policy_reference")
            recommendation = self.decision_result.recommendation
            snapshot = assessment.risk_evaluation_snapshot
            if recommendation.action.value == "BUY":
                assert snapshot is not None  # Guaranteed by ManagerConstitutionAssessment.
                if snapshot.portfolio != self.decision_result.context.portfolio:
                    raise ValueError("RiskEvaluationSnapshot portfolio must match decision_result")
                if snapshot.proposed_target_weight != recommendation.target_weight:
                    raise ValueError("RiskEvaluationSnapshot target weight must match recommendation")
                if snapshot.security.ticker != recommendation.ticker:
                    raise ValueError("RiskEvaluationSnapshot security must match recommendation")
                if snapshot.price_observation != self.risk_validation_result.price_observation:
                    raise ValueError("RiskEvaluationSnapshot price_observation must match System Safety validation")
                matching_packets = tuple(
                    packet for packet in self.decision_result.context.research_batch.packets
                    if packet.ticker == recommendation.ticker
                )
                if len(matching_packets) != 1 or snapshot.evidence_coverage.packet_id != matching_packets[0].packet_id:
                    raise ValueError("RiskEvaluationSnapshot evidence coverage must match the verified research packet")

        journaled_at = _require_aware_datetime(self.journaled_at, field_name="journaled_at")
        assessment_timestamp = (
            () if self.two_layer_evaluation is None or self.two_layer_evaluation.manager_assessment is None
            else (self.two_layer_evaluation.manager_assessment.assessment_timestamp,)
        )
        latest_artifact_at = max(
            self.decision_result.produced_at,
            self.risk_validation_result.validation_timestamp,
            *assessment_timestamp,
            *(() if self.reviewer_result is None else (self.reviewer_result.reviewed_at,)),
        )
        if journaled_at < latest_artifact_at:
            raise ValueError("journaled_at must not precede the latest included pipeline artifact")
        object.__setattr__(self, "journaled_at", journaled_at)

    @property
    def decision_cycle_id(self) -> UUID:
        """Return decision-cycle lineage from the verified manager result."""
        return self.decision_result.decision_cycle_id

    @property
    def portfolio_id(self) -> UUID:
        """Return portfolio lineage from the verified manager result."""
        return self.decision_result.portfolio_id

    @property
    def manager_type(self) -> str:
        """Return manager lineage from the authoritative ResearchBatch."""
        return self.decision_result.manager_type

    @property
    def constitution_version(self) -> str:
        """Return the version of the constitution used for this decision."""
        return self.decision_result.constitution_version

    @property
    def research_batch_id(self) -> str:
        """Return the source ResearchBatch reference without copying packets."""
        return self.decision_result.research_batch_id

    @property
    def research_packet_ids(self) -> tuple[str, ...]:
        """Return the ordered packet references supplied for this decision cycle."""
        return tuple(packet.packet_id for packet in self.decision_result.context.research_batch.packets)

    @property
    def cited_evidence_ids(self) -> tuple[str, ...]:
        """Return manager-cited evidence references in recommendation order."""
        return tuple(reference.evidence_id for reference in self.decision_result.recommendation.evidence)

    @property
    def reviewer_evidence_ids(self) -> tuple[str, ...]:
        """Return unique reviewer-cited evidence references in finding order."""
        return _reviewer_evidence_ids(self.reviewer_result)
