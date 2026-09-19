"""Bounded V3 deep-research orchestration."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol
from uuid import uuid4

from agentic_portfolio_lab.domain.portfolio import Portfolio, SecurityIdentity
from agentic_portfolio_lab.domain.research import MissingData, MissingDataReason
from agentic_portfolio_lab.domain.research_provider import ResearchProvider, ResearchProviderError, SourceResearchDocument
from agentic_portfolio_lab.domain.research_v3 import (
    ResearchBatchV3, ResearchSubjectRole, ResearchV3Evidence, ResearchV3Subject,
    CompanyResearchVersion, screening_context_for,
)
from agentic_portfolio_lab.domain.screening_v2 import ScreeningRunV2


class ResearchV3Store(Protocol):
    def save(self, batch: ResearchBatchV3) -> None: ...


class ResearchV3CacheStore(Protocol):
    def latest_company_research(self, security: SecurityIdentity) -> CompanyResearchVersion | None: ...
    def save_company_research(self, version: CompanyResearchVersion) -> None: ...
    def consume_daily_deep_research_budget(self, budget_date, *, limit: int) -> bool: ...


def _document_evidence(security: SecurityIdentity, document: SourceResearchDocument, *, as_of: datetime) -> tuple[tuple[ResearchV3Evidence, ...], tuple[MissingData, ...], tuple[str, ...]]:
    records = (document.overview.source, document.income_statement.source, document.earnings.source)
    if document.balance_sheet is not None:
        records += (document.balance_sheet.source,)
    if document.cash_flow is not None:
        records += (document.cash_flow.source,)
    missing: list[MissingData] = []
    for name, facts in (("overview", document.overview), ("income_statement", document.income_statement), ("earnings", document.earnings), ("balance_sheet", document.balance_sheet), ("cash_flow", document.cash_flow)):
        if facts is None:
            continue
        for field in fields(facts):
            if field.name != "source" and getattr(facts, field.name) is None:
                missing.append(MissingData(MissingDataReason.NOT_AVAILABLE, f"{name}.{field.name}"))
    values: dict[str, set[str]] = {}
    for record in records:
        for key, value in record.facts:
            if value:
                values.setdefault(key, set()).add(value)
    contradictions = tuple(f"{key} has conflicting provider values" for key, values_for_key in sorted(values.items()) if len(values_for_key) > 1)
    evidence = tuple(ResearchV3Evidence(
        f"{security.ticker}:{index}:{record.source_type}", document.provider_identity, record.source_type,
        record.source_title, record.source_date, record.reference or f"{document.provider_identity}:{record.source_type}:{record.source_title}",
        "CURRENT" if record.source_date >= as_of.date() else "STALE",
        next((item for item in missing if item.details and item.details.startswith(("overview.", "income_statement.", "earnings.", "balance_sheet.", "cash_flow."))), None),
        contradictions[0] if contradictions else None,
    ) for index, record in enumerate(records))
    return evidence, tuple(missing), contradictions


class BuildResearchV3Service:
    """Research all holdings and a bounded prefix of screened new candidates."""
    def __init__(self, *, provider: ResearchProvider, store: ResearchV3Store | None = None, cache_store: ResearchV3CacheStore | None = None, now: Callable[[], datetime] | None = None, max_deep_research_subjects: int = 8, cache_freshness: timedelta = timedelta(days=7)) -> None:
        if max_deep_research_subjects <= 0 or cache_freshness <= timedelta(0):
            raise ValueError("research budget and cache freshness must be positive")
        self._provider, self._store = provider, store
        self._cache = cache_store if cache_store is not None else store if all(callable(getattr(store, name, None)) for name in ("latest_company_research", "save_company_research", "consume_daily_deep_research_budget")) else None
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._limit = max_deep_research_subjects
        self._cache_freshness = cache_freshness

    def build(self, *, screening_run: ScreeningRunV2, portfolio: Portfolio) -> ResearchBatchV3:
        holdings = tuple(position.security for position in portfolio.positions if position.quantity > 0)
        candidates = tuple(x for x in screening_run.new_candidates if x not in holdings)
        subjects: list[tuple[SecurityIdentity, ResearchSubjectRole]] = []
        seen: set[SecurityIdentity] = set()
        for security, role in ((*[(x, ResearchSubjectRole.NEW_CANDIDATE) for x in candidates], *[(x, ResearchSubjectRole.EXISTING_HOLDING) for x in holdings])):
            if security not in seen:
                subjects.append((security, role)); seen.add(security)
        if not subjects:
            raise ValueError("V3 batch requires a candidate or nonzero holding")
        created_at = self._now()
        built: list[ResearchV3Subject] = []
        retrieved_this_batch = 0
        for security, role in subjects:
            context = screening_context_for(screening_run, security) if role is ResearchSubjectRole.NEW_CANDIDATE else None
            cached = None if self._cache is None else self._cache.latest_company_research(security)
            if cached is not None and cached.retrieved_at + self._cache_freshness > created_at:
                evidence, missing, contradictions = _document_evidence(security, cached.document, as_of=created_at)
                evidence = tuple(ResearchV3Evidence(item.evidence_id, item.provider_identity, item.source_type, item.source_title, item.source_date, item.reference, "CACHED_FRESH", item.missing_data, item.contradiction) for item in evidence)
                built.append(ResearchV3Subject(f"{security.ticker}:{uuid4()}", security, role, cached.retrieved_at, evidence, cached.document.provider_identity, context, missing, contradictions, cached.document))
                continue
            budget_available = retrieved_this_batch < self._limit
            if budget_available and self._cache is not None:
                budget_available = self._cache.consume_daily_deep_research_budget(created_at.date(), limit=self._limit)
            if not budget_available:
                provider_identity = type(self._provider).__name__
                missing_item = MissingData(
                    MissingDataReason.NOT_AVAILABLE,
                    "Deep research was not retrieved because max_deep_research_subjects was reached.",
                )
                evidence = (ResearchV3Evidence(
                    f"{security.ticker}:deep-research-not-retrieved", provider_identity, "RESEARCH",
                    MissingData(MissingDataReason.NOT_AVAILABLE), MissingData(MissingDataReason.NOT_AVAILABLE),
                    MissingData(MissingDataReason.NOT_AVAILABLE), "NOT_RETRIEVED", missing_item,
                ),)
                built.append(ResearchV3Subject(
                    f"{security.ticker}:{uuid4()}", security, role, created_at, evidence,
                    provider_identity, context, (missing_item,), (), None,
                ))
                continue
            retrieved_this_batch += 1
            try:
                document = self._provider.get_company_research(security)
                if document.security != security:
                    raise ResearchProviderError("provider returned research for a different security")
                if self._cache is not None:
                    # This independent append happens before any later batch,
                    # manager, or cycle persistence can fail.
                    self._cache.save_company_research(CompanyResearchVersion(str(uuid4()), security, created_at, document))
                evidence, missing, contradictions = _document_evidence(security, document, as_of=created_at)
                provider_identity = document.provider_identity
            except ResearchProviderError as error:
                provider_identity = type(self._provider).__name__
                missing = (MissingData(MissingDataReason.NOT_AVAILABLE, str(error)),)
                evidence = (ResearchV3Evidence(f"{security.ticker}:missing", provider_identity, "RESEARCH", MissingData(MissingDataReason.NOT_AVAILABLE), MissingData(MissingDataReason.NOT_AVAILABLE), MissingData(MissingDataReason.NOT_AVAILABLE), "UNKNOWN", missing[0]),)
                document = None
                contradictions = ()
            built.append(ResearchV3Subject(f"{security.ticker}:{uuid4()}", security, role, created_at, evidence, provider_identity, context, missing, contradictions, document))
        batch = ResearchBatchV3(f"research-v3-{uuid4()}", screening_run.screening_run_id, screening_run.universe_snapshot_id, screening_run.profile.identity, created_at, tuple(built))
        if self._store is not None:
            self._store.save(batch)
        return batch
