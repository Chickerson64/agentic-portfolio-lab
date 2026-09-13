"""Additive, provider-independent V2 portfolio target contract.

V2 describes manager intent as a complete target allocation.  It deliberately
does not describe trades; current-to-target derivation belongs to deterministic
downstream code.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
import re
from typing import ClassVar
from uuid import UUID

from .portfolio import SecurityIdentity, _calculate_decimal, _canonical_upper_text, _require_max_decimal_places, _require_non_empty_text, _require_non_negative_decimal
from .recommendations import RecommendationEvidenceReference, ReviewTrigger

V2_WEIGHT_PLACES = Decimal("0.000001")
_V2_TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{0,11}$")
_V2_EXCHANGE_PATTERN = re.compile(r"^[A-Z]+(?: [A-Z]+)*$")


class CashClassification(StrEnum):
    STRATEGIC = "STRATEGIC"
    ACCIDENTAL = "ACCIDENTAL"


class ExistingHoldingDisposition(StrEnum):
    INITIATE = "INITIATE"
    RETAIN = "RETAIN"
    INCREASE = "INCREASE"
    REDUCE = "REDUCE"
    REMOVE = "REMOVE"


class TargetConstructionMode(StrEnum):
    INITIAL = "INITIAL"
    REBALANCE = "REBALANCE"


@dataclass(frozen=True, slots=True)
class TargetDecisionProvenance:
    """Versioned model and input lineage retained with a V2 target."""

    provider: str
    model: str
    schema_version: str
    prompt_version: str
    response_id: str | None
    request_id: str | None
    lineage: tuple[tuple[str, str], ...] | list[tuple[str, str]]

    def __post_init__(self) -> None:
        for field_name in ("provider", "model", "schema_version", "prompt_version"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        for field_name in ("response_id", "request_id"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string or None")
        lineage = tuple(self.lineage)
        if not lineage or any(not isinstance(item, tuple) or len(item) != 2 or not all(isinstance(value, str) and value.strip() for value in item) for item in lineage):
            raise ValueError("lineage must contain nonblank string pairs")
        object.__setattr__(self, "lineage", lineage)


def _text(value: str, field_name: str) -> str:
    return _require_non_empty_text(value, field_name=field_name).strip()


def _enum(value: StrEnum | str, enum_type: type[StrEnum], field_name: str) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(_canonical_upper_text(value, field_name=field_name))
    except ValueError as error:
        raise ValueError(f"{field_name} is unsupported") from error


def _weight(value: Decimal, field_name: str = "target_weight") -> Decimal:
    value = _require_non_negative_decimal(value, field_name=field_name)
    value = _require_max_decimal_places(value, V2_WEIGHT_PLACES, field_name=field_name)
    if value > Decimal("1"):
        raise ValueError(f"{field_name} must not exceed 1")
    return value


@dataclass(frozen=True, slots=True)
class CashTarget:
    weight: Decimal
    classification: CashClassification | str
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "weight", _weight(self.weight, "cash weight"))
        object.__setattr__(self, "classification", _enum(self.classification, CashClassification, "cash classification"))
        object.__setattr__(self, "rationale", _text(self.rationale, "cash rationale"))


@dataclass(frozen=True, slots=True)
class PortfolioTargetPosition:
    security: SecurityIdentity
    target_weight: Decimal
    role: str
    thesis: str
    confidence: int
    evidence: tuple[RecommendationEvidenceReference, ...] | list[RecommendationEvidenceReference]
    invalidation_conditions: tuple[str, ...] | list[str]
    review_triggers: tuple[ReviewTrigger, ...] | list[ReviewTrigger]
    existing_holding_disposition: ExistingHoldingDisposition | str = ExistingHoldingDisposition.INITIATE
    research_supported: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        if self.security.security_type not in {"EQUITY", "ETF"} or self.security.currency != "USD":
            raise ValueError("security identity is unsupported for V2")
        if not _V2_TICKER_PATTERN.fullmatch(self.security.ticker):
            raise ValueError("security ticker is malformed")
        if not _V2_EXCHANGE_PATTERN.fullmatch(self.security.exchange):
            raise ValueError("security exchange is malformed")
        object.__setattr__(self, "target_weight", _weight(self.target_weight))
        for name in ("role", "thesis"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, int):
            raise TypeError("confidence must be an integer")
        if not 0 <= self.confidence <= 100:
            raise ValueError("confidence must be between 0 and 100")
        if not isinstance(self.research_supported, bool):
            raise TypeError("research_supported must be a boolean")
        evidence = tuple(self.evidence)
        if not all(isinstance(item, RecommendationEvidenceReference) for item in evidence):
            raise TypeError("evidence must contain RecommendationEvidenceReference instances")
        if self.research_supported and not evidence:
            raise ValueError("research-supported positions require evidence")
        object.__setattr__(self, "evidence", evidence)
        if not isinstance(self.invalidation_conditions, (tuple, list)):
            raise TypeError("invalidation_conditions must be a tuple or list of strings")
        conditions = tuple(_text(item, "invalidation condition") for item in self.invalidation_conditions)
        object.__setattr__(self, "invalidation_conditions", conditions)
        triggers = tuple(self.review_triggers)
        if not all(isinstance(item, ReviewTrigger) for item in triggers):
            raise TypeError("review_triggers must contain ReviewTrigger instances")
        object.__setattr__(self, "review_triggers", triggers)
        disposition = _enum(self.existing_holding_disposition, ExistingHoldingDisposition, "existing_holding_disposition")
        if disposition is ExistingHoldingDisposition.REMOVE and not self.target_weight.is_zero():
            raise ValueError("REMOVE disposition requires a zero target weight")
        if disposition is not ExistingHoldingDisposition.REMOVE and self.target_weight.is_zero():
            raise ValueError("zero target weight requires REMOVE disposition")
        object.__setattr__(self, "existing_holding_disposition", disposition)

    @property
    def confidence_score(self) -> int:
        """V1-compatible naming for the descriptive V2 confidence value."""
        return self.confidence

    @property
    def thesis_invalidation(self) -> tuple[str, ...]:
        return self.invalidation_conditions


@dataclass(frozen=True, slots=True)
class PortfolioTargetAllocation:
    """A complete, immutable V2 manager target for one identified portfolio."""

    schema_version: ClassVar[str] = "portfolio-target-v2"
    portfolio_id: UUID
    overall_rationale: str
    risk_commentary: str
    concentration_commentary: str
    benchmark_active_risk_commentary: str
    cash_target: CashTarget
    positions: tuple[PortfolioTargetPosition, ...] | list[PortfolioTargetPosition]
    construction_mode: TargetConstructionMode | str = TargetConstructionMode.REBALANCE
    decision_provenance: TargetDecisionProvenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.portfolio_id, UUID):
            raise TypeError("portfolio_id must be a UUID")
        for name in ("overall_rationale", "risk_commentary", "concentration_commentary", "benchmark_active_risk_commentary"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.cash_target, CashTarget):
            raise TypeError("cash_target must be a CashTarget")
        positions = tuple(self.positions)
        if not all(isinstance(item, PortfolioTargetPosition) for item in positions):
            raise TypeError("positions must contain PortfolioTargetPosition instances")
        identities = tuple(item.security for item in positions)
        if len(set(identities)) != len(identities):
            raise ValueError("positions must not contain duplicate security identities")
        total = _calculate_decimal(
            lambda: self.cash_target.weight + sum((item.target_weight for item in positions), Decimal("0"))
        )
        if total != Decimal("1"):
            raise ValueError("security target weights plus cash weight must equal exactly 1.000000")
        object.__setattr__(self, "positions", positions)
        object.__setattr__(self, "construction_mode", _enum(self.construction_mode, TargetConstructionMode, "construction_mode"))
        if self.decision_provenance is not None and not isinstance(self.decision_provenance, TargetDecisionProvenance):
            raise TypeError("decision_provenance must be a TargetDecisionProvenance or None")

    @property
    def target_cash(self) -> CashTarget:
        return self.cash_target

    @property
    def security_targets(self) -> tuple[PortfolioTargetPosition, ...]:
        return self.positions


# Short aliases make the contract readable at call sites while retaining one
# canonical type for serialization and future versioned adapters.
V2PortfolioTarget = PortfolioTargetAllocation
V2PortfolioTargetPosition = PortfolioTargetPosition
