"""Deterministic workflow boundary for one Value Manager decision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .portfolio import _require_aware_datetime
from .recommendations import PortfolioRecommendation, RecommendationAction, RecommendationEvidenceReference
from .research import EvidenceItem
from .value_manager import ValueManager, ValueManagerDecisionContext


def _verify_buy_ticker(context: ValueManagerDecisionContext, ticker: str | None) -> None:
    # The recommendation schema already requires a BUY ticker. Retaining this
    # guard keeps the workflow safe if that schema later changes.
    if ticker is None:
        raise ValueError("BUY recommendation ticker is required")
    matching_packets = tuple(packet for packet in context.research_batch.packets if packet.ticker == ticker)
    if not matching_packets:
        raise ValueError("BUY recommendation ticker must exist in the ResearchBatch")
    if len(matching_packets) != 1:
        raise ValueError("BUY recommendation ticker must match exactly one ResearchPacket")


def _verify_evidence(
    context: ValueManagerDecisionContext,
    references: tuple[RecommendationEvidenceReference, ...],
) -> None:
    evidence_by_id: dict[str, tuple[EvidenceItem, ...]] = {}
    for packet in context.research_batch.packets:
        for evidence in packet.evidence_items:
            evidence_by_id[evidence.evidence_id] = evidence_by_id.get(evidence.evidence_id, ()) + (evidence,)

    for reference in references:
        matches = evidence_by_id.get(reference.evidence_id, ())
        if not matches:
            raise ValueError("recommendation evidence_id must exist in the ResearchBatch")
        if len(matches) != 1:
            raise ValueError("recommendation evidence_id is ambiguous across ResearchPackets")
        evidence = matches[0]
        if (
            reference.source_type != evidence.source_type
            or reference.source_title != evidence.source_title
            or reference.source_date != evidence.source_date
        ):
            raise ValueError("recommendation evidence metadata must match the referenced EvidenceItem")


def _verify_recommendation(
    context: ValueManagerDecisionContext,
    recommendation: PortfolioRecommendation,
) -> None:
    if recommendation.action is RecommendationAction.BUY:
        _verify_buy_ticker(context, recommendation.ticker)
    _verify_evidence(context, recommendation.evidence)


@dataclass(frozen=True, slots=True)
class ValueManagerDecisionResult:
    """One manager recommendation with lineage derived from its input context.

    The context remains the single source of portfolio, batch, decision-cycle,
    manager, and constitution lineage. This object deliberately adds no risk,
    review, approval, or execution state.
    """

    context: ValueManagerDecisionContext
    recommendation: PortfolioRecommendation
    produced_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.context, ValueManagerDecisionContext):
            raise TypeError("context must be a ValueManagerDecisionContext")
        if not isinstance(self.recommendation, PortfolioRecommendation):
            raise TypeError("recommendation must be a PortfolioRecommendation")
        produced_at = _require_aware_datetime(self.produced_at, field_name="produced_at")
        if produced_at < self.context.research_batch.created_at:
            raise ValueError("produced_at must not precede research_batch created_at")
        _verify_recommendation(self.context, self.recommendation)

    @property
    def decision_cycle_id(self) -> UUID:
        """Return the decision-cycle lineage from the supplied ResearchBatch."""
        return self.context.decision_cycle_id

    @property
    def portfolio_id(self) -> UUID:
        """Return the portfolio lineage from the supplied Portfolio."""
        return self.context.portfolio.portfolio_id

    @property
    def manager_type(self) -> str:
        """Return the Value Manager type from the authoritative ResearchBatch."""
        return self.context.research_batch.manager_type

    @property
    def constitution_version(self) -> str:
        """Return the constitution version used to produce this recommendation."""
        return self.context.constitution_version

    @property
    def research_batch_id(self) -> str:
        """Return the immutable ResearchBatch reference used for this decision."""
        return self.context.research_batch.batch_id


@dataclass(frozen=True, slots=True)
class ValueManagerDecisionWorkflow:
    """Invokes a Value Manager and validates recommendation-to-batch linkage.

    The workflow is provider-agnostic. It validates only the cross-boundary
    links which cannot be checked by either the manager-intent schema or the
    research models in isolation.
    """

    manager: ValueManager

    def __post_init__(self) -> None:
        if not isinstance(self.manager, ValueManager) or not callable(getattr(self.manager, "decide", None)):
            raise TypeError("manager must implement the ValueManager protocol")

    def run(
        self,
        context: ValueManagerDecisionContext,
        *,
        produced_at: datetime,
    ) -> ValueManagerDecisionResult:
        """Return one verified manager recommendation for an explicit context."""
        if not isinstance(context, ValueManagerDecisionContext):
            raise TypeError("context must be a ValueManagerDecisionContext")
        _require_aware_datetime(produced_at, field_name="produced_at")

        recommendation = self.manager.decide(context)
        if not isinstance(recommendation, PortfolioRecommendation):
            raise TypeError("ValueManager.decide must return a PortfolioRecommendation")

        return ValueManagerDecisionResult(
            context=context,
            recommendation=recommendation,
            produced_at=produced_at,
        )
