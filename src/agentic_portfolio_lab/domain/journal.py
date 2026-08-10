"""Immutable audit linkage for one pre-execution investment decision cycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .portfolio import _require_aware_datetime
from .reviewer import ReviewerResult
from .risk_validation import RiskValidationResult
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

        journaled_at = _require_aware_datetime(self.journaled_at, field_name="journaled_at")
        latest_artifact_at = max(
            self.decision_result.produced_at,
            self.risk_validation_result.validation_timestamp,
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
