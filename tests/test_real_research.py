from datetime import date, datetime, timezone
from dataclasses import asdict
from uuid import uuid4

import pytest

from agentic_portfolio_lab.application.build_research import BuildResearchService
from agentic_portfolio_lab.application.market_configuration import RESEARCH_CANDIDATE_UNIVERSE
from agentic_portfolio_lab.domain.research_provider import ResearchProviderConfigurationError, ResearchProviderError
from agentic_portfolio_lab.infrastructure.alpha_vantage import AlphaVantageResearchProvider
from agentic_portfolio_lab.api.app import create_app
from fastapi.testclient import TestClient
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore, SQLiteResearchBatchState


def _overview(**extra):
    return {"Symbol":"MSFT","Name":"Microsoft","Exchange":"NASDAQ","Currency":"USD","AssetType":"Common Stock","Sector":"Technology","Industry":"Software","LatestQuarter":"2026-06-30","Description":"Provider description","MarketCapitalization":"100","PERatio":"20", **extra}
def _income(**extra): return {"symbol":"MSFT","quarterlyReports":[{"fiscalDateEnding":"2026-06-30","totalRevenue":"10","netIncome":"2"}], **extra}
def _earnings(**extra): return {"symbol":"MSFT","quarterlyEarnings":[{"reportedDate":"2026-07-30","reportedEPS":"1","estimatedEPS":"0.9","surprise":"0.1"}], **extra}


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


class Provider:
    def get_company_research(self, security):
        payloads = iter((_overview(Symbol=security.ticker, Name=security.ticker, Exchange=security.exchange), _income(symbol=security.ticker), _earnings(symbol=security.ticker)))
        return AlphaVantageResearchProvider(api_key="key", transport=lambda _: next(payloads), sleep=lambda _: None).get_company_research(security)
class State:
    def __init__(self): self.batches=[]
    def append_research_batch(self, batch): self.batches.append(batch)


def test_build_creates_one_persistable_batch_and_one_future_manager_cycle():
    state = State(); instant = datetime(2026,8,13,20,0,tzinfo=timezone.utc)
    result = BuildResearchService(provider=Provider(), state=state, candidate_universe=RESEARCH_CANDIDATE_UNIVERSE, now=lambda: instant).build(portfolio_id=uuid4())
    assert len(result.batch.packets) == len(RESEARCH_CANDIDATE_UNIVERSE) == 5
    assert state.batches == [result.batch]
    assert result.batch.manager_type == "VALUE"
    assert all(any(section.section_id == "RISKS_AND_LIMITATIONS" for section in packet.sections) for packet in result.batch.packets)
    assert len({item.evidence_id for packet in result.batch.packets for item in packet.evidence_items}) == 15


def test_build_research_command_returns_batch_metadata_without_live_provider_call():
    state = State(); instant = datetime(2026,8,13,20,0,tzinfo=timezone.utc)
    service = BuildResearchService(provider=Provider(), state=state, candidate_universe=RESEARCH_CANDIDATE_UNIVERSE, now=lambda: instant)
    response = TestClient(create_app(research_service=service)).post("/commands/build-research")
    assert response.status_code == 200
    assert response.json()["packet_count"] == 5
    assert response.json()["source_provider_identity"] == "alpha-vantage"
    assert len(state.batches) == 1


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


def test_valid_partial_fields_become_explicit_missing_data_sections():
    state = State(); instant = datetime(2026,8,13,20,0,tzinfo=timezone.utc)
    class Partial(Provider):
        def get_company_research(self, security):
            payloads=iter((_overview(Symbol=security.ticker, Name=security.ticker, Exchange=security.exchange), _income(symbol=security.ticker), _earnings(symbol=security.ticker)))
            return AlphaVantageResearchProvider(api_key="key", transport=lambda _: next(payloads), sleep=lambda _: None).get_company_research(security)
    packet=BuildResearchService(provider=Partial(), state=state, candidate_universe=(RESEARCH_CANDIDATE_UNIVERSE[0],), now=lambda:instant).build(portfolio_id=uuid4()).batch.packets[0]
    assert any(section.section_id == "VALUATION_PEG_RATIO_MISSING" for section in packet.sections)
    assert "market_cap: 100" in next(section.content for section in packet.sections if section.section_id == "VALUATION")


@pytest.mark.parametrize("payload_factory, missing_section", [
    (lambda security: (_overview(Symbol=security.ticker, Exchange=security.exchange, PERatio="N/A"), _income(symbol=security.ticker), _earnings(symbol=security.ticker)), "VALUATION_PE_RATIO_MISSING"),
    (lambda security: (_overview(Symbol=security.ticker, Exchange=security.exchange), _income(symbol=security.ticker, quarterlyReports=[{"fiscalDateEnding":"2026-06-30", "totalRevenue":"N/A"}]), _earnings(symbol=security.ticker)), "FINANCIALS_TOTAL_REVENUE_MISSING"),
    (lambda security: (_overview(Symbol=security.ticker, Exchange=security.exchange), _income(symbol=security.ticker), _earnings(symbol=security.ticker, quarterlyEarnings=[{"reportedDate":"2026-07-30", "reportedEPS":"N/A"}])), "EARNINGS_REPORTED_EPS_MISSING"),
])
def test_na_is_not_evidence_and_becomes_explicit_missing_data(payload_factory, missing_section):
    security = RESEARCH_CANDIDATE_UNIVERSE[0]; sequence = iter(payload_factory(security))
    provider = AlphaVantageResearchProvider(api_key="key", transport=lambda _: next(sequence), sleep=lambda _: None)
    class One: 
        def get_company_research(self, _): return provider.get_company_research(security)
    packet = BuildResearchService(provider=One(), state=State(), candidate_universe=(security,), now=lambda: datetime(2026,8,13,20,tzinfo=timezone.utc)).build(portfolio_id=uuid4()).batch.packets[0]
    assert any(section.section_id == missing_section for section in packet.sections)
    assert "N/A" not in " ".join(item.claim_supported for item in packet.evidence_items)


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


def test_all_missing_valid_income_and_earnings_succeed_with_missing_data():
    security=RESEARCH_CANDIDATE_UNIVERSE[0]
    sequence=iter((_overview(), _income(symbol=security.ticker, quarterlyReports=[{"fiscalDateEnding":"2026-06-30"}]), _earnings(symbol=security.ticker, quarterlyEarnings=[{"reportedDate":"2026-07-30"}])))
    provider=AlphaVantageResearchProvider(api_key="key", transport=lambda _:next(sequence), sleep=lambda _:None)
    class One: 
        def get_company_research(self, _): return provider.get_company_research(security)
    packet=BuildResearchService(provider=One(), state=State(), candidate_universe=(security,), now=lambda:datetime(2026,8,13,20,tzinfo=timezone.utc)).build(portfolio_id=uuid4()).batch.packets[0]
    assert any(section.section_id == "FINANCIALS_TOTAL_REVENUE_MISSING" for section in packet.sections)
    assert any(section.section_id == "EARNINGS_REPORTED_EPS_MISSING" for section in packet.sections)


def test_authoritative_research_output_uses_no_raw_alpha_vantage_keys():
    security = RESEARCH_CANDIDATE_UNIVERSE[0]
    sequence = iter((_overview(), _income(), _earnings()))
    document = AlphaVantageResearchProvider(api_key="key", transport=lambda _: next(sequence), sleep=lambda _: None).get_company_research(security)
    class One:
        def get_company_research(self, _): return document
    packet = BuildResearchService(provider=One(), state=State(), candidate_universe=(security,), now=lambda: datetime(2026,8,13,20,tzinfo=timezone.utc)).build(portfolio_id=uuid4()).batch.packets[0]
    forbidden = ("Symbol", "AssetType", "MarketCapitalization", "PERatio", "fiscalDateEnding", "totalRevenue", "reportedEPS")
    assert all(key not in repr(asdict(document)) for key in forbidden)
    assert all(key not in " ".join(str(section.content) for section in packet.sections) for key in forbidden)
    assert all(key not in " ".join(item.claim_supported for item in packet.evidence_items) for key in forbidden)


@pytest.mark.parametrize("field, section", [
    ("price_to_book_ratio", "VALUATION"), ("beta", "RISKS_AND_LIMITATIONS"),
    ("dividend_yield", "RISKS_AND_LIMITATIONS"), ("eps", "VALUATION"),
    ("revenue_per_share", "VALUATION"), ("profit_margin", "VALUATION"),
    ("operating_margin", "VALUATION"), ("return_on_equity", "VALUATION"),
])
def test_restored_overview_fields_are_present_or_explicitly_missing(field, section):
    security = RESEARCH_CANDIDATE_UNIVERSE[0]
    raw_field = {"price_to_book_ratio":"PriceToBookRatio", "beta":"Beta", "dividend_yield":"DividendYield", "eps":"EPS", "revenue_per_share":"RevenuePerShareTTM", "profit_margin":"ProfitMargin", "operating_margin":"OperatingMarginTTM", "return_on_equity":"ReturnOnEquityTTM"}[field]
    def packet_for(overview):
        sequence = iter((overview, _income(), _earnings()))
        provider = AlphaVantageResearchProvider(api_key="key", transport=lambda _: next(sequence), sleep=lambda _: None)
        class One:
            def get_company_research(self, _): return provider.get_company_research(security)
        return BuildResearchService(provider=One(), state=State(), candidate_universe=(security,), now=lambda: datetime(2026,8,13,20,tzinfo=timezone.utc)).build(portfolio_id=uuid4()).batch.packets[0]
    present = packet_for(_overview(**{raw_field: "1.23"}))
    assert f"{field}: 1.23" in next(item.content for item in present.sections if item.section_id == section)
    assert not any(item.section_id == f"{section}_{field.upper()}_MISSING" for item in present.sections)
    missing = packet_for(_overview())
    missing_section = next(item for item in missing.sections if item.section_id == f"{section}_{field.upper()}_MISSING")
    assert missing_section.content.reason.value == "NOT_AVAILABLE"


def test_final_candidate_failure_preserves_prior_durable_batch_and_api_latest(tmp_path):
    path=tmp_path/"research.sqlite"; store=SQLiteLocalRunStore(path); initial=store.initialize_run(initialized_at=datetime(2026,8,13,14,tzinfo=timezone.utc))
    fixed=lambda:datetime(2026,8,13,20,tzinfo=timezone.utc)
    prior=BuildResearchService(provider=Provider(), state=SQLiteResearchBatchState(store), candidate_universe=RESEARCH_CANDIDATE_UNIVERSE, now=fixed).build(portfolio_id=initial.managed_portfolio.portfolio_id).batch
    class FinalFailure(Provider):
        def __init__(self): self.calls=[]
        def get_company_research(self, security):
            self.calls.append(security.ticker)
            if len(self.calls)==5: raise ResearchProviderError("final candidate failed")
            return super().get_company_research(security)
    failing=FinalFailure()
    with pytest.raises(ResearchProviderError): BuildResearchService(provider=failing,state=SQLiteResearchBatchState(store),candidate_universe=RESEARCH_CANDIDATE_UNIVERSE,now=fixed).build(portfolio_id=initial.managed_portfolio.portfolio_id)
    assert failing.calls == [security.ticker for security in RESEARCH_CANDIDATE_UNIVERSE]
    reopened=SQLiteLocalRunStore(path).open_run(); assert reopened is not None and reopened.research_batches == (prior,)
    assert TestClient(create_app(database_path=str(path))).get("/research/latest").json()["batch_id"] == prior.batch_id


def test_malformed_earnings_does_not_replace_prior_durable_batch(tmp_path):
    path=tmp_path/"research.sqlite"; store=SQLiteLocalRunStore(path); initial=store.initialize_run(initialized_at=datetime(2026,8,13,14,tzinfo=timezone.utc))
    fixed=lambda:datetime(2026,8,13,20,tzinfo=timezone.utc)
    prior=BuildResearchService(provider=Provider(), state=SQLiteResearchBatchState(store), candidate_universe=RESEARCH_CANDIDATE_UNIVERSE, now=fixed).build(portfolio_id=initial.managed_portfolio.portfolio_id).batch
    sequence=iter((_overview(), _income(), {"symbol":"MSFT", "quarterlyEarnings": []}))
    malformed=AlphaVantageResearchProvider(api_key="key", transport=lambda _:next(sequence), sleep=lambda _:None)
    with pytest.raises(ResearchProviderError, match="EARNINGS lacks quarterly earnings"):
        BuildResearchService(provider=malformed, state=SQLiteResearchBatchState(store), candidate_universe=(RESEARCH_CANDIDATE_UNIVERSE[0],), now=fixed).build(portfolio_id=initial.managed_portfolio.portfolio_id)
    reopened=SQLiteLocalRunStore(path).open_run()
    assert reopened is not None and reopened.research_batches == (prior,)
    assert TestClient(create_app(database_path=str(path))).get("/research/latest").json()["batch_id"] == prior.batch_id


def test_research_sqlite_round_trip_preserves_identity_evidence_dates_and_missing_data(tmp_path):
    path=tmp_path/"research.sqlite"; store=SQLiteLocalRunStore(path); initial=store.initialize_run(initialized_at=datetime(2026,8,13,14,tzinfo=timezone.utc))
    result=BuildResearchService(provider=Provider(),state=SQLiteResearchBatchState(store),candidate_universe=RESEARCH_CANDIDATE_UNIVERSE,now=lambda:datetime(2026,8,13,20,tzinfo=timezone.utc)).build(portfolio_id=initial.managed_portfolio.portfolio_id)
    body=TestClient(create_app(database_path=str(path))).get("/research/latest").json()
    assert body["batch_id"] == result.batch.batch_id and body["decision_cycle_id"] == str(result.batch.decision_cycle_id)
    assert body["batch_id"] != body["decision_cycle_id"] and len(body["packets"]) == 5
    ids=[item["evidence_id"] for packet in body["packets"] for item in packet["evidence"]]
    assert len(ids) == len(set(ids)) == 15
    assert {item["source_date"] for packet in body["packets"] for item in packet["evidence"]} == {"2026-06-30", "2026-07-30"}
    assert {(packet["ticker"], packet["security_type"], packet["exchange"], packet["currency"]) for packet in body["packets"]} == {(security.ticker, security.security_type, security.exchange, security.currency) for security in RESEARCH_CANDIDATE_UNIVERSE}
    expected_missing = {
        (packet.ticker, section.section_id): (section.content.reason.value, section.content.details)
        for packet in result.batch.packets for section in packet.sections
        if not isinstance(section.content, str)
    }
    actual_missing = {
        (packet["ticker"], section["section_id"]): (section["missing_data"]["reason"], section["missing_data"]["details"])
        for packet in body["packets"] for section in packet["sections"]
        if section["missing_data"] is not None
    }
    assert actual_missing == expected_missing
