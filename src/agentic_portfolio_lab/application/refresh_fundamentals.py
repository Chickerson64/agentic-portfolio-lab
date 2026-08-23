"""Reuse-aware Alpha Vantage fundamentals refresh for Research v2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
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
OVERVIEW_REUSE_MAX_AGE = timedelta(days=7)
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
    """Refresh fundamentals with initial-hydration OVERVIEW reuse and weekly statement reuse."""

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
        if not isinstance(as_of, datetime):
            raise TypeError("as_of must be a datetime")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        fetched_at = self._now()
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("fundamentals clock must return a timezone-aware datetime")
        if not _has_complete_statement_set(security, cached):
            reused_overview = _reusable_overview(security, cached, as_of)
            if reused_overview is not None:
                return self._hydrate_from_cached_overview(security, reused_overview, as_of, fetched_at)
        return self._refresh_with_live_overview(security, cached, as_of, fetched_at)

    def _hydrate_from_cached_overview(
        self,
        security: SecurityIdentity,
        overview_record: ProviderFundamentalRecord,
        as_of: datetime,
        fetched_at: datetime,
    ) -> RefreshFundamentalsResult:
        latest_quarter = _overview_latest_quarter(overview_record)
        if latest_quarter is None:
            raise ResearchProviderError("OVERVIEW LatestQuarter cannot be parsed")
        statement_statuses = _fetch_statement_statuses(self._provider, security, as_of, fetched_at)
        overview_status = EndpointRefreshStatus(
            ProviderEndpoint.OVERVIEW,
            ReuseStatus.REUSED_CURRENT,
            overview_record,
        )
        newest_statement_period = _newest_statement_period(statement_statuses)
        if newest_statement_period is not None and newest_statement_period > latest_quarter:
            overview_status = EndpointRefreshStatus(
                ProviderEndpoint.OVERVIEW,
                ReuseStatus.STALE,
                overview_record,
            )
        return RefreshFundamentalsResult(security, (overview_status, *statement_statuses))

    def _refresh_with_live_overview(
        self,
        security: SecurityIdentity,
        cached: Sequence[ProviderFundamentalRecord],
        as_of: datetime,
        fetched_at: datetime,
    ) -> RefreshFundamentalsResult:
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
        statuses.extend(_fetch_statement_statuses(self._provider, security, as_of, fetched_at))
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


def _has_complete_statement_set(
    security: SecurityIdentity,
    cached: Sequence[ProviderFundamentalRecord],
) -> bool:
    present = {
        record.endpoint
        for record in cached
        if record.security == security and record.endpoint in _STATEMENT_ENDPOINTS
    }
    return all(endpoint in present for endpoint in _STATEMENT_ENDPOINTS)


def _overview_latest_quarter(record: ProviderFundamentalRecord) -> date | None:
    if record.fiscal_period is not None:
        return record.fiscal_period
    return _parse_date(dict(record.facts).get("latest_quarter"))


def _overview_fresh_enough(fetched_at: datetime, as_of: datetime) -> bool:
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        return False
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        return False
    if fetched_at > as_of:
        return False
    return (as_of - fetched_at) <= OVERVIEW_REUSE_MAX_AGE


def _reusable_overview(
    security: SecurityIdentity,
    cached: Sequence[ProviderFundamentalRecord],
    as_of: datetime,
) -> ProviderFundamentalRecord | None:
    matches = [
        record
        for record in cached
        if record.security == security
        and record.endpoint is ProviderEndpoint.OVERVIEW
        and record.provider_identity == _PROVIDER_IDENTITY
        and _overview_latest_quarter(record) is not None
        and _overview_fresh_enough(record.fetched_at, as_of)
    ]
    if not matches:
        return None
    return max(matches, key=lambda record: record.fetched_at)


def _newest_statement_period(statuses: Sequence[EndpointRefreshStatus]) -> date | None:
    periods = tuple(status.record.fiscal_period for status in statuses if status.record.fiscal_period is not None)
    return max(periods) if periods else None


def _fetch_statement_statuses(
    provider: FundamentalEndpointProvider,
    security: SecurityIdentity,
    as_of: datetime,
    fetched_at: datetime,
) -> tuple[EndpointRefreshStatus, ...]:
    fetched_statements = (
        (ProviderEndpoint.INCOME_STATEMENT, provider.fetch_income_statement(security, as_of=as_of)),
        (ProviderEndpoint.BALANCE_SHEET, provider.fetch_balance_sheet(security, as_of=as_of)),
        (ProviderEndpoint.CASH_FLOW, provider.fetch_cash_flow(security, as_of=as_of)),
        (ProviderEndpoint.EARNINGS, provider.fetch_earnings(security, as_of=as_of)),
    )
    return tuple(
        EndpointRefreshStatus(
            endpoint,
            ReuseStatus.FETCHED_THIS_CYCLE,
            provider_fundamental_record_from_normalized(security, endpoint, document, fetched_at),
        )
        for endpoint, document in fetched_statements
    )


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
