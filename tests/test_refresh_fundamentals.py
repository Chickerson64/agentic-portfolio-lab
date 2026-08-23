from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from agentic_portfolio_lab.application.fundamental_metrics import FundamentalMetricInputs, derive_fundamental_metrics
from agentic_portfolio_lab.application.market_configuration import RESEARCH_CANDIDATE_UNIVERSE
from agentic_portfolio_lab.application.refresh_fundamentals import (
    OVERVIEW_REUSE_MAX_AGE,
    RefreshFundamentalsService,
    provider_fundamental_record_from_normalized,
)
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.provider_fundamentals import ProviderEndpoint, ProviderFundamentalRecord, ReuseStatus
from agentic_portfolio_lab.domain.research import MissingData, MissingDataReason
from agentic_portfolio_lab.domain.research_provider import ResearchProviderError
from agentic_portfolio_lab.infrastructure.alpha_vantage import AlphaVantageResearchProvider


UTC = timezone.utc
AS_OF = datetime(2026, 8, 17, 16, tzinfo=UTC)
CACHED_AT = datetime(2026, 7, 1, 12, tzinfo=UTC)
RECENT_AT = AS_OF - timedelta(days=2)
PERIOD = date(2026, 6, 30)


def _overview(**extra):
    return {
        "Symbol": "MSFT",
        "Name": "Microsoft",
        "Exchange": "NASDAQ",
        "Currency": "USD",
        "AssetType": "Common Stock",
        "LatestQuarter": "2026-06-30",
        **extra,
    }


def _income(**extra):
    return {"symbol": "MSFT", "quarterlyReports": [{"fiscalDateEnding": "2026-06-30", "totalRevenue": "10", "netIncome": "2"}], **extra}


def _balance(**extra):
    return {
        "symbol": "MSFT",
        "quarterlyReports": [
            {
                "fiscalDateEnding": "2026-06-30",
                "reportedCurrency": "USD",
                "cashAndCashEquivalentsAtCarryingValue": "80",
                "shortLongTermDebtTotal": "20",
                "totalCurrentAssets": "100",
                "totalCurrentLiabilities": "40",
                "commonStockSharesOutstanding": "50",
            }
        ],
        **extra,
    }


def _cash_flow(**extra):
    return {
        "symbol": "MSFT",
        "quarterlyReports": [
            {
                "fiscalDateEnding": "2026-06-30",
                "operatingCashflow": "30",
                "capitalExpenditures": "-5",
                "paymentsForRepurchaseOfCommonStock": "1",
                "proceedsFromIssuanceOfCommonStock": "0",
            }
        ],
        **extra,
    }


def _earnings(**extra):
    return {"symbol": "MSFT", "quarterlyEarnings": [{"reportedDate": "2026-07-30", "fiscalDateEnding": "2026-06-30", "reportedEPS": "1"}], **extra}


def _security():
    return RESEARCH_CANDIDATE_UNIVERSE[0]


def _cached_record(endpoint: ProviderEndpoint, *, fiscal_period=PERIOD, fetched_at=CACHED_AT) -> ProviderFundamentalRecord:
    return ProviderFundamentalRecord(
        record_id=f"cached-{endpoint.value}",
        security=_security(),
        provider_identity="alpha-vantage",
        endpoint=endpoint,
        fiscal_period=fiscal_period,
        source_date=PERIOD,
        fetched_at=fetched_at,
        facts=(("marker", endpoint.value),),
    )


def _cached_overview(
    *,
    fetched_at=CACHED_AT,
    fiscal_period=PERIOD,
    facts: tuple[tuple[str, str], ...] | None = None,
    provider_identity: str = "alpha-vantage",
    security=None,
) -> ProviderFundamentalRecord:
    return ProviderFundamentalRecord(
        record_id="cached-OVERVIEW",
        security=security or _security(),
        provider_identity=provider_identity,
        endpoint=ProviderEndpoint.OVERVIEW,
        fiscal_period=fiscal_period,
        source_date=PERIOD,
        fetched_at=fetched_at,
        facts=facts if facts is not None else (("latest_quarter", "2026-06-30"), ("marker", "OVERVIEW")),
    )


def _statement_payloads() -> dict[str, object]:
    return {
        "INCOME_STATEMENT": _income(),
        "BALANCE_SHEET": _balance(),
        "CASH_FLOW": _cash_flow(),
        "EARNINGS": _earnings(),
    }


def _cached_statements(**overrides: ProviderFundamentalRecord) -> tuple[ProviderFundamentalRecord, ...]:
    records = {
        ProviderEndpoint.INCOME_STATEMENT: _cached_record(ProviderEndpoint.INCOME_STATEMENT),
        ProviderEndpoint.BALANCE_SHEET: _cached_record(ProviderEndpoint.BALANCE_SHEET),
        ProviderEndpoint.CASH_FLOW: _cached_record(ProviderEndpoint.CASH_FLOW),
        ProviderEndpoint.EARNINGS: _cached_record(ProviderEndpoint.EARNINGS),
    }
    records.update(overrides)
    return tuple(records.values())


def _provider(payloads, calls):
    def transport(url):
        query = parse_qs(urlparse(url).query)
        function = query["function"][0]
        calls.append(function)
        if function not in payloads:
            raise AssertionError(f"unexpected Alpha Vantage function {function}")
        return payloads[function]

    return AlphaVantageResearchProvider(api_key="key", transport=transport, sleep=lambda _: None)


def test_non_datetime_as_of_fails_before_provider_io():
    calls = []
    service = RefreshFundamentalsService(provider=_provider({}, calls), now=lambda: AS_OF)

    with pytest.raises(TypeError, match="as_of must be a datetime"):
        service.refresh(_security(), (), "2026-08-17T16:00:00Z")  # type: ignore[arg-type]

    assert calls == []


def test_timezone_naive_as_of_fails_before_provider_io():
    calls = []
    service = RefreshFundamentalsService(provider=_provider({}, calls), now=lambda: AS_OF)

    with pytest.raises(ValueError, match="as_of must be timezone-aware"):
        service.refresh(_security(), (), AS_OF.replace(tzinfo=None))

    assert calls == []


def test_reuse_fetches_overview_only_and_keeps_cached_statement_timestamps():
    calls = []
    cached = _cached_statements()
    service = RefreshFundamentalsService(provider=_provider({"OVERVIEW": _overview()}, calls), now=lambda: AS_OF)
    result = service.refresh(_security(), cached, AS_OF)

    assert calls == ["OVERVIEW"]
    assert result.status_for(ProviderEndpoint.OVERVIEW).reuse_status is ReuseStatus.FETCHED_THIS_CYCLE
    for endpoint, cached_record in zip(
        (ProviderEndpoint.INCOME_STATEMENT, ProviderEndpoint.BALANCE_SHEET, ProviderEndpoint.CASH_FLOW, ProviderEndpoint.EARNINGS),
        cached,
        strict=True,
    ):
        status = result.status_for(endpoint)
        assert status.reuse_status is ReuseStatus.REUSED_CURRENT
        assert status.record is cached_record
        assert status.record.fetched_at == CACHED_AT
        assert status.record.source_date == PERIOD
    assert result.status_for(ProviderEndpoint.OVERVIEW).record.fetched_at == AS_OF
    assert result.status_for(ProviderEndpoint.OVERVIEW).record.fiscal_period == PERIOD


def test_newer_latest_quarter_fetches_all_four_statements():
    calls = []
    cached = _cached_statements()
    payloads = {
        "OVERVIEW": _overview(LatestQuarter="2026-09-30"),
        "INCOME_STATEMENT": _income(quarterlyReports=[{"fiscalDateEnding": "2026-09-30", "totalRevenue": "12"}]),
        "BALANCE_SHEET": _balance(quarterlyReports=[{"fiscalDateEnding": "2026-09-30", "cashAndCashEquivalentsAtCarryingValue": "90"}]),
        "CASH_FLOW": _cash_flow(quarterlyReports=[{"fiscalDateEnding": "2026-09-30", "operatingCashflow": "31"}]),
        "EARNINGS": _earnings(quarterlyEarnings=[{"reportedDate": "2026-10-20", "fiscalDateEnding": "2026-09-30", "reportedEPS": "1.1"}]),
    }
    later = datetime(2026, 10, 21, tzinfo=UTC)
    service = RefreshFundamentalsService(provider=_provider(payloads, calls), now=lambda: later)
    result = service.refresh(_security(), cached, later)

    assert calls == ["OVERVIEW", "INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW", "EARNINGS"]
    assert all(result.status_for(endpoint).reuse_status is ReuseStatus.FETCHED_THIS_CYCLE for endpoint in ProviderEndpoint)
    assert all(status.record is not cached_record for status, cached_record in zip(result.statuses[1:], cached, strict=True))
    assert result.status_for(ProviderEndpoint.INCOME_STATEMENT).record.fetched_at == later
    assert result.status_for(ProviderEndpoint.INCOME_STATEMENT).record.fiscal_period == date(2026, 9, 30)
    assert ("total_revenue", "12") in result.status_for(ProviderEndpoint.INCOME_STATEMENT).record.facts


def test_missing_statement_endpoint_fetches_all_four_even_when_others_match():
    calls = []
    cached = _cached_statements()[:-1]
    payloads = {
        "OVERVIEW": _overview(),
        "INCOME_STATEMENT": _income(),
        "BALANCE_SHEET": _balance(),
        "CASH_FLOW": _cash_flow(),
        "EARNINGS": _earnings(),
    }
    service = RefreshFundamentalsService(provider=_provider(payloads, calls), now=lambda: AS_OF)
    result = service.refresh(_security(), cached, AS_OF)

    assert calls == ["OVERVIEW", "INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW", "EARNINGS"]
    assert all(result.status_for(endpoint).reuse_status is ReuseStatus.FETCHED_THIS_CYCLE for endpoint in _STATEMENT_LIKE)


def test_unparseable_latest_quarter_fails_closed_without_statement_calls():
    calls = []
    service = RefreshFundamentalsService(
        provider=_provider({"OVERVIEW": _overview(LatestQuarter="Q2 2026")}, calls),
        now=lambda: AS_OF,
    )
    with pytest.raises(ResearchProviderError, match="LatestQuarter"):
        service.refresh(_security(), _cached_statements(), AS_OF)
    assert calls == ["OVERVIEW"]


def test_complete_statement_set_still_fetches_overview_when_cached_overview_is_recent():
    calls = []
    cached = (_cached_overview(fetched_at=RECENT_AT), *_cached_statements())
    service = RefreshFundamentalsService(provider=_provider({"OVERVIEW": _overview()}, calls), now=lambda: AS_OF)
    result = service.refresh(_security(), cached, AS_OF)

    assert calls == ["OVERVIEW"]
    assert result.status_for(ProviderEndpoint.OVERVIEW).reuse_status is ReuseStatus.FETCHED_THIS_CYCLE
    assert result.status_for(ProviderEndpoint.INCOME_STATEMENT).reuse_status is ReuseStatus.REUSED_CURRENT


def test_recent_cached_overview_without_statements_reuses_overview_and_fetches_four():
    calls = []
    overview = _cached_overview(fetched_at=RECENT_AT)
    service = RefreshFundamentalsService(provider=_provider(_statement_payloads(), calls), now=lambda: AS_OF)
    result = service.refresh(_security(), (overview,), AS_OF)

    assert calls == ["INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW", "EARNINGS"]
    overview_status = result.status_for(ProviderEndpoint.OVERVIEW)
    assert overview_status.reuse_status is ReuseStatus.REUSED_CURRENT
    assert overview_status.record is overview
    assert overview_status.record.fetched_at == RECENT_AT
    assert overview_status.record.source_date == PERIOD
    assert overview_status.record.facts == overview.facts
    assert overview_status.record.record_id == "cached-OVERVIEW"
    assert all(result.status_for(endpoint).reuse_status is ReuseStatus.FETCHED_THIS_CYCLE for endpoint in _STATEMENT_LIKE)


def test_overview_reuse_requires_exact_security_identity():
    calls = []
    other = SecurityIdentity(
        ticker=_security().ticker,
        security_type=_security().security_type,
        exchange="NYSE",
        currency=_security().currency,
    )
    payloads = {"OVERVIEW": _overview(), **_statement_payloads()}
    service = RefreshFundamentalsService(provider=_provider(payloads, calls), now=lambda: AS_OF)
    result = service.refresh(_security(), (_cached_overview(fetched_at=RECENT_AT, security=other),), AS_OF)

    assert calls[0] == "OVERVIEW"
    assert result.status_for(ProviderEndpoint.OVERVIEW).reuse_status is ReuseStatus.FETCHED_THIS_CYCLE


def test_overview_reuse_requires_alpha_vantage_provider_identity():
    calls = []
    payloads = {"OVERVIEW": _overview(), **_statement_payloads()}
    service = RefreshFundamentalsService(provider=_provider(payloads, calls), now=lambda: AS_OF)
    result = service.refresh(
        _security(),
        (_cached_overview(fetched_at=RECENT_AT, provider_identity="twelve-data"),),
        AS_OF,
    )

    assert calls[0] == "OVERVIEW"
    assert result.status_for(ProviderEndpoint.OVERVIEW).reuse_status is ReuseStatus.FETCHED_THIS_CYCLE


def test_overview_older_than_reuse_max_age_is_fetched():
    calls = []
    too_old = AS_OF - OVERVIEW_REUSE_MAX_AGE - timedelta(seconds=1)
    payloads = {"OVERVIEW": _overview(), **_statement_payloads()}
    service = RefreshFundamentalsService(provider=_provider(payloads, calls), now=lambda: AS_OF)
    result = service.refresh(_security(), (_cached_overview(fetched_at=too_old),), AS_OF)

    assert calls[0] == "OVERVIEW"
    assert result.status_for(ProviderEndpoint.OVERVIEW).reuse_status is ReuseStatus.FETCHED_THIS_CYCLE
    assert (AS_OF - too_old) > OVERVIEW_REUSE_MAX_AGE


def test_overview_exactly_at_reuse_max_age_is_reused():
    calls = []
    boundary = AS_OF - OVERVIEW_REUSE_MAX_AGE
    overview = _cached_overview(fetched_at=boundary)
    service = RefreshFundamentalsService(provider=_provider(_statement_payloads(), calls), now=lambda: AS_OF)
    result = service.refresh(_security(), (overview,), AS_OF)

    assert calls == ["INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW", "EARNINGS"]
    overview_status = result.status_for(ProviderEndpoint.OVERVIEW)
    assert overview_status.reuse_status is ReuseStatus.REUSED_CURRENT
    assert overview_status.record is overview
    assert overview_status.record.fetched_at == boundary
    assert all(
        result.status_for(endpoint).reuse_status is ReuseStatus.FETCHED_THIS_CYCLE
        for endpoint in _STATEMENT_LIKE
    )


def test_overview_fetched_at_after_as_of_is_not_reused():
    calls = []
    payloads = {"OVERVIEW": _overview(), **_statement_payloads()}
    service = RefreshFundamentalsService(provider=_provider(payloads, calls), now=lambda: AS_OF)
    result = service.refresh(
        _security(),
        (_cached_overview(fetched_at=AS_OF + timedelta(minutes=1)),),
        AS_OF,
    )

    assert calls[0] == "OVERVIEW"
    assert result.status_for(ProviderEndpoint.OVERVIEW).reuse_status is ReuseStatus.FETCHED_THIS_CYCLE


def test_overview_without_parseable_latest_quarter_is_not_reused():
    calls = []
    payloads = {"OVERVIEW": _overview(), **_statement_payloads()}
    service = RefreshFundamentalsService(provider=_provider(payloads, calls), now=lambda: AS_OF)
    missing = _cached_overview(fetched_at=RECENT_AT, fiscal_period=None, facts=(("company_name", "Microsoft"),))
    bad = _cached_overview(
        fetched_at=RECENT_AT,
        fiscal_period=None,
        facts=(("latest_quarter", "Q2 2026"),),
    )

    missing_result = service.refresh(_security(), (missing,), AS_OF)
    assert calls[0] == "OVERVIEW"
    assert missing_result.status_for(ProviderEndpoint.OVERVIEW).reuse_status is ReuseStatus.FETCHED_THIS_CYCLE

    calls.clear()
    bad_result = service.refresh(_security(), (bad,), AS_OF)
    assert calls[0] == "OVERVIEW"
    assert bad_result.status_for(ProviderEndpoint.OVERVIEW).reuse_status is ReuseStatus.FETCHED_THIS_CYCLE


def test_reused_overview_is_stale_when_fetched_statements_are_newer():
    calls = []
    older_quarter = date(2026, 3, 31)
    overview = _cached_overview(
        fetched_at=RECENT_AT,
        fiscal_period=older_quarter,
        facts=(("latest_quarter", "2026-03-31"), ("marker", "OVERVIEW")),
    )
    service = RefreshFundamentalsService(provider=_provider(_statement_payloads(), calls), now=lambda: AS_OF)
    result = service.refresh(_security(), (overview,), AS_OF)

    assert calls == ["INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW", "EARNINGS"]
    overview_status = result.status_for(ProviderEndpoint.OVERVIEW)
    assert overview_status.reuse_status is ReuseStatus.STALE
    assert overview_status.record is overview
    assert overview_status.record.fetched_at == RECENT_AT
    assert overview_status.record.source_date == PERIOD
    assert overview.fiscal_period == older_quarter
    assert all(result.status_for(endpoint).reuse_status is ReuseStatus.FETCHED_THIS_CYCLE for endpoint in _STATEMENT_LIKE)
    assert result.status_for(ProviderEndpoint.INCOME_STATEMENT).record.fiscal_period == PERIOD


def test_overview_latest_quarter_from_facts_can_be_reused():
    calls = []
    overview = _cached_overview(
        fetched_at=RECENT_AT,
        fiscal_period=None,
        facts=(("latest_quarter", "2026-06-30"),),
    )
    service = RefreshFundamentalsService(provider=_provider(_statement_payloads(), calls), now=lambda: AS_OF)
    result = service.refresh(_security(), (overview,), AS_OF)

    assert calls == ["INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW", "EARNINGS"]
    assert result.status_for(ProviderEndpoint.OVERVIEW).reuse_status is ReuseStatus.REUSED_CURRENT
    assert result.status_for(ProviderEndpoint.OVERVIEW).record is overview


def test_provider_error_fails_refresh_without_fabricating_statements():
    calls = []
    payloads = {
        "OVERVIEW": _overview(LatestQuarter="2026-09-30"),
        "INCOME_STATEMENT": {"Information": "rate limit"},
    }
    later = datetime(2026, 10, 21, tzinfo=UTC)
    service = RefreshFundamentalsService(provider=_provider(payloads, calls), now=lambda: later)
    with pytest.raises(ResearchProviderError, match="INCOME_STATEMENT"):
        service.refresh(_security(), _cached_statements(), later)
    assert calls == ["OVERVIEW", "INCOME_STATEMENT"]


def test_helper_omits_na_and_includes_endpoint_and_fetched_at_in_record_id():
    provider = AlphaVantageResearchProvider(
        api_key="key",
        transport=lambda _: _income(quarterlyReports=[{"fiscalDateEnding": "2026-06-30", "totalRevenue": "N/A", "netIncome": "2"}]),
        sleep=lambda _: None,
    )
    income = provider.fetch_income_statement(_security())
    record = provider_fundamental_record_from_normalized(_security(), ProviderEndpoint.INCOME_STATEMENT, income, AS_OF)

    assert record.record_id == f"MSFT-INCOME_STATEMENT-{AS_OF.isoformat()}"
    assert "INCOME_STATEMENT" in record.record_id
    assert AS_OF.isoformat() in record.record_id
    assert record.facts == (("net_income", "2"), ("period_0_fiscal_date_ending", "2026-06-30"), ("period_0_net_income", "2"))
    assert all(value.casefold() not in {"n/a", "na", "none"} for _, value in record.facts)


def _period_values(facts: tuple[tuple[str, str], ...], field: str, count: int = 4) -> tuple[Decimal | None, ...]:
    mapped = dict(facts)
    values: list[Decimal | None] = []
    for index in range(count):
        raw = mapped.get(f"period_{index}_{field}")
        values.append(Decimal(raw) if raw is not None else None)
    return tuple(values)


def _cash_flow_reports(*quarters: tuple[str, str, str]):
    return [
        {"fiscalDateEnding": ending, "operatingCashflow": ocf, "capitalExpenditures": capex}
        for ending, ocf, capex in quarters
    ]


def test_four_cash_flow_quarters_survive_fetch_to_record_and_feed_ttm():
    reports = _cash_flow_reports(
        ("2026-06-30", "5", "-2"),
        ("2026-03-31", "4", "-1"),
        ("2025-12-31", "3", "-1"),
        ("2025-09-30", "2", "0"),
        ("2025-06-30", "1", "-9"),
    )
    as_of = datetime(2026, 8, 17, 16, tzinfo=UTC)
    cash_flow = AlphaVantageResearchProvider(
        api_key="key",
        transport=lambda _: _cash_flow(quarterlyReports=reports),
        sleep=lambda _: None,
    ).fetch_cash_flow(_security(), as_of=as_of)
    record = provider_fundamental_record_from_normalized(_security(), ProviderEndpoint.CASH_FLOW, cash_flow, AS_OF)

    ocf = _period_values(record.facts, "operating_cash_flow")
    capex = _period_values(record.facts, "capex")
    assert ocf == (Decimal("5"), Decimal("4"), Decimal("3"), Decimal("2"))
    assert capex == (Decimal("-2"), Decimal("-1"), Decimal("-1"), Decimal("0"))
    assert ("period_4_operating_cash_flow", "1") not in record.facts
    metrics = {metric.metric_id: metric for metric in derive_fundamental_metrics(
        FundamentalMetricInputs(quarterly_operating_cash_flow=ocf, quarterly_capex=capex)
    )}
    assert metrics["ttm_ocf"].value == Decimal("14")
    assert metrics["ttm_capex"].value == Decimal("-4")
    assert metrics["ttm_fcf"].value == Decimal("10")
    assert all(value.casefold() not in {"n/a", "na", "none"} for _, value in record.facts)


def test_fewer_than_four_cash_flow_quarters_leave_ttm_not_available():
    reports = _cash_flow_reports(
        ("2026-06-30", "5", "-2"),
        ("2026-03-31", "4", "-1"),
        ("2025-12-31", "3", "-1"),
    )
    cash_flow = AlphaVantageResearchProvider(
        api_key="key",
        transport=lambda _: _cash_flow(quarterlyReports=reports),
        sleep=lambda _: None,
    ).fetch_cash_flow(_security(), as_of=AS_OF)
    record = provider_fundamental_record_from_normalized(_security(), ProviderEndpoint.CASH_FLOW, cash_flow, AS_OF)

    ocf = _period_values(record.facts, "operating_cash_flow")
    capex = _period_values(record.facts, "capex")
    assert ocf == (Decimal("5"), Decimal("4"), Decimal("3"), None)
    assert capex == (Decimal("-2"), Decimal("-1"), Decimal("-1"), None)
    metrics = {metric.metric_id: metric for metric in derive_fundamental_metrics(
        FundamentalMetricInputs(quarterly_operating_cash_flow=ocf, quarterly_capex=capex)
    )}
    unavailable = MissingData(MissingDataReason.NOT_AVAILABLE, "fewer than four valid quarters")
    assert metrics["ttm_ocf"].value == unavailable
    assert metrics["ttm_capex"].value == unavailable
    assert metrics["ttm_fcf"].value == unavailable
    assert metrics["ttm_ocf"].value != Decimal("12")
    assert metrics["ttm_fcf"].value != Decimal("16")


def test_four_balance_share_counts_survive_fetch_to_record():
    reports = [
        {"fiscalDateEnding": "2026-06-30", "commonStockSharesOutstanding": "100"},
        {"fiscalDateEnding": "2026-03-31", "commonStockSharesOutstanding": "95"},
        {"fiscalDateEnding": "2025-12-31", "commonStockSharesOutstanding": "92"},
        {"fiscalDateEnding": "2025-09-30", "commonStockSharesOutstanding": "90"},
        {"fiscalDateEnding": "2025-06-30", "commonStockSharesOutstanding": "80"},
    ]
    balance = AlphaVantageResearchProvider(
        api_key="key",
        transport=lambda _: _balance(quarterlyReports=reports),
        sleep=lambda _: None,
    ).fetch_balance_sheet(_security(), as_of=AS_OF)
    record = provider_fundamental_record_from_normalized(_security(), ProviderEndpoint.BALANCE_SHEET, balance, AS_OF)

    shares = _period_values(record.facts, "shares_outstanding")
    assert shares == (Decimal("100"), Decimal("95"), Decimal("92"), Decimal("90"))
    assert ("period_4_shares_outstanding", "80") not in record.facts
    metrics = {metric.metric_id: metric for metric in derive_fundamental_metrics(
        FundamentalMetricInputs(latest_shares=shares[0], shares_4q_ago=shares[3])
    )}
    assert metrics["share_count_change"].value == Decimal("10")


_STATEMENT_LIKE = (
    ProviderEndpoint.INCOME_STATEMENT,
    ProviderEndpoint.BALANCE_SHEET,
    ProviderEndpoint.CASH_FLOW,
    ProviderEndpoint.EARNINGS,
)
