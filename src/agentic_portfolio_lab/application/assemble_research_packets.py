"""Assemble one ResearchPacket from refreshed endpoint records and a cycle price."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Mapping, Sequence
from uuid import uuid4

from agentic_portfolio_lab.application.fundamental_inputs import fundamental_metric_inputs_from_records
from agentic_portfolio_lab.application.fundamental_metrics import derive_fundamental_metrics
from agentic_portfolio_lab.application.refresh_fundamentals import EndpointRefreshStatus, RefreshFundamentalsResult
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.provider_fundamentals import (
    FreshnessClass,
    ProviderEndpoint,
    ReliabilityClass,
    ReuseStatus,
)
from agentic_portfolio_lab.domain.research import (
    DerivedMetric,
    EvidenceItem,
    MissingData,
    MissingDataReason,
    PacketComponentCoverage,
    PacketFundamentals,
    ResearchPacket,
    ResearchSection,
)
from agentic_portfolio_lab.domain.valuation import PriceObservation

_ENDPOINT_EVIDENCE = {
    ProviderEndpoint.OVERVIEW: ("ALPHA_VANTAGE_OVERVIEW", "Alpha Vantage company overview"),
    ProviderEndpoint.INCOME_STATEMENT: ("ALPHA_VANTAGE_INCOME_STATEMENT", "Alpha Vantage quarterly income statement"),
    ProviderEndpoint.BALANCE_SHEET: ("ALPHA_VANTAGE_BALANCE_SHEET", "Alpha Vantage quarterly balance sheet"),
    ProviderEndpoint.CASH_FLOW: ("ALPHA_VANTAGE_CASH_FLOW", "Alpha Vantage quarterly cash flow"),
    ProviderEndpoint.EARNINGS: ("ALPHA_VANTAGE_EARNINGS", "Alpha Vantage quarterly earnings"),
}
_VALUATION_METRICS = ("market_cap", "enterprise_value", "fcf_yield")
_FINANCIAL_METRICS = (
    "net_debt",
    "current_ratio",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "fcf",
    "ttm_ocf",
    "ttm_capex",
    "ttm_fcf",
    "ttm_net_income",
    "ttm_revenue",
    "cash_conversion",
    "share_count_change",
)


def _missing(label: str) -> MissingData:
    return MissingData(MissingDataReason.NOT_AVAILABLE, f"provider did not supply {label}")


def _text_fact(facts: Mapping[str, str], key: str) -> str | MissingData:
    value = facts.get(key)
    return value if value else _missing(key)


def _format_decimal(value: Decimal) -> str:
    return format(value, "f")


def _coverage_freshness(status: EndpointRefreshStatus) -> FreshnessClass:
    if status.reuse_status is ReuseStatus.MISSING:
        return FreshnessClass.UNKNOWN
    if status.reuse_status is ReuseStatus.STALE:
        return FreshnessClass.STALE
    return FreshnessClass.FRESH


def _coverage_reliability(endpoint: ProviderEndpoint) -> ReliabilityClass:
    if endpoint is ProviderEndpoint.OVERVIEW:
        return ReliabilityClass.PROVIDER_COMPUTED
    return ReliabilityClass.PRIMARY_STATEMENT


def coverage_from_statuses(statuses: Sequence[EndpointRefreshStatus]) -> tuple[PacketComponentCoverage, ...]:
    return tuple(
        PacketComponentCoverage(
            endpoint=status.endpoint,
            reuse_status=status.reuse_status,
            freshness=_coverage_freshness(status),
            reliability=_coverage_reliability(status.endpoint),
            fiscal_period=status.record.fiscal_period,
            source_date=status.record.source_date,
            fetched_at=status.record.fetched_at,
        )
        for status in statuses
    )


def _input_freshness(statuses: Sequence[EndpointRefreshStatus]) -> dict[str, FreshnessClass]:
    freshness: dict[str, FreshnessClass] = {"price": FreshnessClass.FRESH}
    for status in statuses:
        klass = _coverage_freshness(status)
        if status.endpoint is ProviderEndpoint.BALANCE_SHEET:
            for key in (
                "cash",
                "total_debt",
                "current_assets",
                "current_liabilities",
                "latest_shares",
                "shares_4q_ago",
                "statement_shares",
            ):
                freshness[key] = klass
        elif status.endpoint is ProviderEndpoint.INCOME_STATEMENT:
            for key in (
                "gross_profit",
                "operating_income",
                "net_income",
                "revenue",
                "quarterly_revenue",
                "quarterly_net_income",
            ):
                freshness[key] = klass
        elif status.endpoint is ProviderEndpoint.CASH_FLOW:
            for key in (
                "operating_cash_flow",
                "capex",
                "quarterly_operating_cash_flow",
                "quarterly_capex",
            ):
                freshness[key] = klass
        elif status.endpoint is ProviderEndpoint.OVERVIEW:
            freshness["overview_shares"] = klass
    return freshness


def _evidence_item(status: EndpointRefreshStatus) -> EvidenceItem:
    source_type, source_title = _ENDPOINT_EVIDENCE[status.endpoint]
    populated = tuple(key for key, _ in status.record.facts)
    claim = (
        "Provider-supplied factual fields: " + ", ".join(populated)
        if populated
        else "Provider-supplied endpoint record with no populated facts"
    )
    return EvidenceItem(
        evidence_id=f"{status.record.security.ticker}-{status.endpoint.value}-{status.record.source_date.isoformat()}",
        source_type=source_type,
        source_title=source_title,
        source_date=status.record.source_date,
        claim_supported=claim,
    )


def _content(values: tuple[tuple[str, str | None], ...]) -> str | MissingData:
    available = tuple(f"{field}: {value}" for field, value in values if value)
    return "; ".join(available) if available else _missing(", ".join(field for field, _ in values))


def _present_derived(metrics: Sequence[DerivedMetric], metric_ids: Sequence[str]) -> tuple[str, ...]:
    wanted = set(metric_ids)
    return tuple(
        f"{metric.metric_id}: {_format_decimal(metric.value)}"
        for metric in metrics
        if metric.metric_id in wanted and isinstance(metric.value, Decimal)
    )


def _section_content(parts: tuple[str, ...], *, missing_label: str) -> str | MissingData:
    return "; ".join(parts) if parts else _missing(missing_label)


def _missing_derived_sections(metrics: Sequence[DerivedMetric]) -> tuple[ResearchSection, ...]:
    return tuple(
        ResearchSection(f"{metric.metric_id}_MISSING", metric.value)
        for metric in metrics
        if isinstance(metric.value, MissingData)
    )


def assemble_research_packet(
    *,
    security: SecurityIdentity,
    refresh: RefreshFundamentalsResult,
    price: PriceObservation,
    as_of: datetime,
) -> ResearchPacket:
    """Build one packet for a selected identity. Rank and slot role are omitted."""

    overview = next(
        (status.record for status in refresh.statuses if status.endpoint is ProviderEndpoint.OVERVIEW),
        None,
    )
    overview_facts = dict(overview.facts) if overview is not None else {}
    earnings = next(
        (status.record for status in refresh.statuses if status.endpoint is ProviderEndpoint.EARNINGS),
        None,
    )
    earnings_facts = dict(earnings.facts) if earnings is not None else {}
    derived = derive_fundamental_metrics(
        fundamental_metric_inputs_from_records(
            refresh.records,
            price=price.observed_price,
            security=security,
            input_freshness=_input_freshness(refresh.statuses),
        )
    )
    evidence = tuple(_evidence_item(status) for status in refresh.statuses)
    evidence_ids = {status.endpoint: item.evidence_id for status, item in zip(refresh.statuses, evidence, strict=True)}

    def _ids(*endpoints: ProviderEndpoint) -> tuple[str, ...]:
        return tuple(evidence_ids[endpoint] for endpoint in endpoints if endpoint in evidence_ids)

    valuation_content = _section_content(
        (f"price: {_format_decimal(price.observed_price)}", *_present_derived(derived, _VALUATION_METRICS)),
        missing_label="price, market_cap, enterprise_value, fcf_yield",
    )
    financial_content = _section_content(
        _present_derived(derived, _FINANCIAL_METRICS),
        missing_label=", ".join(_FINANCIAL_METRICS),
    )
    sections = (
        ResearchSection(
            "COMPANY_OVERVIEW",
            _content(
                (
                    ("company_name", overview_facts.get("company_name")),
                    ("description", overview_facts.get("description")),
                    ("sector", overview_facts.get("sector")),
                    ("industry", overview_facts.get("industry")),
                )
            ),
            _ids(ProviderEndpoint.OVERVIEW),
        ),
        ResearchSection(
            "VALUATION",
            valuation_content,
            _ids(ProviderEndpoint.OVERVIEW, ProviderEndpoint.BALANCE_SHEET, ProviderEndpoint.CASH_FLOW),
        ),
        ResearchSection(
            "FINANCIALS",
            financial_content,
            _ids(ProviderEndpoint.INCOME_STATEMENT, ProviderEndpoint.BALANCE_SHEET, ProviderEndpoint.CASH_FLOW),
        ),
        ResearchSection(
            "EARNINGS_AND_GROWTH",
            _content(
                (
                    ("reported_eps", earnings_facts.get("reported_eps")),
                    ("estimated_eps", earnings_facts.get("estimated_eps")),
                    ("surprise", earnings_facts.get("surprise")),
                    ("surprise_percentage", earnings_facts.get("surprise_percentage")),
                )
            ),
            _ids(ProviderEndpoint.EARNINGS),
        ),
        ResearchSection(
            "RISKS_AND_LIMITATIONS",
            _content(
                (
                    ("fifty_two_week_high", overview_facts.get("fifty_two_week_high")),
                    ("fifty_two_week_low", overview_facts.get("fifty_two_week_low")),
                    ("beta", overview_facts.get("beta")),
                    ("dividend_yield", overview_facts.get("dividend_yield")),
                )
            ),
            _ids(ProviderEndpoint.OVERVIEW),
        ),
        *_missing_derived_sections(derived),
    )
    return ResearchPacket(
        packet_id=f"packet-{security.ticker}-{uuid4()}",
        candidate_id=security.ticker,
        ticker=security.ticker,
        security_type=security.security_type,
        as_of_timestamp=as_of,
        evidence_items=evidence,
        sections=sections,
        company_name=_text_fact(overview_facts, "company_name"),
        exchange=security.exchange,
        currency=security.currency,
        sector=_text_fact(overview_facts, "sector"),
        industry=_text_fact(overview_facts, "industry"),
        fundamentals=PacketFundamentals(coverage=coverage_from_statuses(refresh.statuses), derived=derived),
    )
