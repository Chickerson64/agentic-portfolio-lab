"""Framework-independent portfolio-manager recommendation models.

These immutable value objects represent manager intent only. Deterministic
systems verify evidence against research packets and own all trade feasibility,
approval, execution, and portfolio-state concerns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from .portfolio import (
    _canonical_upper_text,
    _require_date,
    _require_max_decimal_places,
    _require_non_empty_text,
    _require_positive_decimal,
)

_TARGET_WEIGHT_PLACES = Decimal("0.000001")


class RecommendationAction(StrEnum):
    """The only portfolio-level actions supported by the first vertical slice."""

    BUY = "BUY"
    HOLD = "HOLD"


class ReviewTriggerType(StrEnum):
    """The category of a future review trigger, not a scheduling mechanism."""

    EVENT_BASED = "EVENT_BASED"
    SCHEDULED = "SCHEDULED"


def _normalize_action(value: RecommendationAction | str) -> RecommendationAction:
    if isinstance(value, RecommendationAction):
        return value
    try:
        return RecommendationAction(_canonical_upper_text(value, field_name="action"))
    except ValueError as error:
        raise ValueError("action must be BUY or HOLD") from error


def _normalize_review_trigger_type(value: ReviewTriggerType | str) -> ReviewTriggerType:
    if isinstance(value, ReviewTriggerType):
        return value
    try:
        return ReviewTriggerType(_canonical_upper_text(value, field_name="trigger_type"))
    except ValueError as error:
        raise ValueError("trigger_type must be EVENT_BASED or SCHEDULED") from error


def _normalize_text_items(value: tuple[str, ...] | list[str], *, field_name: str, require_items: bool) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{field_name} must be a tuple or list of strings")
    normalized = tuple(_require_non_empty_text(item, field_name=f"{field_name} item").strip() for item in value)
    if require_items and not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _normalize_evidence_references(
    value: tuple["RecommendationEvidenceReference", ...] | list["RecommendationEvidenceReference"],
) -> tuple["RecommendationEvidenceReference", ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError("evidence must be a tuple or list of RecommendationEvidenceReference instances")
    references = tuple(value)
    if not references:
        raise ValueError("evidence must not be empty")
    if not all(isinstance(reference, RecommendationEvidenceReference) for reference in references):
        raise TypeError("evidence must contain RecommendationEvidenceReference instances")
    evidence_ids = tuple(reference.evidence_id for reference in references)
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ValueError("evidence must not contain duplicate evidence_id values")
    return references


def _normalize_review_triggers(
    value: tuple["ReviewTrigger", ...] | list["ReviewTrigger"],
) -> tuple["ReviewTrigger", ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError("review_triggers must be a tuple or list of ReviewTrigger instances")
    triggers = tuple(value)
    if not all(isinstance(trigger, ReviewTrigger) for trigger in triggers):
        raise TypeError("review_triggers must contain ReviewTrigger instances")
    return triggers


def _require_target_weight(value: Decimal) -> Decimal:
    value = _require_positive_decimal(value, field_name="target_weight")
    value = _require_max_decimal_places(value, _TARGET_WEIGHT_PLACES, field_name="target_weight")
    if value > Decimal("1"):
        raise ValueError("target_weight must not exceed 1")
    return value


@dataclass(frozen=True, slots=True)
class RecommendationEvidenceReference:
    """A source reference a manager may cite from supplied research evidence.

    The recommendation schema preserves the minimum reference fields. A later
    deterministic verifier confirms this reference is present in a supplied
    ResearchPacket; this value object never fetches or invents sources.
    """

    evidence_id: str
    source_type: str
    source_title: str
    source_date: date
    claim_supported: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _require_non_empty_text(self.evidence_id, field_name="evidence_id").strip())
        object.__setattr__(self, "source_type", _canonical_upper_text(self.source_type, field_name="source_type"))
        object.__setattr__(self, "source_title", _require_non_empty_text(self.source_title, field_name="source_title").strip())
        _require_date(self.source_date, field_name="source_date")
        object.__setattr__(self, "claim_supported", _require_non_empty_text(self.claim_supported, field_name="claim_supported").strip())


@dataclass(frozen=True, slots=True)
class ReviewTrigger:
    """A stated future review condition without scheduling behavior."""

    trigger_type: ReviewTriggerType | str
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "trigger_type", _normalize_review_trigger_type(self.trigger_type))
        object.__setattr__(self, "description", _require_non_empty_text(self.description, field_name="description").strip())


@dataclass(frozen=True, slots=True)
class PortfolioRecommendation:
    """One portfolio-level manager recommendation for deterministic downstream review."""

    action: RecommendationAction | str
    ticker: str | None
    target_weight: Decimal | None
    decision_rationale: str
    investment_thesis: str | None
    valuation: str
    risks: tuple[str, ...] | list[str]
    confidence_score: int
    evidence: tuple[RecommendationEvidenceReference, ...] | list[RecommendationEvidenceReference]
    why_not_spy: str
    thesis_invalidation: tuple[str, ...] | list[str]
    review_triggers: tuple[ReviewTrigger, ...] | list[ReviewTrigger]

    def __post_init__(self) -> None:
        action = _normalize_action(self.action)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "decision_rationale", _require_non_empty_text(self.decision_rationale, field_name="decision_rationale").strip())
        object.__setattr__(self, "valuation", _require_non_empty_text(self.valuation, field_name="valuation").strip())
        object.__setattr__(self, "risks", _normalize_text_items(self.risks, field_name="risks", require_items=True))
        if isinstance(self.confidence_score, bool) or not isinstance(self.confidence_score, int):
            raise TypeError("confidence_score must be an integer")
        if not 0 <= self.confidence_score <= 100:
            raise ValueError("confidence_score must be between 0 and 100")
        object.__setattr__(self, "evidence", _normalize_evidence_references(self.evidence))
        object.__setattr__(self, "why_not_spy", _require_non_empty_text(self.why_not_spy, field_name="why_not_spy").strip())
        object.__setattr__(
            self,
            "thesis_invalidation",
            _normalize_text_items(
                self.thesis_invalidation,
                field_name="thesis_invalidation",
                require_items=action is RecommendationAction.BUY,
            ),
        )
        object.__setattr__(self, "review_triggers", _normalize_review_triggers(self.review_triggers))

        if action is RecommendationAction.BUY:
            if self.ticker is None:
                raise ValueError("ticker is required for BUY")
            object.__setattr__(self, "ticker", _canonical_upper_text(self.ticker, field_name="ticker"))
            if self.target_weight is None:
                raise ValueError("target_weight is required for BUY")
            object.__setattr__(self, "target_weight", _require_target_weight(self.target_weight))
            if self.investment_thesis is None:
                raise ValueError("investment_thesis is required for BUY")
            object.__setattr__(
                self,
                "investment_thesis",
                _require_non_empty_text(self.investment_thesis, field_name="investment_thesis").strip(),
            )
            return

        if self.ticker is not None:
            raise ValueError("ticker must be null for HOLD")
        if self.target_weight is not None:
            raise ValueError("target_weight must be null for HOLD")
        if self.investment_thesis is not None:
            raise ValueError("investment_thesis must be null for HOLD")
