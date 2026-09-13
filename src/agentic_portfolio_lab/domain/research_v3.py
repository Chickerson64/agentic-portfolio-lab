"""Evidence-oriented V3 research contracts.

V3 deliberately keeps screening context and provider evidence separate.  It is
not a portfolio-construction or trading contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Mapping
from uuid import UUID

from .portfolio import Portfolio, SecurityIdentity, _require_aware_datetime, _require_non_empty_text
from .research import EvidenceItem, MissingData, MissingDataReason, ResearchBatch, ResearchPacket, ResearchSection, UNKNOWN_MISSING
from .research_provider import SourceResearchDocument
from .screening_v2 import ScreeningFeatures, ScreeningProfileIdentity, ScreeningRunV2


class ResearchSubjectRole(StrEnum):
    NEW_CANDIDATE = "NEW_CANDIDATE"
    EXISTING_HOLDING = "EXISTING_HOLDING"


@dataclass(frozen=True, slots=True)
class ScreeningEvidenceContext:
    """Immutable screening lineage carried as context, never as a decision."""
    snapshot_id: str
    profile_identity: ScreeningProfileIdentity
    screening_run_id: UUID
    rank: int | None = None
    features: ScreeningFeatures | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", _require_non_empty_text(self.snapshot_id, field_name="snapshot_id").strip())
        if not isinstance(self.profile_identity, ScreeningProfileIdentity) or not isinstance(self.screening_run_id, UUID):
            raise TypeError("invalid screening lineage")
        if self.rank is not None and (not isinstance(self.rank, int) or self.rank <= 0):
            raise ValueError("rank must be positive when supplied")
        if self.features is not None and not isinstance(self.features, ScreeningFeatures):
            raise TypeError("features must be ScreeningFeatures or None")


@dataclass(frozen=True, slots=True)
class ResearchV3Evidence:
    evidence_id: str
    provider_identity: str
    source_type: str
    source_title: str | MissingData
    source_date: date | MissingData
    reference: str | MissingData
    freshness: str
    missing_data: MissingData | None = None
    contradiction: str | MissingData | None = None

    def __post_init__(self) -> None:
        for field_name in ("evidence_id", "provider_identity", "source_type", "freshness"):
            object.__setattr__(self, field_name, _require_non_empty_text(getattr(self, field_name), field_name=field_name).strip())
        if not isinstance(self.source_title, (str, MissingData)) or not isinstance(self.source_date, (date, MissingData)):
            raise TypeError("source title/date must be source values or MissingData")
        if isinstance(self.source_title, str):
            object.__setattr__(self, "source_title", self.source_title.strip())
        if isinstance(self.reference, str):
            object.__setattr__(self, "reference", self.reference.strip())
        if self.missing_data is not None and not isinstance(self.missing_data, MissingData):
            raise TypeError("missing_data must be MissingData or None")


@dataclass(frozen=True, slots=True)
class ResearchV3Subject:
    subject_id: str
    security: SecurityIdentity
    role: ResearchSubjectRole
    researched_at: datetime
    evidence: tuple[ResearchV3Evidence, ...]
    provider_identity: str
    screening_context: ScreeningEvidenceContext | None = None
    missing_data: tuple[MissingData, ...] = ()
    contradictions: tuple[str, ...] = ()
    provider_document: SourceResearchDocument | None = None

    @property
    def subject_role(self) -> ResearchSubjectRole:
        return self.role

    @property
    def evidence_references(self) -> tuple[str, ...]:
        return tuple(item.reference for item in self.evidence if isinstance(item.reference, str))

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _require_non_empty_text(self.subject_id, field_name="subject_id").strip())
        if not isinstance(self.security, SecurityIdentity) or not isinstance(self.role, ResearchSubjectRole):
            raise TypeError("invalid V3 subject identity or role")
        _require_aware_datetime(self.researched_at, field_name="researched_at")
        if not self.evidence or not all(isinstance(item, ResearchV3Evidence) for item in self.evidence):
            raise ValueError("evidence must contain ResearchV3Evidence")
        if not isinstance(self.provider_identity, str) or not self.provider_identity.strip():
            raise ValueError("provider_identity must not be empty")
        if self.role is ResearchSubjectRole.NEW_CANDIDATE and self.screening_context is None:
            raise ValueError("new candidates require screening context")
        if self.screening_context is not None and self.screening_context.snapshot_id.strip() == "":
            raise ValueError("screening context requires snapshot lineage")
        if not all(isinstance(item, MissingData) for item in self.missing_data):
            raise TypeError("missing_data must contain MissingData")
        if not all(isinstance(item, str) and item.strip() for item in self.contradictions):
            raise TypeError("contradictions must contain non-empty strings")


@dataclass(frozen=True, slots=True)
class ResearchBatchV3:
    batch_id: str
    screening_run_id: UUID
    snapshot_id: str
    profile_identity: ScreeningProfileIdentity
    created_at: datetime
    subjects: tuple[ResearchV3Subject, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "batch_id", _require_non_empty_text(self.batch_id, field_name="batch_id").strip())
        if not isinstance(self.screening_run_id, UUID) or not isinstance(self.profile_identity, ScreeningProfileIdentity):
            raise TypeError("invalid V3 batch lineage")
        object.__setattr__(self, "snapshot_id", _require_non_empty_text(self.snapshot_id, field_name="snapshot_id").strip())
        _require_aware_datetime(self.created_at, field_name="created_at")
        if not self.subjects or not all(isinstance(x, ResearchV3Subject) for x in self.subjects):
            raise ValueError("subjects must not be empty")
        if len({x.subject_id for x in self.subjects}) != len(self.subjects):
            raise ValueError("subjects must have unique subject_id values")
        if len({x.security for x in self.subjects}) != len(self.subjects):
            raise ValueError("subjects must have unique securities")
        for subject in self.subjects:
            if subject.screening_context is not None and (
                subject.screening_context.snapshot_id != self.snapshot_id
                or subject.screening_context.profile_identity != self.profile_identity
                or subject.screening_context.screening_run_id != self.screening_run_id
            ):
                raise ValueError("subject screening context must match batch lineage")

    @property
    def research_subjects(self) -> tuple[ResearchV3Subject, ...]:
        return self.subjects

    def as_manager_research_batch(self, *, portfolio_id: UUID, decision_cycle_id: UUID | None = None) -> ResearchBatch:
        """Adapt V3 evidence to the unchanged V2 manager boundary."""
        packets = []
        for subject in self.subjects:
            items = tuple(EvidenceItem(
                item.evidence_id,
                item.source_type,
                item.source_title if isinstance(item.source_title, str) else "Unavailable source",
                item.source_date if isinstance(item.source_date, date) else self.created_at.date(),
                item.reference if isinstance(item.reference, str) else "Unavailable source evidence",
            ) for item in subject.evidence)
            packets.append(ResearchPacket(
                packet_id=f"{self.batch_id}:{subject.subject_id}",
                candidate_id=subject.subject_id,
                ticker=subject.security.ticker,
                security_type=subject.security.security_type,
                as_of_timestamp=subject.researched_at,
                evidence_items=items,
                sections=tuple(ResearchSection(f"V3_{index}", item.reference if isinstance(item.reference, str) else UNKNOWN_MISSING, (item.evidence_id,)) for index, item in enumerate(subject.evidence)),
                exchange=subject.security.exchange,
                currency=subject.security.currency,
            ))
        return ResearchBatch(
            self.batch_id, decision_cycle_id or self.screening_run_id, portfolio_id,
            "VALUE", self.created_at, self.created_at, tuple(packets), self.screening_run_id,
        )


# Friendly names for callers that use the version before the noun.
ResearchV3Batch = ResearchBatchV3
ResearchV3Item = ResearchV3Subject


def screening_context_for(run: ScreeningRunV2, security: SecurityIdentity) -> ScreeningEvidenceContext | None:
    result = next((item for item in run.results if item.security == security), None)
    if result is None:
        return None
    return ScreeningEvidenceContext(run.universe_snapshot_id, run.profile.identity, run.screening_run_id, result.rank, result.features)
