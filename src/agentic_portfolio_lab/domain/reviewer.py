"""Framework-independent boundary for review of validated manager intent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from .constitution import ValueManagerConstitution
from .portfolio import _canonical_upper_text, _require_aware_datetime, _require_non_empty_text
from .risk_validation import RiskValidationResult
from .value_manager_workflow import ValueManagerDecisionResult


class ReviewDecision(StrEnum):
    """The only reviewer outcomes supported by the MVP."""

    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class ReviewFindingSeverity(StrEnum):
    """The urgency of a critique without assigning a numerical score."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ReviewFindingCategory(StrEnum):
    """The documented qualitative areas a reviewer may critique."""

    CONSTITUTION_ADHERENCE = "CONSTITUTION_ADHERENCE"
    REASONING_QUALITY = "REASONING_QUALITY"
    EVIDENCE_USAGE = "EVIDENCE_USAGE"
    CONTRADICTORY_STATEMENTS = "CONTRADICTORY_STATEMENTS"
    CONFIDENCE_CALIBRATION = "CONFIDENCE_CALIBRATION"
    THESIS_COMPLETENESS = "THESIS_COMPLETENESS"
    SPY_COMPARISON_QUALITY = "SPY_COMPARISON_QUALITY"
    MISSING_DISCUSSION = "MISSING_DISCUSSION"
    COMMUNICATION_QUALITY = "COMMUNICATION_QUALITY"


def _normalize_enum(value: StrEnum | str, enum_type: type[StrEnum], *, field_name: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(_canonical_upper_text(value, field_name=field_name))
    except ValueError as error:
        allowed = ", ".join(member.value for member in enum_type)
        raise ValueError(f"{field_name} must be one of: {allowed}") from error


def _normalize_evidence_ids(value: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError("related_evidence_ids must be a tuple or list of strings")
    evidence_ids = tuple(
        _require_non_empty_text(item, field_name="related_evidence_ids item").strip() for item in value
    )
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ValueError("related_evidence_ids must not contain duplicates")
    return evidence_ids


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    """One descriptive critique of a verified recommendation.

    Findings are qualitative review output. They do not encode mechanical risk
    validation, a trade instruction, or any portfolio-state change.
    """

    severity: ReviewFindingSeverity | str
    category: ReviewFindingCategory | str
    message: str
    related_evidence_ids: tuple[str, ...] | list[str] = ()
    related_recommendation_field: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "severity",
            _normalize_enum(self.severity, ReviewFindingSeverity, field_name="severity"),
        )
        object.__setattr__(
            self,
            "category",
            _normalize_enum(self.category, ReviewFindingCategory, field_name="category"),
        )
        object.__setattr__(self, "message", _require_non_empty_text(self.message, field_name="message").strip())
        object.__setattr__(self, "related_evidence_ids", _normalize_evidence_ids(self.related_evidence_ids))
        if self.related_recommendation_field is not None:
            object.__setattr__(
                self,
                "related_recommendation_field",
                _require_non_empty_text(
                    self.related_recommendation_field,
                    field_name="related_recommendation_field",
                ).strip(),
            )


@dataclass(frozen=True, slots=True)
class AIReviewerReviewContext:
    """Verified inputs to one independent qualitative reviewer invocation.

    This context intentionally composes prior workflow outputs instead of raw
    manager output, raw research, or portfolio state. The workflow result is
    the authoritative recommendation lineage, while the risk result confirms
    that the reviewer is receiving the matching deterministic validation run.
    """

    decision_result: ValueManagerDecisionResult
    risk_validation_result: RiskValidationResult
    constitution: ValueManagerConstitution

    def __post_init__(self) -> None:
        if not isinstance(self.decision_result, ValueManagerDecisionResult):
            raise TypeError("decision_result must be a ValueManagerDecisionResult")
        if not isinstance(self.risk_validation_result, RiskValidationResult):
            raise TypeError("risk_validation_result must be a RiskValidationResult")
        if self.risk_validation_result.decision_result != self.decision_result:
            raise ValueError("risk_validation_result must belong to decision_result")
        if not self.risk_validation_result.passed:
            raise ValueError("risk_validation_result must have passed before AI review")
        if not isinstance(self.constitution, ValueManagerConstitution):
            raise TypeError("constitution must be a ValueManagerConstitution")
        if self.decision_result.context.constitution != self.constitution:
            raise ValueError("constitution must match the decision_result constitution")

    @property
    def decision_cycle_id(self) -> UUID:
        """Return lineage from the authoritative manager decision context."""
        return self.decision_result.decision_cycle_id

    @property
    def portfolio_id(self) -> UUID:
        """Return portfolio lineage from the authoritative manager decision context."""
        return self.decision_result.portfolio_id

    @property
    def constitution_version(self) -> str:
        """Return the version of the constitution used for the decision."""
        return self.constitution.constitution_version

    @property
    def research_batch_id(self) -> str:
        """Return the immutable research-batch reference for this review."""
        return self.decision_result.research_batch_id


def _verify_related_evidence(context: AIReviewerReviewContext, findings: tuple[ReviewFinding, ...]) -> None:
    evidence_counts: dict[str, int] = {}
    for packet in context.decision_result.context.research_batch.packets:
        for evidence in packet.evidence_items:
            evidence_counts[evidence.evidence_id] = evidence_counts.get(evidence.evidence_id, 0) + 1

    for finding in findings:
        for evidence_id in finding.related_evidence_ids:
            count = evidence_counts.get(evidence_id, 0)
            if count == 0:
                raise ValueError("related_evidence_ids must exist in the ResearchBatch")
            if count > 1:
                raise ValueError("related_evidence_ids must not be ambiguous across ResearchPackets")


@dataclass(frozen=True, slots=True)
class ReviewerResult:
    """One immutable, evidence-linked reviewer outcome for a decision cycle."""

    context: AIReviewerReviewContext
    decision: ReviewDecision | str
    findings: tuple[ReviewFinding, ...] | list[ReviewFinding]
    reviewed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.context, AIReviewerReviewContext):
            raise TypeError("context must be an AIReviewerReviewContext")
        decision = _normalize_enum(self.decision, ReviewDecision, field_name="decision")
        if not isinstance(self.findings, (tuple, list)):
            raise TypeError("findings must be a tuple or list of ReviewFinding instances")
        findings = tuple(self.findings)
        if not all(isinstance(finding, ReviewFinding) for finding in findings):
            raise TypeError("findings must contain ReviewFinding instances")
        if decision is ReviewDecision.REQUEST_CHANGES and not findings:
            raise ValueError("REQUEST_CHANGES requires at least one finding")
        if decision is ReviewDecision.APPROVE and any(
            finding.severity is ReviewFindingSeverity.CRITICAL for finding in findings
        ):
            raise ValueError("APPROVE must not contain CRITICAL findings")
        reviewed_at = _require_aware_datetime(self.reviewed_at, field_name="reviewed_at")
        if reviewed_at < self.context.risk_validation_result.validation_timestamp:
            raise ValueError("reviewed_at must not precede risk validation_timestamp")
        _verify_related_evidence(self.context, findings)
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "reviewed_at", reviewed_at)

    @property
    def decision_cycle_id(self) -> UUID:
        """Return the review's authoritative decision-cycle lineage."""
        return self.context.decision_cycle_id

    @property
    def portfolio_id(self) -> UUID:
        """Return the reviewed portfolio's authoritative lineage."""
        return self.context.portfolio_id

    @property
    def constitution_version(self) -> str:
        """Return the audited constitution version used for the review."""
        return self.context.constitution_version


@runtime_checkable
class AIReviewer(Protocol):
    """Independently critiques one verified manager decision.

    Implementations may be deterministic or AI-assisted, but this boundary has
    no provider, research, risk-validation, approval, execution, or persistence
    dependency.
    """

    def review(self, context: AIReviewerReviewContext) -> ReviewerResult:
        """Return exactly one immutable review result for the supplied context."""
