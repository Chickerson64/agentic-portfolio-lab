"""Framework-independent research packet domain models.

Research packets are immutable, source-backed inputs to a manager. They never
contain an investment recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final
from uuid import UUID

from .portfolio import _canonical_upper_text, _require_aware_datetime, _require_date, _require_non_empty_text
from .provider_fundamentals import FreshnessClass, ProviderEndpoint, ReliabilityClass, ReuseStatus


class MissingDataReason(StrEnum):
    """Why an upstream research value is explicitly absent."""

    UNKNOWN = "UNKNOWN"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class MissingData:
    """An explicit missing-data marker; values are never silently inferred."""

    reason: MissingDataReason
    details: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reason, MissingDataReason):
            raise TypeError("reason must be a MissingDataReason")
        if self.details is not None:
            object.__setattr__(self, "details", _require_non_empty_text(self.details, field_name="details"))


UNKNOWN_MISSING: Final = MissingData(MissingDataReason.UNKNOWN)


def _require_identifier(value: str, *, field_name: str) -> str:
    return _require_non_empty_text(value, field_name=field_name).strip()


def _require_text_or_missing(value: str | MissingData, *, field_name: str) -> str | MissingData:
    if isinstance(value, MissingData):
        return value
    return _require_non_empty_text(value, field_name=field_name).strip()


def _normalize_evidence_ids(value: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError("evidence_ids must be a tuple or list of strings")
    normalized_ids = tuple(_require_identifier(item, field_name="evidence_ids item") for item in value)
    if not normalized_ids:
        raise ValueError("evidence_ids must not be empty")
    if len(set(normalized_ids)) != len(normalized_ids):
        raise ValueError("evidence_ids must not contain duplicates")
    return normalized_ids


def _security_components_match(left: "ResearchPacket", right: "ResearchPacket") -> bool:
    """Return whether two packet identities are the same or ambiguous.

    A missing optional identity component cannot establish that two otherwise
    matching tickers are different securities, so batches reject that ambiguity.
    """
    if (left.ticker, left.security_type) != (right.ticker, right.security_type):
        return False
    for field_name in ("exchange", "currency"):
        left_value = getattr(left, field_name)
        right_value = getattr(right, field_name)
        if isinstance(left_value, MissingData) or isinstance(right_value, MissingData):
            continue
        if left_value != right_value:
            return False
    return True


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """A minimum, traceable reference to source evidence in a research packet."""

    evidence_id: str
    source_type: str
    source_title: str
    source_date: date
    claim_supported: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _require_identifier(self.evidence_id, field_name="evidence_id"))
        object.__setattr__(self, "source_type", _canonical_upper_text(self.source_type, field_name="source_type"))
        object.__setattr__(self, "source_title", _require_non_empty_text(self.source_title, field_name="source_title").strip())
        _require_date(self.source_date, field_name="source_date")
        object.__setattr__(self, "claim_supported", _require_non_empty_text(self.claim_supported, field_name="claim_supported").strip())


@dataclass(frozen=True, slots=True)
class ResearchSection:
    """A compact source-backed packet section without fixing future section schemas."""

    section_id: str
    content: str | MissingData
    evidence_ids: tuple[str, ...] | list[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "section_id", _canonical_upper_text(self.section_id, field_name="section_id"))
        content = _require_text_or_missing(self.content, field_name="content")
        object.__setattr__(self, "content", content)
        if isinstance(content, MissingData):
            if self.evidence_ids:
                object.__setattr__(self, "evidence_ids", _normalize_evidence_ids(self.evidence_ids))
            else:
                object.__setattr__(self, "evidence_ids", tuple())
            return
        object.__setattr__(self, "evidence_ids", _normalize_evidence_ids(self.evidence_ids))


@dataclass(frozen=True, slots=True)
class ResearchPacket:
    """The independently reusable evidence bundle for exactly one security."""

    packet_id: str
    candidate_id: str
    ticker: str
    security_type: str
    as_of_timestamp: datetime
    evidence_items: tuple[EvidenceItem, ...] | list[EvidenceItem]
    sections: tuple[ResearchSection, ...] | list[ResearchSection]
    company_name: str | MissingData = UNKNOWN_MISSING
    exchange: str | MissingData = UNKNOWN_MISSING
    currency: str | MissingData = UNKNOWN_MISSING
    sector: str | MissingData = UNKNOWN_MISSING
    industry: str | MissingData = UNKNOWN_MISSING
    fundamentals: PacketFundamentals | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "packet_id", _require_identifier(self.packet_id, field_name="packet_id"))
        object.__setattr__(self, "candidate_id", _require_identifier(self.candidate_id, field_name="candidate_id"))
        object.__setattr__(self, "ticker", _canonical_upper_text(self.ticker, field_name="ticker"))
        object.__setattr__(self, "security_type", _canonical_upper_text(self.security_type, field_name="security_type"))
        _require_aware_datetime(self.as_of_timestamp, field_name="as_of_timestamp")

        for field_name in ("company_name", "sector", "industry"):
            object.__setattr__(self, field_name, _require_text_or_missing(getattr(self, field_name), field_name=field_name))
        for field_name in ("exchange", "currency"):
            value = getattr(self, field_name)
            if isinstance(value, MissingData):
                continue
            object.__setattr__(self, field_name, _canonical_upper_text(value, field_name=field_name))

        if not isinstance(self.evidence_items, (tuple, list)):
            raise TypeError("evidence_items must be a tuple or list of EvidenceItem instances")
        evidence_items = tuple(self.evidence_items)
        if not evidence_items:
            raise ValueError("evidence_items must not be empty")
        if not all(isinstance(item, EvidenceItem) for item in evidence_items):
            raise TypeError("evidence_items must contain EvidenceItem instances")
        evidence_ids = tuple(item.evidence_id for item in evidence_items)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence_items must not contain duplicate evidence_id values")
        packet_as_of_date = self.as_of_timestamp.date()
        if any(item.source_date > packet_as_of_date for item in evidence_items):
            raise ValueError("evidence_items must not have source_date after packet as_of_timestamp")
        object.__setattr__(self, "evidence_items", evidence_items)

        if not isinstance(self.sections, (tuple, list)):
            raise TypeError("sections must be a tuple or list of ResearchSection instances")
        sections = tuple(self.sections)
        if not sections:
            raise ValueError("sections must not be empty")
        if not all(isinstance(section, ResearchSection) for section in sections):
            raise TypeError("sections must contain ResearchSection instances")
        section_ids = tuple(section.section_id for section in sections)
        if len(set(section_ids)) != len(section_ids):
            raise ValueError("sections must not contain duplicate section_id values")
        available_evidence_ids = set(evidence_ids)
        for section in sections:
            unknown_evidence_ids = set(section.evidence_ids) - available_evidence_ids
            if unknown_evidence_ids:
                raise ValueError("section evidence_ids must reference evidence_items in this packet")
        object.__setattr__(self, "sections", sections)
        if self.fundamentals is not None and not isinstance(self.fundamentals, PacketFundamentals):
            raise TypeError("fundamentals must be PacketFundamentals or None")


@dataclass(frozen=True, slots=True)
class PacketComponentCoverage:
    """Per-endpoint reuse and provenance attached to a research packet."""

    endpoint: ProviderEndpoint
    reuse_status: ReuseStatus
    freshness: FreshnessClass
    reliability: ReliabilityClass
    fiscal_period: date | None
    source_date: date | None
    fetched_at: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, ProviderEndpoint):
            raise TypeError("endpoint must be a ProviderEndpoint")
        if not isinstance(self.reuse_status, ReuseStatus):
            raise TypeError("reuse_status must be a ReuseStatus")
        if not isinstance(self.freshness, FreshnessClass):
            raise TypeError("freshness must be a FreshnessClass")
        if not isinstance(self.reliability, ReliabilityClass):
            raise TypeError("reliability must be a ReliabilityClass")
        if self.fiscal_period is not None:
            _require_date(self.fiscal_period, field_name="fiscal_period")
        if self.source_date is not None:
            _require_date(self.source_date, field_name="source_date")
        if self.fetched_at is not None:
            _require_aware_datetime(self.fetched_at, field_name="fetched_at")
        if self.reuse_status is ReuseStatus.MISSING and self.freshness is not FreshnessClass.UNKNOWN:
            raise ValueError("MISSING coverage freshness must be UNKNOWN")
        if self.reuse_status in {ReuseStatus.FETCHED_THIS_CYCLE, ReuseStatus.REUSED_CURRENT}:
            if self.fetched_at is None or self.source_date is None:
                raise ValueError("FETCHED_THIS_CYCLE and REUSED_CURRENT coverage require fetched_at and source_date")


@dataclass(frozen=True, slots=True)
class DerivedMetric:
    """A named derived metric placeholder; formulas land in a later lane."""

    metric_id: str
    value: Decimal | MissingData
    formula_id: str
    input_keys: tuple[str, ...] | list[str]
    reliability: ReliabilityClass
    freshness: FreshnessClass

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_id", _require_identifier(self.metric_id, field_name="metric_id"))
        if not isinstance(self.value, (Decimal, MissingData)):
            raise TypeError("value must be a Decimal or MissingData")
        if isinstance(self.value, Decimal) and not self.value.is_finite():
            raise ValueError("value must be finite")
        object.__setattr__(self, "formula_id", _require_identifier(self.formula_id, field_name="formula_id"))
        if not isinstance(self.input_keys, (tuple, list)):
            raise TypeError("input_keys must be a tuple or list of strings")
        input_keys = tuple(_require_identifier(item, field_name="input_keys item") for item in self.input_keys)
        if len(set(input_keys)) != len(input_keys):
            raise ValueError("input_keys must not contain duplicates")
        object.__setattr__(self, "input_keys", input_keys)
        if not isinstance(self.reliability, ReliabilityClass):
            raise TypeError("reliability must be a ReliabilityClass")
        if not isinstance(self.freshness, FreshnessClass):
            raise TypeError("freshness must be a FreshnessClass")
        if isinstance(self.value, Decimal) and self.reliability is not ReliabilityClass.DERIVED_DETERMINISTIC:
            raise ValueError("present derived metrics must use DERIVED_DETERMINISTIC reliability")


@dataclass(frozen=True, slots=True)
class PacketFundamentals:
    """Endpoint coverage and derived metrics later attached to a ResearchPacket."""

    coverage: tuple[PacketComponentCoverage, ...] | list[PacketComponentCoverage]
    derived: tuple[DerivedMetric, ...] | list[DerivedMetric] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.coverage, (tuple, list)):
            raise TypeError("coverage must be a tuple or list of PacketComponentCoverage instances")
        coverage = tuple(self.coverage)
        if not all(isinstance(item, PacketComponentCoverage) for item in coverage):
            raise TypeError("coverage must contain PacketComponentCoverage instances")
        endpoints = tuple(item.endpoint for item in coverage)
        if len(set(endpoints)) != len(endpoints):
            raise ValueError("coverage must not contain duplicate endpoints")
        object.__setattr__(self, "coverage", coverage)
        if not isinstance(self.derived, (tuple, list)):
            raise TypeError("derived must be a tuple or list of DerivedMetric instances")
        derived = tuple(self.derived)
        if not all(isinstance(item, DerivedMetric) for item in derived):
            raise TypeError("derived must contain DerivedMetric instances")
        metric_ids = tuple(item.metric_id for item in derived)
        if len(set(metric_ids)) != len(metric_ids):
            raise ValueError("derived must not contain duplicate metric_id values")
        object.__setattr__(self, "derived", derived)


@dataclass(frozen=True, slots=True)
class ResearchBatch:
    """An ordered, immutable packet container for one decision cycle."""

    batch_id: str
    decision_cycle_id: UUID
    portfolio_id: UUID
    manager_type: str
    created_at: datetime
    as_of_timestamp: datetime
    packets: tuple[ResearchPacket, ...] | list[ResearchPacket]
    screening_run_id: UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "batch_id", _require_identifier(self.batch_id, field_name="batch_id"))
        if not isinstance(self.decision_cycle_id, UUID):
            raise TypeError("decision_cycle_id must be a UUID")
        if not isinstance(self.portfolio_id, UUID):
            raise TypeError("portfolio_id must be a UUID")
        object.__setattr__(self, "manager_type", _canonical_upper_text(self.manager_type, field_name="manager_type"))
        if self.screening_run_id is not None and not isinstance(self.screening_run_id, UUID):
            raise TypeError("screening_run_id must be a UUID")
        created_at = _require_aware_datetime(self.created_at, field_name="created_at")
        as_of_timestamp = _require_aware_datetime(self.as_of_timestamp, field_name="as_of_timestamp")
        if created_at < as_of_timestamp:
            raise ValueError("created_at must not precede as_of_timestamp")
        if not isinstance(self.packets, (tuple, list)):
            raise TypeError("packets must be a tuple or list of ResearchPacket instances")
        packets = tuple(self.packets)
        if not packets:
            raise ValueError("packets must not be empty")
        if not all(isinstance(packet, ResearchPacket) for packet in packets):
            raise TypeError("packets must contain ResearchPacket instances")
        packet_ids = tuple(packet.packet_id for packet in packets)
        if len(set(packet_ids)) != len(packet_ids):
            raise ValueError("packets must not contain duplicate packet_id values")
        candidate_ids = tuple(packet.candidate_id for packet in packets)
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("packets must not contain duplicate candidate_id values")
        for packet in packets:
            if packet.as_of_timestamp > as_of_timestamp:
                raise ValueError("packet as_of_timestamp must not exceed batch as_of_timestamp")
        for index, packet in enumerate(packets):
            if any(_security_components_match(packet, previous) for previous in packets[:index]):
                raise ValueError("packets must not contain duplicate or ambiguous security identities")
        object.__setattr__(self, "packets", packets)
