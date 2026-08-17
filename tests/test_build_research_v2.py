"""Research v2 weekly assembly: screen → refresh selected → persist one cycle."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agentic_portfolio_lab.api.app import create_app
from agentic_portfolio_lab.application.build_research import BuildResearchService, ResearchCycleInputs
from agentic_portfolio_lab.application.fundamental_inputs import fundamental_metric_inputs_from_records
from agentic_portfolio_lab.application.fundamental_metrics import derive_fundamental_metrics
from agentic_portfolio_lab.application.market_configuration import VALUE_US_EQUITIES_V1
from agentic_portfolio_lab.domain.openai_value_manager import _serialize_context, _serialize_packet
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio
from agentic_portfolio_lab.domain.provider_fundamentals import (
    ProviderEndpoint,
    ProviderFundamentalRecord,
    ReuseStatus,
)
from agentic_portfolio_lab.domain.research import MissingData, MissingDataReason, PacketFundamentals
from agentic_portfolio_lab.domain.research_provider import ResearchProviderError
from agentic_portfolio_lab.domain.screening import ResearchSlotRole
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.domain.value_manager import ValueManagerDecisionContext
from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.infrastructure.alpha_vantage import AlphaVantageResearchProvider
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore, SQLiteResearchBatchState

UTC = timezone.utc
AS_OF = datetime(2026, 8, 17, 16, tzinfo=UTC)
CACHED_AT = datetime(2026, 7, 1, 12, tzinfo=UTC)
PERIOD = date(2026, 6, 30)
LATER = datetime(2026, 10, 21, tzinfo=UTC)


def _price(security, amount="100", *, observed_at=AS_OF) -> PriceObservation:
    return PriceObservation(
        security=security,
        observed_price=Decimal(amount),
        market_date=observed_at.date(),
        observed_at=observed_at,
        currency="USD",
        source_provider_identity="twelve-data",
        price_convention="fake-source-price",
    )


def _overview_payload(security, **extra):
    return {
        "Symbol": security.ticker,
        "Name": security.ticker,
        "Exchange": security.exchange,
        "Currency": "USD",
        "AssetType": "Common Stock",
        "Sector": "Technology",
        "Industry": "Software",
        "LatestQuarter": "2026-06-30",
        "Description": "Provider description",
        "52WeekHigh": "200",
        "PERatio": "20",
        "SharesOutstanding": "50",
        **extra,
    }


def _income_payload(security, **extra):
    reports = extra.pop(
        "quarterlyReports",
        [
            {"fiscalDateEnding": "2026-06-30", "reportedCurrency": "USD", "totalRevenue": "10", "grossProfit": "4", "operatingIncome": "3", "netIncome": "2"},
            {"fiscalDateEnding": "2026-03-31", "reportedCurrency": "USD", "totalRevenue": "9", "grossProfit": "3", "operatingIncome": "2", "netIncome": "1"},
            {"fiscalDateEnding": "2025-12-31", "reportedCurrency": "USD", "totalRevenue": "8", "grossProfit": "3", "operatingIncome": "2", "netIncome": "1"},
            {"fiscalDateEnding": "2025-09-30", "reportedCurrency": "USD", "totalRevenue": "7", "grossProfit": "2", "operatingIncome": "1", "netIncome": "1"},
        ],
    )
    return {"symbol": security.ticker, "quarterlyReports": reports, **extra}


def _balance_payload(security, **extra):
    reports = extra.pop(
        "quarterlyReports",
        [
            {"fiscalDateEnding": "2026-06-30", "reportedCurrency": "USD", "cashAndCashEquivalentsAtCarryingValue": "80", "shortLongTermDebtTotal": "20", "totalCurrentAssets": "100", "totalCurrentLiabilities": "40", "commonStockSharesOutstanding": "50"},
            {"fiscalDateEnding": "2026-03-31", "reportedCurrency": "USD", "commonStockSharesOutstanding": "48"},
            {"fiscalDateEnding": "2025-12-31", "reportedCurrency": "USD", "commonStockSharesOutstanding": "46"},
            {"fiscalDateEnding": "2025-09-30", "reportedCurrency": "USD", "commonStockSharesOutstanding": "44"},
        ],
    )
    return {"symbol": security.ticker, "quarterlyReports": reports, **extra}


def _cash_flow_payload(security, **extra):
    reports = extra.pop(
        "quarterlyReports",
        [
            {"fiscalDateEnding": "2026-06-30", "operatingCashflow": "5", "capitalExpenditures": "-2"},
            {"fiscalDateEnding": "2026-03-31", "operatingCashflow": "4", "capitalExpenditures": "-1"},
            {"fiscalDateEnding": "2025-12-31", "operatingCashflow": "3", "capitalExpenditures": "-1"},
            {"fiscalDateEnding": "2025-09-30", "operatingCashflow": "2", "capitalExpenditures": "0"},
        ],
    )
    return {"symbol": security.ticker, "quarterlyReports": reports, **extra}


def _earnings_payload(security, **extra):
    reports = extra.pop(
        "quarterlyEarnings",
        [{"reportedDate": "2026-07-30", "fiscalDateEnding": "2026-06-30", "reportedEPS": "1", "estimatedEPS": "0.9", "surprise": "0.1"}],
    )
    return {"symbol": security.ticker, "quarterlyEarnings": reports, **extra}


def _cached_overview(
    security,
    *,
    record_id: str | None = None,
    fetched_at=CACHED_AT,
    fifty_two_week_high="200",
    pe_ratio="20",
) -> ProviderFundamentalRecord:
    return ProviderFundamentalRecord(
        record_id=record_id or f"cached-{security.ticker}-OVERVIEW",
        security=security,
        provider_identity="alpha-vantage",
        endpoint=ProviderEndpoint.OVERVIEW,
        fiscal_period=PERIOD,
        source_date=PERIOD,
        fetched_at=fetched_at,
        facts=(
            ("latest_quarter", "2026-06-30"),
            ("fifty_two_week_high", fifty_two_week_high),
            ("pe_ratio", pe_ratio),
            ("company_name", security.ticker),
        ),
    )


def _cached_statement(
    security,
    endpoint: ProviderEndpoint,
    *,
    fiscal_period=PERIOD,
    fetched_at=CACHED_AT,
    facts: tuple[tuple[str, str], ...] | None = None,
) -> ProviderFundamentalRecord:
    return ProviderFundamentalRecord(
        record_id=f"cached-{security.ticker}-{endpoint.value}",
        security=security,
        provider_identity="alpha-vantage",
        endpoint=endpoint,
        fiscal_period=fiscal_period,
        source_date=fiscal_period,
        fetched_at=fetched_at,
        facts=facts or (("marker", endpoint.value),),
    )


def _cached_statements(security, **overrides: ProviderFundamentalRecord) -> tuple[ProviderFundamentalRecord, ...]:
    records = {
        ProviderEndpoint.INCOME_STATEMENT: _cached_statement(security, ProviderEndpoint.INCOME_STATEMENT),
        ProviderEndpoint.BALANCE_SHEET: _cached_statement(security, ProviderEndpoint.BALANCE_SHEET),
        ProviderEndpoint.CASH_FLOW: _cached_statement(security, ProviderEndpoint.CASH_FLOW),
        ProviderEndpoint.EARNINGS: _cached_statement(security, ProviderEndpoint.EARNINGS),
    }
    records.update(overrides)
    return tuple(records.values())


@dataclass
class FakeCycleState:
    price_observations: tuple[PriceObservation, ...] = ()
    fundamental_records: tuple[ProviderFundamentalRecord, ...] = ()
    screening_runs: list = field(default_factory=list)
    fetched_records: list = field(default_factory=list)
    batches: list = field(default_factory=list)

    def load_research_inputs(self) -> ResearchCycleInputs:
        return ResearchCycleInputs(self.price_observations, self.fundamental_records)

    def persist_research_cycle(self, *, screening_run, fetched_records, batch) -> None:
        self.screening_runs.append(screening_run)
        fetched = tuple(fetched_records)
        self.fetched_records.append(fetched)
        self.fundamental_records = (*self.fundamental_records, *fetched)
        self.batches.append(batch)


def _recording_provider(calls: list[tuple[str, str]], *, overview_extra=None, statement_date="2026-06-30"):
    overview_extra = overview_extra or {}

    def transport(url: str):
        query = parse_qs(urlparse(url).query)
        function, symbol = query["function"][0], query["symbol"][0]
        calls.append((function, symbol))
        security = next(item for item in VALUE_US_EQUITIES_V1.identities if item.ticker == symbol)
        if function == "OVERVIEW":
            return _overview_payload(security, **overview_extra)
        if function == "INCOME_STATEMENT":
            if statement_date != "2026-06-30":
                return _income_payload(security, quarterlyReports=[{"fiscalDateEnding": statement_date, "totalRevenue": "12"}])
            return _income_payload(security)
        if function == "BALANCE_SHEET":
            if statement_date != "2026-06-30":
                return _balance_payload(security, quarterlyReports=[{"fiscalDateEnding": statement_date, "cashAndCashEquivalentsAtCarryingValue": "90"}])
            return _balance_payload(security)
        if function == "CASH_FLOW":
            if statement_date != "2026-06-30":
                return _cash_flow_payload(security, quarterlyReports=[{"fiscalDateEnding": statement_date, "operatingCashflow": "31"}])
            return _cash_flow_payload(security)
        if statement_date != "2026-06-30":
            return _earnings_payload(security, quarterlyEarnings=[{"reportedDate": "2026-10-20", "fiscalDateEnding": statement_date, "reportedEPS": "1.1"}])
        return _earnings_payload(security)

    return AlphaVantageResearchProvider(api_key="key", transport=transport, sleep=lambda _: None)


def _service(state: FakeCycleState, calls: list[tuple[str, str]], *, now=None, **provider_kwargs) -> BuildResearchService:
    return BuildResearchService(
        provider=_recording_provider(calls, **provider_kwargs),
        state=state,
        universe=VALUE_US_EQUITIES_V1,
        now=now or (lambda: AS_OF),
    )


def _priced(*securities, records=()):
    prices = tuple(_price(security, str(100 + index)) for index, security in enumerate(securities))
    cached = tuple(records) + tuple(_cached_overview(security) for security in securities)
    return FakeCycleState(price_observations=prices, fundamental_records=cached)


def test_screen_refreshes_selected_only_and_skips_unselected():
    universe = VALUE_US_EQUITIES_V1.identities
    state = _priced(*universe)
    calls: list[tuple[str, str]] = []
    result = _service(state, calls).build(portfolio_id=uuid4())

    selected = state.screening_runs[0].selected
    assert len(state.price_observations) == 8
    assert len(selected) == 5
    selected_tickers = {security.ticker for security in selected}
    unselected_tickers = {security.ticker for security in universe} - selected_tickers
    assert len(unselected_tickers) == 3
    fetched_symbols = {symbol for _, symbol in calls}
    assert fetched_symbols == selected_tickers
    assert unselected_tickers.isdisjoint(fetched_symbols)
    assert {packet.ticker for packet in result.batch.packets} == selected_tickers
    assert all(packet.fundamentals is not None for packet in result.batch.packets)
    assert all(not hasattr(packet, "rank_key") for packet in result.batch.packets)
    assert all(not hasattr(packet, "slot_role") for packet in result.batch.packets)
    assert result.batch.screening_run_id == state.screening_runs[0].screening_run_id
    assert len(result.batch.packets) == 5


def test_manager_packet_order_is_universe_identity_not_screening_selected_order():
    by_ticker = {security.ticker: security for security in VALUE_US_EQUITIES_V1.identities}
    rank_inputs = {
        "COST": ("500", "8"),
        "V": ("400", "12"),
        "JPM": ("300", "15"),
    }
    prices = tuple(_price(security, "100") for security in VALUE_US_EQUITIES_V1.identities)
    cached = tuple(
        _cached_overview(
            security,
            fifty_two_week_high=rank_inputs.get(security.ticker, ("110", "40"))[0],
            pe_ratio=rank_inputs.get(security.ticker, ("110", "40"))[1],
        )
        for security in VALUE_US_EQUITIES_V1.identities
    )
    state = FakeCycleState(price_observations=prices, fundamental_records=cached)
    result = _service(state, []).build(portfolio_id=uuid4())

    selected = state.screening_runs[0].selected
    by_security = {item.security: item for item in state.screening_runs[0].results}
    selected_tickers = tuple(security.ticker for security in selected)
    universe_tickers = tuple(
        security.ticker for security in VALUE_US_EQUITIES_V1.identities if security in set(selected)
    )
    assert selected_tickers == ("COST", "V", "JPM", "AAPL", "AMZN")
    assert universe_tickers == ("AAPL", "AMZN", "JPM", "V", "COST")
    assert selected_tickers != universe_tickers
    assert [by_security[security].slot_role for security in selected] == [
        ResearchSlotRole.RANKED,
        ResearchSlotRole.RANKED,
        ResearchSlotRole.RANKED,
        ResearchSlotRole.COVERAGE,
        ResearchSlotRole.REPORTING_CYCLE,
    ]
    assert tuple(packet.ticker for packet in result.batch.packets) == universe_tickers

    portfolio = Portfolio(
        portfolio_id=result.batch.portfolio_id,
        portfolio_name="Value",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance("USD", Decimal("1000")),
        created_at=AS_OF,
    )
    payload = _serialize_context(
        ValueManagerDecisionContext(
            portfolio=portfolio,
            research_batch=result.batch,
            constitution=ConstitutionLoader.load_value_manager_constitution(),
        )
    )
    assert [packet["ticker"] for packet in payload["research_batch"]["packets"]] == list(universe_tickers)
    assert selected == (by_ticker["COST"], by_ticker["V"], by_ticker["JPM"], by_ticker["AAPL"], by_ticker["AMZN"])


def test_metric_inputs_use_exact_security_identity():
    target, other = VALUE_US_EQUITIES_V1.identities[:2]
    later = datetime(2026, 8, 18, 12, tzinfo=UTC)
    records = (
        ProviderFundamentalRecord(
            record_id="target-overview",
            security=target,
            provider_identity="alpha-vantage",
            endpoint=ProviderEndpoint.OVERVIEW,
            fiscal_period=PERIOD,
            source_date=PERIOD,
            fetched_at=CACHED_AT,
            facts=(("shares_outstanding", "10"),),
        ),
        ProviderFundamentalRecord(
            record_id="other-overview",
            security=other,
            provider_identity="alpha-vantage",
            endpoint=ProviderEndpoint.OVERVIEW,
            fiscal_period=PERIOD,
            source_date=PERIOD,
            fetched_at=later,
            facts=(("shares_outstanding", "99"),),
        ),
    )
    inputs = fundamental_metric_inputs_from_records(records, price=None, security=target)
    assert inputs.overview_shares == Decimal("10")


def test_reuse_matching_latest_quarter_fetches_overview_only():
    security = VALUE_US_EQUITIES_V1.identities[0]
    cached_statements = _cached_statements(security)
    state = FakeCycleState(
        price_observations=(_price(security),),
        fundamental_records=(_cached_overview(security), *cached_statements),
    )
    calls: list[tuple[str, str]] = []
    result = _service(state, calls).build(portfolio_id=uuid4())

    assert calls == [("OVERVIEW", security.ticker)]
    fetched = state.fetched_records[0]
    assert len(fetched) == 1
    assert fetched[0].endpoint is ProviderEndpoint.OVERVIEW
    assert fetched[0].fetched_at == AS_OF
    assert all(record is original for record, original in zip(state.fundamental_records[1:5], cached_statements, strict=True))
    assert all(record.fetched_at == CACHED_AT for record in cached_statements)
    coverage = {item.endpoint: item for item in result.batch.packets[0].fundamentals.coverage}
    assert coverage[ProviderEndpoint.OVERVIEW].reuse_status is ReuseStatus.FETCHED_THIS_CYCLE
    assert coverage[ProviderEndpoint.INCOME_STATEMENT].reuse_status is ReuseStatus.REUSED_CURRENT
    assert coverage[ProviderEndpoint.INCOME_STATEMENT].fetched_at == CACHED_AT


def test_period_change_fetches_overview_and_all_four_statements():
    security = VALUE_US_EQUITIES_V1.identities[0]
    cached_statements = _cached_statements(security)
    state = FakeCycleState(
        price_observations=(_price(security, observed_at=LATER),),
        fundamental_records=(_cached_overview(security), *cached_statements),
    )
    calls: list[tuple[str, str]] = []
    result = _service(
        state,
        calls,
        now=lambda: LATER,
        overview_extra={"LatestQuarter": "2026-09-30"},
        statement_date="2026-09-30",
    ).build(portfolio_id=uuid4())

    assert [function for function, _ in calls] == [
        "OVERVIEW",
        "INCOME_STATEMENT",
        "BALANCE_SHEET",
        "CASH_FLOW",
        "EARNINGS",
    ]
    fetched = state.fetched_records[0]
    assert {record.endpoint for record in fetched} == set(ProviderEndpoint)
    assert all(record.fetched_at == LATER for record in fetched)
    assert all(status.reuse_status is ReuseStatus.FETCHED_THIS_CYCLE for status in result.batch.packets[0].fundamentals.coverage)


def test_fewer_than_five_priced_names_is_not_padded():
    priced = VALUE_US_EQUITIES_V1.identities[:2]
    state = _priced(*priced)
    calls: list[tuple[str, str]] = []
    result = _service(state, calls).build(portfolio_id=uuid4())

    assert len(result.batch.packets) == 2
    assert len(state.screening_runs[0].selected) == 2
    assert {packet.ticker for packet in result.batch.packets} == {security.ticker for security in priced}
    assert {symbol for _, symbol in calls} == {security.ticker for security in priced}


def test_zero_priced_names_fails_closed_without_persist():
    state = FakeCycleState()
    calls: list[tuple[str, str]] = []
    with pytest.raises(ValueError, match="no eligible priced names"):
        _service(state, calls).build(portfolio_id=uuid4())
    assert state.batches == []
    assert state.screening_runs == []
    assert state.fetched_records == []
    assert calls == []


def test_mapper_four_cash_flow_quarters_feed_ttm():
    security = VALUE_US_EQUITIES_V1.identities[0]
    record = ProviderFundamentalRecord(
        record_id="cf-four",
        security=security,
        provider_identity="alpha-vantage",
        endpoint=ProviderEndpoint.CASH_FLOW,
        fiscal_period=PERIOD,
        source_date=PERIOD,
        fetched_at=AS_OF,
        facts=(
            ("period_0_operating_cash_flow", "5"),
            ("period_1_operating_cash_flow", "4"),
            ("period_2_operating_cash_flow", "3"),
            ("period_3_operating_cash_flow", "2"),
            ("period_0_capex", "-2"),
            ("period_1_capex", "-1"),
            ("period_2_capex", "-1"),
            ("period_3_capex", "0"),
        ),
    )
    metrics = {
        metric.metric_id: metric
        for metric in derive_fundamental_metrics(
            fundamental_metric_inputs_from_records((record,), price=None, security=security)
        )
    }
    assert metrics["ttm_ocf"].value == Decimal("14")
    assert metrics["ttm_fcf"].value == Decimal("10")


def test_mapper_fewer_than_four_cash_flow_quarters_are_not_available():
    security = VALUE_US_EQUITIES_V1.identities[0]
    record = ProviderFundamentalRecord(
        record_id="cf-three",
        security=security,
        provider_identity="alpha-vantage",
        endpoint=ProviderEndpoint.CASH_FLOW,
        fiscal_period=PERIOD,
        source_date=PERIOD,
        fetched_at=AS_OF,
        facts=(
            ("period_0_operating_cash_flow", "5"),
            ("period_1_operating_cash_flow", "4"),
            ("period_2_operating_cash_flow", "3"),
            ("period_0_capex", "-2"),
            ("period_1_capex", "-1"),
            ("period_2_capex", "-1"),
        ),
    )
    metrics = {
        metric.metric_id: metric
        for metric in derive_fundamental_metrics(
            fundamental_metric_inputs_from_records((record,), price=None, security=security)
        )
    }
    unavailable = MissingData(MissingDataReason.NOT_AVAILABLE, "fewer than four valid quarters")
    assert metrics["ttm_ocf"].value == unavailable
    assert metrics["ttm_fcf"].value == unavailable
    assert metrics["ttm_ocf"].value != Decimal("12")


def test_packet_fundamentals_present_and_rank_absent_from_packet_and_manager_json():
    security = VALUE_US_EQUITIES_V1.identities[0]
    state = _priced(security)
    result = _service(state, []).build(portfolio_id=uuid4())
    packet = result.batch.packets[0]
    assert isinstance(packet.fundamentals, PacketFundamentals)
    assert packet.fundamentals.derived
    serialized = _serialize_packet(packet)
    blob = str(serialized)
    assert "rank_key" not in blob
    assert "rank_reason" not in blob
    assert "slot_role" not in blob
    assert "screening_run_id" not in blob
    assert "RANKED" not in blob
    metrics = {item["metric_id"]: item["value"] for item in serialized["fundamentals"]["derived"]}
    assert "ttm_fcf" in metrics
    assert "market_cap" in metrics
    assert any(item["reuse_status"] == ReuseStatus.FETCHED_THIS_CYCLE.value for item in serialized["fundamentals"]["coverage"])


def test_manager_serialization_includes_derived_and_omits_screening_run_id():
    security = VALUE_US_EQUITIES_V1.identities[0]
    state = _priced(security)
    result = _service(state, []).build(portfolio_id=uuid4())
    portfolio = Portfolio(
        portfolio_id=result.batch.portfolio_id,
        portfolio_name="Value",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance("USD", Decimal("1000")),
        created_at=AS_OF,
    )
    context = ValueManagerDecisionContext(
        portfolio=portfolio,
        research_batch=result.batch,
        constitution=ConstitutionLoader.load_value_manager_constitution(),
    )
    payload = _serialize_context(context)
    assert "screening_run_id" not in payload["research_batch"]
    packet = payload["research_batch"]["packets"][0]
    assert "rank_key" not in packet
    assert "slot_role" not in packet
    derived = packet["fundamentals"]["derived"]
    assert any(item["metric_id"] == "fcf" for item in derived)
    assert any(item["metric_id"] == "enterprise_value" for item in derived)


def test_sqlite_reopen_preserves_screening_run_id_and_reused_timestamps(tmp_path):
    path = tmp_path / "research.sqlite"
    store = SQLiteLocalRunStore(path)
    initial = store.initialize_run(initialized_at=datetime(2026, 8, 13, 14, tzinfo=UTC))
    security = VALUE_US_EQUITIES_V1.identities[0]
    cached_statements = _cached_statements(security)
    store.save_transition(
        replace(
            initial,
            price_observations=(_price(security),),
            fundamental_records=(_cached_overview(security), *cached_statements),
        )
    )
    calls: list[tuple[str, str]] = []
    result = BuildResearchService(
        provider=_recording_provider(calls),
        state=SQLiteResearchBatchState(store),
        universe=VALUE_US_EQUITIES_V1,
        now=lambda: AS_OF,
    ).build(portfolio_id=initial.managed_portfolio.portfolio_id)

    reopened = SQLiteLocalRunStore(path).open_run()
    assert reopened is not None
    assert reopened.screening_runs[0].screening_run_id == result.batch.screening_run_id
    assert reopened.research_batches[0].screening_run_id == result.batch.screening_run_id
    fetched_ids = {record.record_id for record in reopened.fundamental_records} - {record.record_id for record in cached_statements} - {f"cached-{security.ticker}-OVERVIEW"}
    fetched = tuple(record for record in reopened.fundamental_records if record.record_id in fetched_ids)
    assert all(record.endpoint is ProviderEndpoint.OVERVIEW for record in fetched)
    reused = {record.record_id: record for record in reopened.fundamental_records if record.record_id.startswith("cached-") and record.endpoint is not ProviderEndpoint.OVERVIEW}
    for original in cached_statements:
        assert reused[original.record_id].fetched_at == CACHED_AT
        assert reused[original.record_id].source_date == PERIOD


def test_build_research_command_returns_batch_metadata_without_live_provider_call():
    state = _priced(*VALUE_US_EQUITIES_V1.identities[:5])
    service = _service(state, [])
    response = TestClient(create_app(research_service=service)).post("/commands/build-research")
    assert response.status_code == 200
    assert response.json()["packet_count"] == 5
    assert response.json()["source_provider_identity"] == "alpha-vantage"
    assert len(state.batches) == 1


def test_provider_failure_after_screen_does_not_persist(tmp_path):
    path = tmp_path / "research.sqlite"
    store = SQLiteLocalRunStore(path)
    initial = store.initialize_run(initialized_at=datetime(2026, 8, 13, 14, tzinfo=UTC))
    priced = VALUE_US_EQUITIES_V1.identities[:2]
    store.save_transition(
        replace(
            initial,
            price_observations=tuple(_price(security) for security in priced),
            fundamental_records=tuple(_cached_overview(security) for security in priced),
        )
    )
    calls: list[tuple[str, str]] = []

    def transport(url: str):
        query = parse_qs(urlparse(url).query)
        function, symbol = query["function"][0], query["symbol"][0]
        calls.append((function, symbol))
        if len({item[1] for item in calls}) > 1 and function == "OVERVIEW":
            raise ResearchProviderError("second selected name failed")
        security = next(item for item in VALUE_US_EQUITIES_V1.identities if item.ticker == symbol)
        payloads = {
            "OVERVIEW": _overview_payload(security),
            "INCOME_STATEMENT": _income_payload(security),
            "BALANCE_SHEET": _balance_payload(security),
            "CASH_FLOW": _cash_flow_payload(security),
            "EARNINGS": _earnings_payload(security),
        }
        return payloads[function]

    with pytest.raises(ResearchProviderError, match="second selected name failed"):
        BuildResearchService(
            provider=AlphaVantageResearchProvider(api_key="key", transport=transport, sleep=lambda _: None),
            state=SQLiteResearchBatchState(store),
            universe=VALUE_US_EQUITIES_V1,
            now=lambda: AS_OF,
        ).build(portfolio_id=initial.managed_portfolio.portfolio_id)

    reopened = SQLiteLocalRunStore(path).open_run()
    assert reopened is not None
    assert reopened.research_batches == ()
    assert reopened.screening_runs == ()
    assert all(record.record_id.startswith("cached-") for record in reopened.fundamental_records)


def test_assembled_batch_uses_injected_cycle_price_not_frontend_numbers():
    security = VALUE_US_EQUITIES_V1.identities[0]
    state = FakeCycleState(
        price_observations=(_price(security, "123.45"),),
        fundamental_records=(_cached_overview(security),),
    )
    packet = _service(state, []).build(portfolio_id=uuid4()).batch.packets[0]
    metrics = {metric.metric_id: metric for metric in packet.fundamentals.derived}
    assert "123.45" in next(section.content for section in packet.sections if section.section_id == "VALUATION")
    assert isinstance(metrics["market_cap"].value, Decimal)


def test_assembly_modules_do_not_call_live_providers():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "agentic_portfolio_lab" / "application"
    for name in ("build_research.py", "assemble_research_packets.py", "fundamental_inputs.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "urlopen" not in source
        assert "alphavantage.co" not in source
        assert "twelvedata" not in source
        assert "get_company_research" not in source
