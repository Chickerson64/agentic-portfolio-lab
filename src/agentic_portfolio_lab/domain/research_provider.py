"""Provider-neutral inputs for factual research packet assembly."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from .portfolio import SecurityIdentity, _require_non_empty_text


class ResearchProviderError(RuntimeError):
    """A research provider could not supply a valid source document."""


class ResearchProviderConfigurationError(ResearchProviderError):
    """A required provider credential is unavailable."""


@dataclass(frozen=True, slots=True)
class SourceResearchRecord:
    source_type: str
    source_title: str
    source_date: date
    facts: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_type", _require_non_empty_text(self.source_type, field_name="source_type").strip())
        object.__setattr__(self, "source_title", _require_non_empty_text(self.source_title, field_name="source_title").strip())
        if not isinstance(self.source_date, date):
            raise TypeError("source_date must be a date")


@dataclass(frozen=True, slots=True)
class SourceResearchDocument:
    security: SecurityIdentity
    provider_identity: str
    overview: "NormalizedOverviewFacts"
    income_statement: "NormalizedIncomeFacts"
    earnings: "NormalizedEarningsFacts"
    balance_sheet: "NormalizedBalanceFacts | None" = None
    cash_flow: "NormalizedCashFlowFacts | None" = None

@dataclass(frozen=True, slots=True)
class NormalizedIncomeFacts:
    source: SourceResearchRecord
    fiscal_date_ending: str | None
    reported_currency: str | None
    total_revenue: str | None
    gross_profit: str | None
    operating_income: str | None
    net_income: str | None

@dataclass(frozen=True, slots=True)
class NormalizedEarningsFacts:
    source: SourceResearchRecord
    reported_date: str | None
    fiscal_date_ending: str | None
    reported_eps: str | None
    estimated_eps: str | None
    surprise: str | None
    surprise_percentage: str | None

@dataclass(frozen=True, slots=True)
class NormalizedOverviewFacts:
    source: SourceResearchRecord
    company_name: str | None
    description: str | None
    exchange: str | None
    currency: str | None
    asset_type: str | None
    sector: str | None
    industry: str | None
    market_cap: str | None
    pe_ratio: str | None
    peg_ratio: str | None
    eps: str | None
    revenue_per_share: str | None
    profit_margin: str | None
    operating_margin: str | None
    return_on_equity: str | None
    quarterly_revenue_growth: str | None
    quarterly_earnings_growth: str | None
    fifty_two_week_high: str | None
    fifty_two_week_low: str | None
    analyst_target_price: str | None
    price_to_book_ratio: str | None
    beta: str | None
    dividend_yield: str | None
    latest_quarter: str | None


@dataclass(frozen=True, slots=True)
class NormalizedBalanceFacts:
    source: SourceResearchRecord
    fiscal_date_ending: str | None
    reported_currency: str | None
    cash: str | None
    debt: str | None
    current_assets: str | None
    current_liabilities: str | None
    shares_outstanding: str | None


@dataclass(frozen=True, slots=True)
class NormalizedCashFlowFacts:
    source: SourceResearchRecord
    fiscal_date_ending: str | None
    reported_currency: str | None
    operating_cash_flow: str | None
    capex: str | None
    buybacks: str | None
    issuance: str | None


class ResearchProvider(Protocol):
    def get_company_research(self, security: SecurityIdentity) -> SourceResearchDocument: ...
