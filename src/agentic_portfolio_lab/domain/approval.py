"""Immutable human approval records for journaled decision cycles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from .journal import DecisionJournalEntry
from .portfolio import _canonical_upper_text, _require_aware_datetime, _require_non_empty_text


class ApprovalDecision(StrEnum):
    """The terminal human outcomes supported by the MVP approval gate."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


def _normalize_approval_decision(value: ApprovalDecision | str) -> ApprovalDecision:
    if isinstance(value, ApprovalDecision):
        return value
    try:
        return ApprovalDecision(_canonical_upper_text(value, field_name="decision"))
    except ValueError as error:
        allowed = ", ".join(member.value for member in ApprovalDecision)
        raise ValueError(f"decision must be one of: {allowed}") from error


@dataclass(frozen=True, slots=True)
class DecisionApproval:
    """One immutable human decision over an already journaled decision cycle.

    The journal entry is the authoritative source for decision-cycle and
    portfolio lineage. This record deliberately contains no execution,
    scheduling, portfolio-mutation, authentication, or permission behavior.
    """

    journal_entry: DecisionJournalEntry
    decision_maker_id: str
    decision: ApprovalDecision | str
    decided_at: datetime
    comment: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.journal_entry, DecisionJournalEntry):
            raise TypeError("journal_entry must be a DecisionJournalEntry")
        decision = _normalize_approval_decision(self.decision)
        if decision is ApprovalDecision.APPROVED and not self.journal_entry.risk_validation_result.passed:
            raise ValueError("APPROVED requires passed deterministic validation")

        decided_at = _require_aware_datetime(self.decided_at, field_name="decided_at")
        if decided_at < self.journal_entry.journaled_at:
            raise ValueError("decided_at must not precede journal_entry journaled_at")

        object.__setattr__(
            self,
            "decision_maker_id",
            _require_non_empty_text(self.decision_maker_id, field_name="decision_maker_id").strip(),
        )
        if self.comment is not None:
            object.__setattr__(
                self,
                "comment",
                _require_non_empty_text(self.comment, field_name="comment").strip(),
            )
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "decided_at", decided_at)

    @property
    def decision_cycle_id(self) -> UUID:
        """Return the approval's authoritative decision-cycle lineage."""
        return self.journal_entry.decision_cycle_id

    @property
    def portfolio_id(self) -> UUID:
        """Return the approval's authoritative portfolio lineage."""
        return self.journal_entry.portfolio_id

