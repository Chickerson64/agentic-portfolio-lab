"""Shared deterministic selection of one authoritative persisted ResearchBatch."""

from __future__ import annotations

from agentic_portfolio_lab.domain.research import ResearchBatch


def latest_authoritative_research_batch(
    batches: tuple[ResearchBatch, ...],
) -> ResearchBatch:
    """Select by immutable creation chronology; ties are intentionally invalid."""
    if not batches:
        raise ValueError("no persisted ResearchBatch is available")
    latest_at = max(batch.created_at for batch in batches)
    latest = tuple(batch for batch in batches if batch.created_at == latest_at)
    if len(latest) != 1:
        raise ValueError("latest persisted ResearchBatch is ambiguous at its created_at timestamp")
    return latest[0]
