from datetime import date, datetime, timezone
from dataclasses import asdict

import pytest

from agentic_portfolio_lab.application.market_configuration import RESEARCH_CANDIDATE_UNIVERSE
from agentic_portfolio_lab.domain.research_provider import ResearchProviderConfigurationError, ResearchProviderError
from agentic_portfolio_lab.infrastructure.alpha_vantage import AlphaVantageResearchProvider


def _overview(**extra):
    return {"Symbol":"MSFT","Name":"Microsoft","Exchange":"NASDAQ","Currency":"USD","AssetType":"Common Stock","Sector":"Technology","Industry":"Software","LatestQuarter":"2026-06-30","Description":"Provider description","MarketCapitalization":"100","PERatio":"20", **extra}
def _income(**extra): return {"symbol":"MSFT","quarterlyReports":[{"fiscalDateEnding":"2026-06-30","totalRevenue":"10","netIncome":"2"}], **extra}
def _earnings(**extra): return {"symbol":"MSFT","quarterlyEarnings":[{"reportedDate":"2026-07-30","reportedEPS":"1","estimatedEPS":"0.9","surprise":"0.1"}], **extra}
def _balance(**extra):
    return {"symbol":"MSFT","quarterlyReports":[{"fiscalDateEnding":"2026-06-30","reportedCurrency":"USD","cashAndCashEquivalentsAtCarryingValue":"80","shortLongTermDebtTotal":"25","totalCurrentAssets":"120","totalCurrentLiabilities":"40","commonStockSharesOutstanding":"1000"}], **extra}
def _cash_flow(**extra):
    return {"symbol":"MSFT","quarterlyReports":[{"fiscalDateEnding":"2026-06-30","reportedCurrency":"USD","operatingCashflow":"30","capitalExpenditures":"-5","paymentsForRepurchaseOfCommonStock":"1","proceedsFromIssuanceOfCommonStock":"0"}], **extra}


def test_alpha_vantage_normalizes_only_approved_documents_and_paces_calls():
    payloads = iter((_overview(), _income(), _earnings()))
    slept = []
    provider = AlphaVantageResearchProvider(api_key="key", transport=lambda _: next(payloads), sleep=slept.append)
    document = provider.get_company_research(RESEARCH_CANDIDATE_UNIVERSE[0])
    assert document.overview.company_name == "Microsoft"
    assert document.overview.source.source_date == date(2026, 6, 30)
    assert document.income_statement.source.source_date == date(2026, 6, 30)
    assert document.earnings.source.source_date == date(2026, 7, 30)
    assert slept == [12, 12]


@pytest.mark.parametrize("payloads", [(_overview(Symbol="AAPL"), _income(), _earnings()), ({"Information":"rate limit"}, _income(), _earnings()), (_overview(), {"quarterlyReports":[]}, _earnings())])
def test_invalid_identity_or_provider_failure_is_not_missing_data(payloads):
    sequence = iter(payloads)
    provider = AlphaVantageResearchProvider(api_key="key", transport=lambda _: next(sequence), sleep=lambda _: None)
    with pytest.raises(ResearchProviderError): provider.get_company_research(RESEARCH_CANDIDATE_UNIVERSE[0])


def test_missing_key_is_clear(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    with pytest.raises(ResearchProviderConfigurationError): AlphaVantageResearchProvider(transport=lambda _: _overview()).get_company_research(RESEARCH_CANDIDATE_UNIVERSE[0])


def test_full_configured_stream_has_fifteen_ordered_calls_and_fourteen_intervals():
    calls, sleeps = [], []
    def transport(url):
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse(url).query); function, symbol = query["function"][0], query["symbol"][0]
        calls.append((function, symbol))
        if function == "OVERVIEW": return _overview(Symbol=symbol, Name=symbol, Exchange=next(security.exchange for security in RESEARCH_CANDIDATE_UNIVERSE if security.ticker == symbol))
        if function == "INCOME_STATEMENT": return _income(symbol=symbol)
        return _earnings(symbol=symbol)
    provider = AlphaVantageResearchProvider(api_key="key", transport=transport, sleep=sleeps.append)
    for security in RESEARCH_CANDIDATE_UNIVERSE: provider.get_company_research(security)
    assert len(calls) == 15
    assert [function for function, _ in calls] == ["OVERVIEW", "INCOME_STATEMENT", "EARNINGS"] * 5
    assert [symbol for _, symbol in calls] == [security.ticker for security in RESEARCH_CANDIDATE_UNIVERSE for _ in range(3)]
    assert sleeps == [12] * 14


@pytest.mark.parametrize("field,value", [("Exchange","NYSE"), ("Currency","CAD"), ("AssetType","ETF")])
def test_overview_identity_mismatches_fail(field, value):
    sequence=iter((_overview(**{field:value}), _income(), _earnings()))
    with pytest.raises(ResearchProviderError): AlphaVantageResearchProvider(api_key="key", transport=lambda _:next(sequence), sleep=lambda _:None).get_company_research(RESEARCH_CANDIDATE_UNIVERSE[0])


def test_income_statement_symbol_mismatch_fails_from_income_validation():
    sequence=iter((_overview(), _income(symbol="AAPL"), _earnings()))
    with pytest.raises(ResearchProviderError, match="INCOME_STATEMENT symbol"):
        AlphaVantageResearchProvider(api_key="key", transport=lambda _:next(sequence), sleep=lambda _:None).get_company_research(RESEARCH_CANDIDATE_UNIVERSE[0])


def test_earnings_symbol_mismatch_fails_from_earnings_validation():
    sequence=iter((_overview(), _income(), _earnings(symbol="AAPL")))
    with pytest.raises(ResearchProviderError, match="EARNINGS symbol"):
        AlphaVantageResearchProvider(api_key="key", transport=lambda _:next(sequence), sleep=lambda _:None).get_company_research(RESEARCH_CANDIDATE_UNIVERSE[0])


def test_authoritative_research_output_uses_no_raw_alpha_vantage_keys():
    security = RESEARCH_CANDIDATE_UNIVERSE[0]
    sequence = iter((_overview(), _income(), _earnings()))
    document = AlphaVantageResearchProvider(api_key="key", transport=lambda _: next(sequence), sleep=lambda _: None).get_company_research(security)
    forbidden = ("Symbol", "AssetType", "MarketCapitalization", "PERatio", "fiscalDateEnding", "totalRevenue", "reportedEPS")
    assert all(key not in repr(asdict(document)) for key in forbidden)


def _v2_provider(payloads, slept=None):
    sequence = iter(payloads)
    return AlphaVantageResearchProvider(api_key="key", transport=lambda _: next(sequence), sleep=(slept.append if slept is not None else (lambda _: None)))


def test_v2_overview_maps_extra_optional_fields_and_omits_na():
    security = RESEARCH_CANDIDATE_UNIVERSE[0]
    overview = AlphaVantageResearchProvider(
        api_key="key",
        transport=lambda _: _overview(SharesOutstanding="50", PriceToSalesRatioTTM="N/A"),
        sleep=lambda _: None,
    ).fetch_overview(security)
    assert overview.shares_outstanding == "50"
    assert overview.price_to_sales is None
    assert ("shares_outstanding", "50") in overview.source.facts
    assert all(key != "price_to_sales" for key, _ in overview.source.facts)
    assert "N/A" not in " ".join(value for _, value in overview.source.facts)


def test_v2_balance_sheet_maps_latest_quarter_and_cash_fallback():
    security = RESEARCH_CANDIDATE_UNIVERSE[0]
    primary = _v2_provider((_balance(),)).fetch_balance_sheet(security)
    assert primary.cash == "80"
    assert primary.cash_field == "cashAndCashEquivalentsAtCarryingValue"
    assert primary.debt == "25"
    assert primary.current_assets == "120"
    assert primary.current_liabilities == "40"
    assert primary.shares_outstanding == "1000"
    assert primary.fiscal_date_ending == "2026-06-30"
    assert primary.reported_currency == "USD"
    assert len(primary.periods) == 1
    assert primary.periods[0].periods == ()
    assert ("cash_field", "cashAndCashEquivalentsAtCarryingValue") in primary.source.facts
    preferred = _v2_provider((
        _balance(quarterlyReports=[{
            "fiscalDateEnding": "2026-06-30",
            "reportedCurrency": "USD",
            "cashAndCashEquivalentsAtCarryingValue": "N/A",
            "cashAndShortTermInvestments": "70",
            "totalCurrentAssets": "120",
            "totalCurrentLiabilities": "40",
            "commonStockSharesOutstanding": "1000",
        }]),
    )).fetch_balance_sheet(security)
    assert preferred.cash == "70"
    assert preferred.cash_field == "cashAndShortTermInvestments"
    assert preferred.debt is None
    assert ("cash_field", "cashAndShortTermInvestments") in preferred.source.facts
    assert "N/A" not in " ".join(value for _, value in preferred.source.facts)


def test_v2_cash_flow_maps_latest_quarter():
    cash_flow = _v2_provider((_cash_flow(),)).fetch_cash_flow(RESEARCH_CANDIDATE_UNIVERSE[0])
    assert cash_flow.operating_cash_flow == "30"
    assert cash_flow.capex == "-5"
    assert cash_flow.buybacks == "1"
    assert cash_flow.issuance == "0"
    assert cash_flow.fiscal_date_ending == "2026-06-30"
    assert len(cash_flow.periods) == 1
    assert cash_flow.periods[0].periods == ()


def test_v2_income_captures_four_quarters_and_filters_look_ahead():
    security = RESEARCH_CANDIDATE_UNIVERSE[0]
    reports = [
        {"fiscalDateEnding": "2026-09-30", "totalRevenue": "future"},
        {"fiscalDateEnding": "2026-06-30", "totalRevenue": "10", "grossProfit": "4", "operatingIncome": "3", "netIncome": "2"},
        {"fiscalDateEnding": "2026-03-31", "totalRevenue": "9"},
        {"fiscalDateEnding": "2025-12-31", "totalRevenue": "8"},
        {"fiscalDateEnding": "2025-09-30", "totalRevenue": "7"},
        {"fiscalDateEnding": "2025-06-30", "totalRevenue": "too-old"},
    ]
    as_of = datetime(2026, 8, 13, 20, tzinfo=timezone.utc)
    income = _v2_provider((_income(quarterlyReports=reports),)).fetch_income_statement(security, as_of=as_of)
    assert income.total_revenue == "10"
    assert income.fiscal_date_ending == "2026-06-30"
    assert len(income.periods) == 4
    assert [period.fiscal_date_ending for period in income.periods] == ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"]
    assert income.periods[0].periods == ()
    unfiltered = _v2_provider((_income(quarterlyReports=reports),)).fetch_income_statement(security)
    assert unfiltered.fiscal_date_ending == "2026-09-30"
    assert len(unfiltered.periods) == 4


def test_v2_cash_flow_captures_four_quarters_and_filters_look_ahead():
    security = RESEARCH_CANDIDATE_UNIVERSE[0]
    reports = [
        {"fiscalDateEnding": "2026-09-30", "operatingCashflow": "future", "capitalExpenditures": "-9"},
        {"fiscalDateEnding": "2026-06-30", "operatingCashflow": "30", "capitalExpenditures": "-5"},
        {"fiscalDateEnding": "2026-03-31", "operatingCashflow": "20", "capitalExpenditures": "-4"},
        {"fiscalDateEnding": "2025-12-31", "operatingCashflow": "15", "capitalExpenditures": "-3"},
        {"fiscalDateEnding": "2025-09-30", "operatingCashflow": "10", "capitalExpenditures": "-2"},
        {"fiscalDateEnding": "2025-06-30", "operatingCashflow": "too-old", "capitalExpenditures": "-1"},
    ]
    as_of = datetime(2026, 8, 13, 20, tzinfo=timezone.utc)
    cash_flow = _v2_provider((_cash_flow(quarterlyReports=reports),)).fetch_cash_flow(security, as_of=as_of)
    assert cash_flow.operating_cash_flow == "30"
    assert cash_flow.capex == "-5"
    assert cash_flow.fiscal_date_ending == "2026-06-30"
    assert len(cash_flow.periods) == 4
    assert [period.fiscal_date_ending for period in cash_flow.periods] == ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"]
    assert [period.operating_cash_flow for period in cash_flow.periods] == ["30", "20", "15", "10"]
    assert [period.capex for period in cash_flow.periods] == ["-5", "-4", "-3", "-2"]
    assert cash_flow.periods[0].periods == ()
    unfiltered = _v2_provider((_cash_flow(quarterlyReports=reports),)).fetch_cash_flow(security)
    assert unfiltered.fiscal_date_ending == "2026-09-30"
    assert len(unfiltered.periods) == 4


def test_v2_balance_sheet_captures_four_quarters_and_filters_look_ahead():
    security = RESEARCH_CANDIDATE_UNIVERSE[0]
    reports = [
        {"fiscalDateEnding": "2026-09-30", "commonStockSharesOutstanding": "future"},
        {"fiscalDateEnding": "2026-06-30", "commonStockSharesOutstanding": "1000", "cashAndCashEquivalentsAtCarryingValue": "80"},
        {"fiscalDateEnding": "2026-03-31", "commonStockSharesOutstanding": "980"},
        {"fiscalDateEnding": "2025-12-31", "commonStockSharesOutstanding": "960"},
        {"fiscalDateEnding": "2025-09-30", "commonStockSharesOutstanding": "940"},
        {"fiscalDateEnding": "2025-06-30", "commonStockSharesOutstanding": "too-old"},
    ]
    as_of = datetime(2026, 8, 13, 20, tzinfo=timezone.utc)
    balance = _v2_provider((_balance(quarterlyReports=reports),)).fetch_balance_sheet(security, as_of=as_of)
    assert balance.shares_outstanding == "1000"
    assert balance.cash == "80"
    assert balance.fiscal_date_ending == "2026-06-30"
    assert len(balance.periods) == 4
    assert [period.fiscal_date_ending for period in balance.periods] == ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"]
    assert [period.shares_outstanding for period in balance.periods] == ["1000", "980", "960", "940"]
    assert balance.periods[0].periods == ()
    unfiltered = _v2_provider((_balance(quarterlyReports=reports),)).fetch_balance_sheet(security)
    assert unfiltered.fiscal_date_ending == "2026-09-30"
    assert len(unfiltered.periods) == 4


def test_v2_statement_symbol_mismatch_fails():
    with pytest.raises(ResearchProviderError, match="BALANCE_SHEET symbol"):
        _v2_provider((_balance(symbol="AAPL"),)).fetch_balance_sheet(RESEARCH_CANDIDATE_UNIVERSE[0])
    with pytest.raises(ResearchProviderError, match="CASH_FLOW symbol"):
        _v2_provider((_cash_flow(symbol="AAPL"),)).fetch_cash_flow(RESEARCH_CANDIDATE_UNIVERSE[0])


def test_v2_uncached_five_endpoint_path_has_twenty_five_ordered_calls():
    calls, sleeps = [], []
    def transport(url):
        from urllib.parse import parse_qs, urlparse
        query = parse_qs(urlparse(url).query)
        function, symbol = query["function"][0], query["symbol"][0]
        calls.append((function, symbol))
        if function == "OVERVIEW":
            return _overview(Symbol=symbol, Name=symbol, Exchange=next(security.exchange for security in RESEARCH_CANDIDATE_UNIVERSE if security.ticker == symbol))
        if function == "INCOME_STATEMENT":
            return _income(symbol=symbol)
        if function == "BALANCE_SHEET":
            return _balance(symbol=symbol)
        if function == "CASH_FLOW":
            return _cash_flow(symbol=symbol)
        return _earnings(symbol=symbol)
    provider = AlphaVantageResearchProvider(api_key="key", transport=transport, sleep=sleeps.append)
    for security in RESEARCH_CANDIDATE_UNIVERSE:
        provider.fetch_overview(security)
        provider.fetch_income_statement(security)
        provider.fetch_balance_sheet(security)
        provider.fetch_cash_flow(security)
        provider.fetch_earnings(security)
    assert len(calls) == 25
    assert [function for function, _ in calls] == ["OVERVIEW", "INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW", "EARNINGS"] * 5
    assert sleeps == [12] * 24


def test_get_company_research_still_leaves_income_periods_empty():
    document = _v2_provider((_overview(), _income(), _earnings())).get_company_research(RESEARCH_CANDIDATE_UNIVERSE[0])
    assert document.income_statement.periods == ()
    assert document.balance_sheet is None
    assert document.cash_flow is None
