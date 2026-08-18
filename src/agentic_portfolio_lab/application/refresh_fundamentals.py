"""Reuse-aware Alpha Vantage fundamentals refresh for Research v2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Protocol, Sequence

from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.provider_fundamentals import ProviderEndpoint, ProviderFundamentalRecord, ReuseStatus
from agentic_portfolio_lab.domain.research_provider import (
    NormalizedBalanceFacts,
    NormalizedCashFlowFacts,
    NormalizedEarningsFacts,
    NormalizedIncomeFacts,
    NormalizedOverviewFacts,
    ResearchProviderError,
)

_PROVIDER_IDENTITY = "alpha-vantage"
_MISSING_FACT_VALUES = frozenset({"n/a", "na", "none"})
_STATEMENT_ENDPOINTS = (
    ProviderEndpoint.INCOME_STATEMENT,
    ProviderEndpoint.BALANCE_SHEET,
    ProviderEndpoint.CASH_FLOW,
    ProviderEndpoint.EARNINGS,
)
_INCOME_PERIOD_FIELDS = (
    "fiscal_date_ending",
    "reported_currency",
    "total_revenue",
    "gross_profit",
    "operating_income",
    "net_income",
)
_BALANCE_PERIOD_FIELDS = (
    "fiscal_date_ending",
    "reported_currency",
    "cash",
    "debt",
    "current_assets",
    "current_liabilities",
    "shares_outstanding",
    "cash_field",
)
_CASH_FLOW_PERIOD_FIELDS = (
    "fiscal_date_ending",
    "reported_currency",
    "operating_cash_flow",
    "capex",
    "buybacks",
    "issuance",
)


class FundamentalEndpointProvider(Protocol):
    def fetch_overview(self, security: SecurityIdentity, *, as_of: datetime | None = None) -> NormalizedOverviewFacts: ...
    def fetch_income_statement(self, security: SecurityIdentity, *, as_of: datetime | None = None) -> NormalizedIncomeFacts: ...
    def fetch_balance_sheet(self, security: SecurityIdentity, *, as_of: datetime | None = None) -> NormalizedBalanceFacts: ...
    def fetch_cash_flow(self, security: SecurityIdentity, *, as_of: datetime | None = None) -> NormalizedCashFlowFacts: ...
    def fetch_earnings(self, security: SecurityIdentity, *, as_of: datetime | None = None) -> NormalizedEarningsFacts: ...


NormalizedEndpointFacts = (
    NormalizedOverviewFacts
    | NormalizedIncomeFacts
    | NormalizedBalanceFacts
    | NormalizedCashFlowFacts
    | NormalizedEarningsFacts
)


@dataclass(frozen=True, slots=True)
class EndpointRefreshStatus:
    endpoint: ProviderEndpoint
    reuse_status: ReuseStatus
    record: ProviderFundamentalRecord


@dataclass(frozen=True, slots=True)
class RefreshFundamentalsResult:
    security: SecurityIdentity
    statuses: tuple[EndpointRefreshStatus, ...]

    @property
    def records(self) -> tuple[ProviderFundamentalRecord, ...]:
        return tuple(status.record for status in self.statuses)

    def status_for(self, endpoint: ProviderEndpoint) -> EndpointRefreshStatus:
        return next(status for status in self.statuses if status.endpoint is endpoint)


class RefreshFundamentalsService:
    """Always fetch OVERVIEW; reuse statement rows when LatestQuarter still matches."""

    def __init__(
        self,
        *,
        provider: FundamentalEndpointProvider,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._now = now or (lambda: datetime.now(timezone.utc))

    def refresh(
        self,
        security: SecurityIdentity,
        cached: Sequence[ProviderFundamentalRecord],
        as_of: datetime,
    ) -> RefreshFundamentalsResult:
        fetched_at = self._now()
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("fundamentals clock must return a timezone-aware datetime")
        overview = self._provider.fetch_overview(security, as_of=as_of)
        latest_quarter = _require_latest_quarter(overview)
        overview_record = provider_fundamental_record_from_normalized(
            security,
            ProviderEndpoint.OVERVIEW,
            overview,
            fetched_at,
        )
        statuses = [
            EndpointRefreshStatus(ProviderEndpoint.OVERVIEW, ReuseStatus.FETCHED_THIS_CYCLE, overview_record),
        ]
        reusable = _reusable_statements(security, cached, latest_quarter)
        if reusable is not None:
            statuses.extend(
                EndpointRefreshStatus(endpoint, ReuseStatus.REUSED_CURRENT, reusable[endpoint])
                for endpoint in _STATEMENT_ENDPOINTS
            )
            return RefreshFundamentalsResult(security, tuple(statuses))
        fetched_statements = (
            (ProviderEndpoint.INCOME_STATEMENT, self._provider.fetch_income_statement(security, as_of=as_of)),
            (ProviderEndpoint.BALANCE_SHEET, self._provider.fetch_balance_sheet(security, as_of=as_of)),
            (ProviderEndpoint.CASH_FLOW, self._provider.fetch_cash_flow(security, as_of=as_of)),
            (ProviderEndpoint.EARNINGS, self._provider.fetch_earnings(security, as_of=as_of)),
        )
        for endpoint, document in fetched_statements:
            statuses.append(
                EndpointRefreshStatus(
                    endpoint,
                    ReuseStatus.FETCHED_THIS_CYCLE,
                    provider_fundamental_record_from_normalized(security, endpoint, document, fetched_at),
                )
            )
        return RefreshFundamentalsResult(security, tuple(statuses))


def provider_fundamental_record_from_normalized(
    security: SecurityIdentity,
    endpoint: ProviderEndpoint,
    document: NormalizedEndpointFacts,
    fetched_at: datetime,
    *,
    provider_identity: str = _PROVIDER_IDENTITY,
) -> ProviderFundamentalRecord:
    """Convert one fetched normalized endpoint into an append-only fundamental record."""

    facts = _facts_from_normalized(document)
    return ProviderFundamentalRecord(
        record_id=_record_id(security, endpoint, fetched_at),
        security=security,
        provider_identity=provider_identity,
        endpoint=endpoint,
        fiscal_period=_fiscal_period(document),
        source_date=document.source.source_date,
        fetched_at=fetched_at,
        facts=facts,
    )


def _require_latest_quarter(overview: NormalizedOverviewFacts) -> date:
    try:
        if overview.latest_quarter is None:
            raise ValueError("missing")
        return date.fromisoformat(overview.latest_quarter)
    except ValueError as error:
        raise ResearchProviderError("OVERVIEW LatestQuarter cannot be parsed") from error


def _reusable_statements(
    security: SecurityIdentity,
    cached: Sequence[ProviderFundamentalRecord],
    latest_quarter: date,
) -> dict[ProviderEndpoint, ProviderFundamentalRecord] | None:
    reusable: dict[ProviderEndpoint, ProviderFundamentalRecord] = {}
    for endpoint in _STATEMENT_ENDPOINTS:
        match = _latest_cached(security, cached, endpoint, latest_quarter)
        if match is None:
            return None
        reusable[endpoint] = match
    return reusable


def _latest_cached(
    security: SecurityIdentity,
    cached: Sequence[ProviderFundamentalRecord],
    endpoint: ProviderEndpoint,
    latest_quarter: date,
) -> ProviderFundamentalRecord | None:
    matches = [
        record
        for record in cached
        if record.security == security and record.endpoint is endpoint and record.fiscal_period == latest_quarter
    ]
    if not matches:
        return None
    return max(matches, key=lambda record: record.fetched_at)


def _record_id(security: SecurityIdentity, endpoint: ProviderEndpoint, fetched_at: datetime) -> str:
    return f"{security.ticker}-{endpoint.value}-{fetched_at.isoformat()}"


def _fiscal_period(document: NormalizedEndpointFacts) -> date | None:
    if isinstance(document, NormalizedOverviewFacts):
        return _parse_date(document.latest_quarter)
    if isinstance(document, NormalizedEarningsFacts):
        return _parse_date(document.fiscal_date_ending)
    return _parse_date(document.fiscal_date_ending) or document.source.source_date


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _facts_from_normalized(document: NormalizedEndpointFacts) -> tuple[tuple[str, str], ...]:
    facts = list(document.source.facts)
    seen = {key for key, _ in facts}
    periods: tuple[object, ...] = ()
    field_names: tuple[str, ...] = ()
    if isinstance(document, NormalizedIncomeFacts):
        periods, field_names = document.periods, _INCOME_PERIOD_FIELDS
    elif isinstance(document, NormalizedBalanceFacts):
        periods, field_names = document.periods, _BALANCE_PERIOD_FIELDS
    elif isinstance(document, NormalizedCashFlowFacts):
        periods, field_names = document.periods, _CASH_FLOW_PERIOD_FIELDS
    for index, period in enumerate(periods):
        for field_name in field_names:
            key = f"period_{index}_{field_name}"
            value = getattr(period, field_name)
            if key in seen:
                continue
            normalized = _fact_value(value)
            if normalized is None:
                continue
            facts.append((key, normalized))
            seen.add(key)
    return tuple(facts)


def _fact_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped.casefold() in _MISSING_FACT_VALUES:
        return None
    return stripped
