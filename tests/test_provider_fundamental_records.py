from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.provider_fundamentals import (
    FreshnessClass,
    ProviderEndpoint,
    ProviderFundamentalRecord,
    ReliabilityClass,
    ReuseStatus,
)
from agentic_portfolio_lab.domain.research import (
    DerivedMetric,
    MissingData,
    MissingDataReason,
    PacketComponentCoverage,
    PacketFundamentals,
)
from agentic_portfolio_lab.domain.research_provider import (
    NormalizedBalanceFacts,
    NormalizedCashFlowFacts,
    NormalizedEarningsFacts,
    NormalizedIncomeFacts,
    NormalizedOverviewFacts,
    SourceResearchDocument,
    SourceResearchRecord,
)


UTC = timezone.utc
FETCHED_AT = datetime(2026, 8, 17, 16, tzinfo=UTC)
SOURCE_DATE = date(2026, 6, 30)


def _security() -> SecurityIdentity:
    return SecurityIdentity("AAPL", "EQUITY", "NASDAQ", "USD")


def _record(**overrides: object) -> ProviderFundamentalRecord:
    values = dict(
        record_id="fund-aapl-income-2026q2",
        security=_security(),
        provider_identity="alpha-vantage",
        endpoint=ProviderEndpoint.INCOME_STATEMENT,
        fiscal_period=SOURCE_DATE,
        source_date=SOURCE_DATE,
        fetched_at=FETCHED_AT,
        facts=(("total_revenue", "100"), ("net_income", "20")),
    )
    values.update(overrides)
    return ProviderFundamentalRecord(**values)  # type: ignore[arg-type]


def _source() -> SourceResearchRecord:
    return SourceResearchRecord("ALPHA_VANTAGE_OVERVIEW", "Overview", SOURCE_DATE, (("company_name", "Apple"),))


def test_provider_fundamental_record_accepts_normalized_facts() -> None:
    record = _record()

    assert record.record_id == "fund-aapl-income-2026q2"
    assert record.facts == (("total_revenue", "100"), ("net_income", "20"))
    assert record.fiscal_period == SOURCE_DATE


def test_provider_fundamental_record_rejects_naive_fetched_at() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _record(fetched_at=datetime(2026, 8, 17, 16))


@pytest.mark.parametrize("value", ("", "  ", "N/A", "n/a", "None", "none"))
def test_provider_fundamental_record_rejects_na_like_fact_values(value: str) -> None:
    with pytest.raises(ValueError):
        _record(facts=(("total_revenue", value),))


def test_provider_fundamental_record_rejects_duplicate_keys_and_future_source_date() -> None:
    with pytest.raises(ValueError, match="unique"):
        _record(facts=(("total_revenue", "1"), ("total_revenue", "2")))
    with pytest.raises(ValueError, match="source_date"):
        _record(source_date=date(2026, 8, 18))


def test_provider_fundamental_record_allows_empty_facts_when_all_values_missing() -> None:
    record = _record(facts=(), fiscal_period=None)

    assert record.facts == ()
    assert record.fiscal_period is None


def test_packet_component_coverage_enforces_missing_and_reuse_timestamps() -> None:
    missing = PacketComponentCoverage(
        endpoint=ProviderEndpoint.BALANCE_SHEET,
        reuse_status=ReuseStatus.MISSING,
        freshness=FreshnessClass.UNKNOWN,
        reliability=ReliabilityClass.PRIMARY_STATEMENT,
        fiscal_period=None,
        source_date=None,
        fetched_at=None,
    )
    reused = PacketComponentCoverage(
        endpoint=ProviderEndpoint.INCOME_STATEMENT,
        reuse_status=ReuseStatus.REUSED_CURRENT,
        freshness=FreshnessClass.FRESH,
        reliability=ReliabilityClass.PRIMARY_STATEMENT,
        fiscal_period=SOURCE_DATE,
        source_date=SOURCE_DATE,
        fetched_at=FETCHED_AT,
    )

    assert missing.reuse_status is ReuseStatus.MISSING
    assert reused.fetched_at == FETCHED_AT

    with pytest.raises(ValueError, match="UNKNOWN"):
        PacketComponentCoverage(
            endpoint=ProviderEndpoint.CASH_FLOW,
            reuse_status=ReuseStatus.MISSING,
            freshness=FreshnessClass.FRESH,
            reliability=ReliabilityClass.PRIMARY_STATEMENT,
            fiscal_period=None,
            source_date=None,
            fetched_at=None,
        )
    with pytest.raises(ValueError, match="fetched_at"):
        PacketComponentCoverage(
            endpoint=ProviderEndpoint.OVERVIEW,
            reuse_status=ReuseStatus.FETCHED_THIS_CYCLE,
            freshness=FreshnessClass.FRESH,
            reliability=ReliabilityClass.PRIMARY_STATEMENT,
            fiscal_period=SOURCE_DATE,
            source_date=None,
            fetched_at=None,
        )


def test_derived_metric_and_packet_fundamentals_are_type_only_placeholders() -> None:
    derived = DerivedMetric(
        metric_id="fcf",
        value=Decimal("10"),
        formula_id="fcf-v1",
        input_keys=("operating_cash_flow", "capex"),
        reliability=ReliabilityClass.DERIVED_DETERMINISTIC,
        freshness=FreshnessClass.FRESH,
    )
    missing = DerivedMetric(
        metric_id="ev",
        value=MissingData(MissingDataReason.NOT_AVAILABLE),
        formula_id="ev-v1",
        input_keys=("market_cap", "debt", "cash"),
        reliability=ReliabilityClass.DERIVED_DETERMINISTIC,
        freshness=FreshnessClass.UNKNOWN,
    )
    fundamentals = PacketFundamentals(
        coverage=(
            PacketComponentCoverage(
                endpoint=ProviderEndpoint.CASH_FLOW,
                reuse_status=ReuseStatus.FETCHED_THIS_CYCLE,
                freshness=FreshnessClass.FRESH,
                reliability=ReliabilityClass.PRIMARY_STATEMENT,
                fiscal_period=SOURCE_DATE,
                source_date=SOURCE_DATE,
                fetched_at=FETCHED_AT,
            ),
        ),
        derived=(derived, missing),
    )

    assert fundamentals.derived[0].value == Decimal("10")
    with pytest.raises(ValueError, match="DERIVED_DETERMINISTIC"):
        DerivedMetric(
            metric_id="fcf",
            value=Decimal("10"),
            formula_id="fcf-v1",
            input_keys=("operating_cash_flow",),
            reliability=ReliabilityClass.PROVIDER_COMPUTED,
            freshness=FreshnessClass.FRESH,
        )


def test_source_research_document_defaults_new_statement_fields() -> None:
    overview = NormalizedOverviewFacts(
        source=_source(),
        company_name="Apple",
        description=None,
        exchange="NASDAQ",
        currency="USD",
        asset_type="EQUITY",
        sector=None,
        industry=None,
        market_cap=None,
        pe_ratio=None,
        peg_ratio=None,
        eps=None,
        revenue_per_share=None,
        profit_margin=None,
        operating_margin=None,
        return_on_equity=None,
        quarterly_revenue_growth=None,
        quarterly_earnings_growth=None,
        fifty_two_week_high=None,
        fifty_two_week_low=None,
        analyst_target_price=None,
        price_to_book_ratio=None,
        beta=None,
        dividend_yield=None,
        latest_quarter="2026-06-30",
    )
    income = NormalizedIncomeFacts(_source(), "2026-06-30", "USD", "100", None, None, "20")
    earnings = NormalizedEarningsFacts(_source(), "2026-07-30", "2026-06-30", "1", None, None, None)
    document = SourceResearchDocument(
        security=_security(),
        provider_identity="alpha-vantage",
        overview=overview,
        income_statement=income,
        earnings=earnings,
    )

    assert document.balance_sheet is None
    assert document.cash_flow is None
    balance = NormalizedBalanceFacts(_source(), "2026-06-30", "USD", "50", "10", "80", "20", "1000")
    cash_flow = NormalizedCashFlowFacts(_source(), "2026-06-30", "USD", "30", "-5", "1", "0")
    assert balance.periods == ()
    assert balance.cash_field is None
    assert cash_flow.periods == ()
    with_statements = SourceResearchDocument(
        security=_security(),
        provider_identity="alpha-vantage",
        overview=overview,
        income_statement=income,
        earnings=earnings,
        balance_sheet=balance,
        cash_flow=cash_flow,
    )
    assert with_statements.balance_sheet == balance
    assert with_statements.cash_flow == cash_flow
