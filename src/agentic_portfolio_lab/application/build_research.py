"""Application service for one complete, source-attributed research batch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol, Sequence
from uuid import uuid4

from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.research import EvidenceItem, MissingData, MissingDataReason, ResearchBatch, ResearchPacket, ResearchSection
from agentic_portfolio_lab.domain.research_provider import ResearchProvider, SourceResearchDocument, SourceResearchRecord


class ResearchBatchState(Protocol):
    def append_research_batch(self, batch: ResearchBatch) -> None: ...


def _missing(label: str) -> MissingData:
    return MissingData(MissingDataReason.NOT_AVAILABLE, f"provider did not supply {label}")


def _content(values: tuple[tuple[str, str | None], ...]) -> str | MissingData:
    available = tuple(f"{field}: {value}" for field, value in values if value)
    return "; ".join(available) if available else _missing(", ".join(field for field, _ in values))


@dataclass(frozen=True, slots=True)
class BuildResearchResult:
    batch: ResearchBatch
    provider_identity: str


class BuildResearchService:
    """Fetch every candidate before one durable append-only state transition."""

    def __init__(self, *, provider: ResearchProvider, state: ResearchBatchState, candidate_universe: Sequence[SecurityIdentity], now: Callable[[], datetime] | None = None) -> None:
        self._provider, self._state, self._candidate_universe = provider, state, tuple(candidate_universe)
        self._now = now or (lambda: datetime.now(timezone.utc))

    def build(self, *, portfolio_id, manager_type: str = "VALUE") -> BuildResearchResult:
        as_of = self._now()
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("research clock must return a timezone-aware datetime")
        documents = tuple(self._provider.get_company_research(security) for security in self._candidate_universe)
        packets = tuple(self._packet(document, as_of) for document in documents)
        batch = ResearchBatch(
            batch_id=f"research-{uuid4()}", decision_cycle_id=uuid4(), portfolio_id=portfolio_id,
            manager_type=manager_type, created_at=self._now(), as_of_timestamp=as_of, packets=packets,
        )
        self._state.append_research_batch(batch)
        return BuildResearchResult(batch, documents[0].provider_identity)

    def _packet(self, document: SourceResearchDocument, as_of: datetime) -> ResearchPacket:
        records = (document.overview.source, document.income_statement.source, document.earnings.source)
        evidence = tuple(EvidenceItem(
            evidence_id=f"{document.security.ticker}-{index}-{record.source_date.isoformat()}", source_type=record.source_type,
            source_title=record.source_title, source_date=record.source_date,
            claim_supported="Provider-supplied factual fields: " + ", ".join(key for key, value in record.facts if value),
        ) for index, record in enumerate(records, start=1))
        sections = (
            ResearchSection("COMPANY_OVERVIEW", _content((("company_name", document.overview.company_name), ("description", document.overview.description), ("sector", document.overview.sector), ("industry", document.overview.industry))), (evidence[0].evidence_id,)),
            ResearchSection("VALUATION", _content((("market_cap", document.overview.market_cap), ("pe_ratio", document.overview.pe_ratio), ("peg_ratio", document.overview.peg_ratio), ("price_to_book_ratio", document.overview.price_to_book_ratio), ("eps", document.overview.eps), ("revenue_per_share", document.overview.revenue_per_share), ("profit_margin", document.overview.profit_margin), ("operating_margin", document.overview.operating_margin), ("return_on_equity", document.overview.return_on_equity), ("analyst_target_price", document.overview.analyst_target_price))), (evidence[0].evidence_id,)),
            ResearchSection("FINANCIALS", _content((("total_revenue", document.income_statement.total_revenue), ("gross_profit", document.income_statement.gross_profit), ("operating_income", document.income_statement.operating_income), ("net_income", document.income_statement.net_income))), (evidence[1].evidence_id,)),
            ResearchSection("EARNINGS_AND_GROWTH", _content((("reported_eps", document.earnings.reported_eps), ("estimated_eps", document.earnings.estimated_eps), ("surprise", document.earnings.surprise), ("surprise_percentage", document.earnings.surprise_percentage))), (evidence[2].evidence_id,)),
            ResearchSection("RISKS_AND_LIMITATIONS", _content((("fifty_two_week_high", document.overview.fifty_two_week_high), ("fifty_two_week_low", document.overview.fifty_two_week_low), ("quarterly_revenue_growth", document.overview.quarterly_revenue_growth), ("quarterly_earnings_growth", document.overview.quarterly_earnings_growth), ("beta", document.overview.beta), ("dividend_yield", document.overview.dividend_yield))), (evidence[0].evidence_id,)),
        )
        missing_sections = tuple(ResearchSection(f"{section}_{field}_MISSING", _missing(field)) for section, fields in (("COMPANY_OVERVIEW", (("company_name", document.overview.company_name), ("description", document.overview.description), ("sector", document.overview.sector), ("industry", document.overview.industry))), ("VALUATION", (("market_cap", document.overview.market_cap), ("pe_ratio", document.overview.pe_ratio), ("peg_ratio", document.overview.peg_ratio), ("price_to_book_ratio", document.overview.price_to_book_ratio), ("eps", document.overview.eps), ("revenue_per_share", document.overview.revenue_per_share), ("profit_margin", document.overview.profit_margin), ("operating_margin", document.overview.operating_margin), ("return_on_equity", document.overview.return_on_equity), ("analyst_target_price", document.overview.analyst_target_price))), ("FINANCIALS", (("total_revenue", document.income_statement.total_revenue), ("gross_profit", document.income_statement.gross_profit), ("operating_income", document.income_statement.operating_income), ("net_income", document.income_statement.net_income))), ("EARNINGS", (("reported_eps", document.earnings.reported_eps), ("estimated_eps", document.earnings.estimated_eps), ("surprise", document.earnings.surprise), ("surprise_percentage", document.earnings.surprise_percentage))), ("RISKS_AND_LIMITATIONS", (("fifty_two_week_high", document.overview.fifty_two_week_high), ("fifty_two_week_low", document.overview.fifty_two_week_low), ("quarterly_revenue_growth", document.overview.quarterly_revenue_growth), ("quarterly_earnings_growth", document.overview.quarterly_earnings_growth), ("beta", document.overview.beta), ("dividend_yield", document.overview.dividend_yield)))) for field, value in fields if value is None)
        return ResearchPacket(
            packet_id=f"packet-{document.security.ticker}-{uuid4()}", candidate_id=document.security.ticker,
            ticker=document.security.ticker, security_type=document.security.security_type, as_of_timestamp=as_of,
            evidence_items=evidence, sections=(*sections, *missing_sections), company_name=document.overview.company_name or _missing("company_name"),
            exchange=document.overview.exchange or _missing("exchange"), currency=document.overview.currency or _missing("currency"),
            sector=document.overview.sector or _missing("sector"), industry=document.overview.industry or _missing("industry"),
        )
