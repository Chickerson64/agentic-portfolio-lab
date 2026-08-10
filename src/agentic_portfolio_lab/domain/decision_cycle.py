"""Explicit orchestration for one pre-approval Value Manager decision cycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .journal import DecisionJournalEntry
from .portfolio import _require_aware_datetime
from .reviewer import AIReviewer, AIReviewerReviewContext, ReviewerResult
from .risk_validation import DeterministicRiskValidator
from .valuation import PriceObservation
from .value_manager import ValueManagerDecisionContext
from .value_manager_workflow import ValueManagerDecisionWorkflow


class DecisionCycleStage(StrEnum):
    """The terminal pre-approval stages supported by the first workflow."""

    STOPPED_AT_RISK_VALIDATION = "STOPPED_AT_RISK_VALIDATION"
    REVIEWED = "REVIEWED"


@dataclass(frozen=True, slots=True)
class DecisionCycleResult:
    """Immutable summary of one fully journaled pre-approval decision cycle."""

    journal_entry: DecisionJournalEntry
    stage: DecisionCycleStage | str

    def __post_init__(self) -> None:
        if not isinstance(self.journal_entry, DecisionJournalEntry):
            raise TypeError("journal_entry must be a DecisionJournalEntry")
        try:
            stage = DecisionCycleStage(self.stage)
        except ValueError as error:
            allowed = ", ".join(member.value for member in DecisionCycleStage)
            raise ValueError(f"stage must be one of: {allowed}") from error

        risk_result = self.journal_entry.risk_validation_result
        reviewer_result = self.journal_entry.reviewer_result
        if stage is DecisionCycleStage.STOPPED_AT_RISK_VALIDATION:
            if risk_result.passed or reviewer_result is not None:
                raise ValueError("STOPPED_AT_RISK_VALIDATION requires failed validation without reviewer output")
        elif not risk_result.passed or reviewer_result is None:
            raise ValueError("REVIEWED requires passed validation and reviewer output")
        object.__setattr__(self, "stage", stage)

    @property
    def deterministic_validation_passed(self) -> bool:
        """Return the journaled deterministic validation outcome."""
        return self.journal_entry.risk_validation_result.passed

    @property
    def qualitative_review_occurred(self) -> bool:
        """Return whether an independent qualitative review was journaled."""
        return self.journal_entry.reviewer_result is not None


@dataclass(frozen=True, slots=True)
class DecisionCycleOrchestrator:
    """Compose decision, risk validation, review, and journaling without mutation.

    This boundary deliberately stops before human approval and execution. It has
    no state, clock, data-fetching, retry, or portfolio-mutation responsibility.
    """

    decision_workflow: ValueManagerDecisionWorkflow
    risk_validator: DeterministicRiskValidator
    reviewer: AIReviewer

    def __post_init__(self) -> None:
        if not isinstance(self.decision_workflow, ValueManagerDecisionWorkflow):
            raise TypeError("decision_workflow must be a ValueManagerDecisionWorkflow")
        if not isinstance(self.risk_validator, DeterministicRiskValidator):
            raise TypeError("risk_validator must be a DeterministicRiskValidator")
        if not isinstance(self.reviewer, AIReviewer) or not callable(getattr(self.reviewer, "review", None)):
            raise TypeError("reviewer must implement the AIReviewer protocol")

    def run(
        self,
        context: ValueManagerDecisionContext,
        *,
        produced_at: datetime,
        validation_timestamp: datetime,
        journaled_at: datetime,
        price_observation: PriceObservation | None = None,
        reviewed_at: datetime | None = None,
    ) -> DecisionCycleResult:
        """Run one explicit pre-approval decision cycle and return its journal.

        ``reviewed_at`` is required only after deterministic validation passes;
        it ensures the orchestrator does not accept a reviewer artifact whose
        timestamp differs from the caller-supplied cycle chronology.
        """
        if not isinstance(context, ValueManagerDecisionContext):
            raise TypeError("context must be a ValueManagerDecisionContext")

        decision_result = self.decision_workflow.run(context, produced_at=produced_at)
        risk_result = self.risk_validator.validate(
            decision_result,
            validation_timestamp=validation_timestamp,
            price_observation=price_observation,
        )
        if not risk_result.passed:
            return DecisionCycleResult(
                journal_entry=DecisionJournalEntry(
                    decision_result=decision_result,
                    risk_validation_result=risk_result,
                    journaled_at=journaled_at,
                ),
                stage=DecisionCycleStage.STOPPED_AT_RISK_VALIDATION,
            )

        if reviewed_at is None:
            raise ValueError("reviewed_at is required after passed deterministic validation")
        expected_reviewed_at = _require_aware_datetime(reviewed_at, field_name="reviewed_at")
        review_context = AIReviewerReviewContext(
            decision_result=decision_result,
            risk_validation_result=risk_result,
            constitution=context.constitution,
        )
        reviewer_result = self.reviewer.review(review_context)
        if not isinstance(reviewer_result, ReviewerResult):
            raise TypeError("AIReviewer.review must return a ReviewerResult")
        if reviewer_result.context != review_context:
            raise ValueError("ReviewerResult must belong to the supplied AIReviewerReviewContext")
        if reviewer_result.reviewed_at != expected_reviewed_at:
            raise ValueError("ReviewerResult reviewed_at must match the caller-supplied reviewed_at")

        return DecisionCycleResult(
            journal_entry=DecisionJournalEntry(
                decision_result=decision_result,
                risk_validation_result=risk_result,
                reviewer_result=reviewer_result,
                journaled_at=journaled_at,
            ),
            stage=DecisionCycleStage.REVIEWED,
        )
