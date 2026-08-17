"""Screening-run contracts for allocating research capacity.

The screener is not a portfolio manager. Rank and slot role stay on these
audit types and must not be copied onto manager recommendation context.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from .portfolio import SecurityIdentity, _require_aware_datetime, _require_non_empty_text
from .universe import require_managed_universe_identities

_MAX_SELECTED = 5
_MAX_RANKED = 3
_MAX_COVERAGE = 1
_MAX_REPORTING_CYCLE = 1


class ResearchSlotRole(StrEnum):
    RANKED = "RANKED"
    COVERAGE = "COVERAGE"
    REPORTING_CYCLE = "REPORTING_CYCLE"


def _normalize_rank_key(value: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError("rank_key must be a tuple or list of strings")
    key = tuple(value)
    if not all(isinstance(item, str) for item in key):
        raise TypeError("rank_key must contain strings")
    for item in key:
        if not item.strip():
            raise ValueError("rank_key items must not be empty")
    return key


@dataclass(frozen=True, slots=True)
class ScreeningCandidateResult:
    """One universe identity's eligibility, rank key, and optional slot."""

    security: SecurityIdentity
    eligible: bool
    ineligibility_reason: str | None
    rank_key: tuple[str, ...] | list[str]
    rank_reason: str
    slot_role: ResearchSlotRole | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        if not isinstance(self.eligible, bool):
            raise TypeError("eligible must be a bool")
        object.__setattr__(self, "rank_key", _normalize_rank_key(self.rank_key))
        object.__setattr__(self, "rank_reason", _require_non_empty_text(self.rank_reason, field_name="rank_reason").strip())
        if self.slot_role is not None and not isinstance(self.slot_role, ResearchSlotRole):
            raise TypeError("slot_role must be a ResearchSlotRole or None")
        if self.eligible:
            if self.ineligibility_reason is not None:
                raise ValueError("ineligibility_reason must be None when eligible")
            return
        if self.ineligibility_reason is None:
            raise ValueError("ineligibility_reason is required when not eligible")
        object.__setattr__(
            self,
            "ineligibility_reason",
            _require_non_empty_text(self.ineligibility_reason, field_name="ineligibility_reason").strip(),
        )
        if self.slot_role is not None:
            raise ValueError("ineligible candidates must not have a slot_role")


@dataclass(frozen=True, slots=True)
class ScreeningRun:
    """Immutable audit record of one research-capacity allocation."""

    screening_run_id: UUID
    universe_version: str
    universe_identities: tuple[SecurityIdentity, ...] | list[SecurityIdentity]
    as_of: datetime
    results: tuple[ScreeningCandidateResult, ...] | list[ScreeningCandidateResult]
    selected: tuple[SecurityIdentity, ...] | list[SecurityIdentity]

    def __post_init__(self) -> None:
        if not isinstance(self.screening_run_id, UUID):
            raise TypeError("screening_run_id must be a UUID")
        object.__setattr__(
            self,
            "universe_version",
            _require_non_empty_text(self.universe_version, field_name="universe_version").strip(),
        )
        universe_identities = require_managed_universe_identities(
            self.universe_identities,
            field_name="universe_identities",
        )
        object.__setattr__(self, "universe_identities", universe_identities)
        _require_aware_datetime(self.as_of, field_name="as_of")

        if not isinstance(self.results, (tuple, list)):
            raise TypeError("results must be a tuple or list of ScreeningCandidateResult instances")
        results = tuple(self.results)
        if not all(isinstance(result, ScreeningCandidateResult) for result in results):
            raise TypeError("results must contain ScreeningCandidateResult instances")
        result_securities = tuple(result.security for result in results)
        if len(set(result_securities)) != len(result_securities):
            raise ValueError("results must not contain duplicate security identities")
        if set(result_securities) != set(universe_identities) or len(results) != len(universe_identities):
            raise ValueError("results must cover exactly the universe snapshot identities")
        object.__setattr__(self, "results", results)

        if not isinstance(self.selected, (tuple, list)):
            raise TypeError("selected must be a tuple or list of SecurityIdentity instances")
        selected = tuple(self.selected)
        if not all(isinstance(identity, SecurityIdentity) for identity in selected):
            raise TypeError("selected must contain SecurityIdentity instances")
        if len(selected) > _MAX_SELECTED:
            raise ValueError("selected must contain at most 5 identities")
        if len(set(selected)) != len(selected):
            raise ValueError("selected must not contain duplicate identities")
        object.__setattr__(self, "selected", selected)

        results_by_security = {result.security: result for result in results}
        selected_set = set(selected)
        for identity in selected:
            result = results_by_security.get(identity)
            if result is None:
                raise ValueError("selected identities must appear in results")
            if not result.eligible:
                raise ValueError("selected identities must be eligible")
            if result.slot_role is None:
                raise ValueError("selected identities must have a slot_role")
        for result in results:
            if result.security in selected_set:
                continue
            if result.slot_role is not None:
                raise ValueError("unselected results must not have a research slot role")

        role_counts = {role: 0 for role in ResearchSlotRole}
        for identity in selected:
            role = results_by_security[identity].slot_role
            if role is None:
                raise ValueError("selected identities must have a slot_role")
            role_counts[role] += 1
        if role_counts[ResearchSlotRole.RANKED] > _MAX_RANKED:
            raise ValueError("selected may include at most 3 RANKED slots")
        if role_counts[ResearchSlotRole.COVERAGE] > _MAX_COVERAGE:
            raise ValueError("selected may include at most 1 COVERAGE slot")
        if role_counts[ResearchSlotRole.REPORTING_CYCLE] > _MAX_REPORTING_CYCLE:
            raise ValueError("selected may include at most 1 REPORTING_CYCLE slot")
