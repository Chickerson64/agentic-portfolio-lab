"""Framework-independent boundary for implementations of the Value Manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from .constitution import ValueManagerConstitution
from .policy import ManagerRiskConstitution
from .portfolio import Portfolio, _require_non_empty_text
from .recommendations import PortfolioRecommendation
from .research import ResearchBatch
from .research_v3 import ResearchBatchV3

_VALUE_MANAGER_TYPE = "VALUE"


def _normalize_feedback(value: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError("prior_reviewer_feedback must be a tuple or list of strings")
    return tuple(
        _require_non_empty_text(item, field_name="prior_reviewer_feedback item").strip()
        for item in value
    )


@dataclass(frozen=True, slots=True)
class ValueManagerDecisionContext:
    """Explicit, immutable inputs to one Value Manager decision cycle.

    The ResearchBatch is the authoritative source of decision-cycle and
    portfolio lineage. The context only verifies that its Portfolio agrees
    with that supplied batch; it does not revalidate either domain object.
    """

    portfolio: Portfolio
    research_batch: ResearchBatch | ResearchBatchV3
    constitution: ValueManagerConstitution
    prior_reviewer_feedback: tuple[str, ...] | list[str] = ()
    manager_risk_constitution: ManagerRiskConstitution | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.portfolio, Portfolio):
            raise TypeError("portfolio must be a Portfolio")
        if isinstance(self.research_batch, ResearchBatchV3):
            object.__setattr__(self, "research_batch", self.research_batch.as_manager_research_batch(portfolio_id=self.portfolio.portfolio_id))
        elif not isinstance(self.research_batch, ResearchBatch):
            raise TypeError("research_batch must be a ResearchBatch or ResearchBatchV3")
        if self.research_batch.portfolio_id != self.portfolio.portfolio_id:
            raise ValueError("research_batch portfolio_id must match portfolio")
        if self.research_batch.manager_type != _VALUE_MANAGER_TYPE:
            raise ValueError("research_batch manager_type must be VALUE")
        if not isinstance(self.constitution, ValueManagerConstitution):
            raise TypeError("constitution must be a ValueManagerConstitution")
        if self.manager_risk_constitution is not None:
            if not isinstance(self.manager_risk_constitution, ManagerRiskConstitution):
                raise TypeError("manager_risk_constitution must be a ManagerRiskConstitution or None")
            if self.manager_risk_constitution.manager_type != _VALUE_MANAGER_TYPE:
                raise ValueError("manager_risk_constitution manager_type must be VALUE")
        object.__setattr__(self, "prior_reviewer_feedback", _normalize_feedback(self.prior_reviewer_feedback))

    @property
    def decision_cycle_id(self) -> UUID:
        """Return the decision-cycle lineage supplied by the ResearchBatch."""
        return self.research_batch.decision_cycle_id

    @property
    def constitution_version(self) -> str:
        """Return the constitution's authoritative audit version identifier."""
        return self.constitution.constitution_version


@runtime_checkable
class ValueManager(Protocol):
    """Produces one portfolio-level recommendation from an explicit context.

    Implementations may use deterministic logic or an AI provider, but the
    boundary has no framework, execution, or persistence dependency.
    """

    def decide(self, context: ValueManagerDecisionContext) -> PortfolioRecommendation:
        """Return exactly one manager-intent recommendation for the context."""
