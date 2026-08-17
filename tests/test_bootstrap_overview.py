"""OVERVIEW bootstrap: skip cached, cap 25, persist each success, exact identity."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agentic_portfolio_lab.api.app import create_app
from agentic_portfolio_lab.api.queries import MvpReadStateSnapshot
from agentic_portfolio_lab.application.bootstrap_overview import BootstrapOverviewResult, BootstrapOverviewService
from agentic_portfolio_lab.application.market_configuration import (
    ALPHA_VANTAGE_DAILY_REQUEST_LIMIT,
    VALUE_US_EQUITIES_V1,
)
from agentic_portfolio_lab.dashboard_demo import build_demo_dashboard_data
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.provider_fundamentals import ProviderEndpoint, ProviderFundamentalRecord
from agentic_portfolio_lab.domain.research_provider import (
    NormalizedOverviewFacts,
    ResearchProviderError,
    SourceResearchRecord,
)
from agentic_portfolio_lab.domain.screening import ResearchSlotRole, ScreeningCandidateResult, ScreeningRun
from agentic_portfolio_lab.domain.universe import CandidateUniverse
from agentic_portfolio_lab.infrastructure.alpha_vantage import AlphaVantageResearchProvider
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore, SQLiteOverviewBootstrapState

UTC = timezone.utc
AS_OF = datetime(2026, 8, 17, 16, tzinfo=UTC)
PERIOD = date(2026, 6, 30)


def _equity(ticker: str, *, exchange: str = "NASDAQ") -> SecurityIdentity:
    return SecurityIdentity(ticker, "EQUITY", exchange, "USD")


def _overview_facts(security: SecurityIdentity, *, latest_quarter: str | None = "2026-06-30") -> NormalizedOverviewFacts:
    facts = (("company_name", security.ticker),)
    if latest_quarter is not None:
        facts = (*facts, ("latest_quarter", latest_quarter))
    return NormalizedOverviewFacts(
        source=SourceResearchRecord(
            "ALPHA_VANTAGE_OVERVIEW",
            "Alpha Vantage company overview",
            PERIOD,
            facts,
        ),
        company_name=security.ticker,
        description="description",
        exchange=security.exchange,
        currency=security.currency,
        asset_type=security.security_type,
        sector="Technology",
        industry="Software",
        market_cap="100",
        pe_ratio="20",
        peg_ratio=None,
        eps=None,
        revenue_per_share=None,
        profit_margin=None,
        operating_margin=None,
        return_on_equity=None,
        quarterly_revenue_growth=None,
        quarterly_earnings_growth=None,
        fifty_two_week_high="200",
        fifty_two_week_low=None,
        analyst_target_price=None,
        price_to_book_ratio=None,
        beta=None,
        dividend_yield=None,
        latest_quarter=latest_quarter,
    )


def _cached_overview(security: SecurityIdentity, *, record_id: str | None = None) -> ProviderFundamentalRecord:
    return ProviderFundamentalRecord(
        record_id=record_id or f"cached-{security.ticker}-{security.exchange}-OVERVIEW",
        security=security,
        provider_identity="alpha-vantage",
        endpoint=ProviderEndpoint.OVERVIEW,
        fiscal_period=PERIOD,
        source_date=PERIOD,
        fetched_at=AS_OF,
        facts=(("company_name", security.ticker),),
    )


def _cached_income(security: SecurityIdentity) -> ProviderFundamentalRecord:
    return ProviderFundamentalRecord(
        record_id=f"cached-{security.ticker}-INCOME_STATEMENT",
        security=security,
        provider_identity="alpha-vantage",
        endpoint=ProviderEndpoint.INCOME_STATEMENT,
        fiscal_period=PERIOD,
        source_date=PERIOD,
        fetched_at=AS_OF,
        facts=(("total_revenue", "10"),),
    )


@dataclass
class FakeOverviewState:
    records: list[ProviderFundamentalRecord] = field(default_factory=list)

    def load_fundamental_records(self) -> tuple[ProviderFundamentalRecord, ...]:
        return tuple(self.records)

    def persist_overview_record(self, record: ProviderFundamentalRecord) -> None:
        if record.endpoint is not ProviderEndpoint.OVERVIEW:
            raise ValueError("overview bootstrap may persist OVERVIEW records only")
        if any(existing.record_id == record.record_id for existing in self.records):
            raise ValueError("fundamental record must not rewrite a persisted record")
        self.records.append(record)


class FakeOverviewProvider:
    def __init__(
        self,
        *,
        fail_on: SecurityIdentity | None = None,
        latest_quarter: str | None = "2026-06-30",
    ) -> None:
        self.calls: list[SecurityIdentity] = []
        self.fail_on = fail_on
        self.latest_quarter = latest_quarter
        self.statement_calls = 0

    def fetch_overview(self, security: SecurityIdentity, *, as_of: datetime | None = None) -> NormalizedOverviewFacts:
        del as_of
        self.calls.append(security)
        if security == self.fail_on:
            raise ResearchProviderError("later OVERVIEW fetch failed")
        return _overview_facts(security, latest_quarter=self.latest_quarter)

    def fetch_income_statement(self, security: SecurityIdentity, *, as_of: datetime | None = None):
        del security, as_of
        self.statement_calls += 1
        raise AssertionError("bootstrap must not fetch INCOME_STATEMENT")

    def fetch_balance_sheet(self, security: SecurityIdentity, *, as_of: datetime | None = None):
        del security, as_of
        self.statement_calls += 1
        raise AssertionError("bootstrap must not fetch BALANCE_SHEET")

    def fetch_cash_flow(self, security: SecurityIdentity, *, as_of: datetime | None = None):
        del security, as_of
        self.statement_calls += 1
        raise AssertionError("bootstrap must not fetch CASH_FLOW")

    def fetch_earnings(self, security: SecurityIdentity, *, as_of: datetime | None = None):
        del security, as_of
        self.statement_calls += 1
        raise AssertionError("bootstrap must not fetch EARNINGS")


def _service(
    state: FakeOverviewState,
    provider: FakeOverviewProvider,
    *,
    universe: CandidateUniverse = VALUE_US_EQUITIES_V1,
    request_limit: int = ALPHA_VANTAGE_DAILY_REQUEST_LIMIT,
) -> BootstrapOverviewService:
    return BootstrapOverviewService(
        provider=provider,
        state=state,
        universe=universe,
        request_limit=request_limit,
        now=lambda: AS_OF,
    )


def _large_universe(count: int) -> CandidateUniverse:
    return CandidateUniverse(
        "test-bootstrap-universe",
        tuple(_equity(f"T{index:02d}") for index in range(count)),
    )


def test_skips_cached_overview_for_exact_identity_and_fetches_the_rest():
    identities = VALUE_US_EQUITIES_V1.identities[:3]
    universe = CandidateUniverse("cache-skip-slice", identities)
    cached = identities[0]
    state = FakeOverviewState(records=[_cached_overview(cached)])
    provider = FakeOverviewProvider()

    result = _service(state, provider, universe=universe).bootstrap()

    assert result.skipped == (cached,)
    assert result.fetched == identities[1:]
    assert result.remaining == ()
    assert result.request_count == len(identities) - 1
    assert result.request_count <= ALPHA_VANTAGE_DAILY_REQUEST_LIMIT
    assert provider.calls == list(identities[1:])
    assert provider.statement_calls == 0
    assert all(record.endpoint is ProviderEndpoint.OVERVIEW for record in state.records)
    assert all(record.security == cached or record.security in result.fetched for record in state.records)


def test_income_statement_cache_does_not_skip_overview_fetch():
    security = VALUE_US_EQUITIES_V1.identities[0]
    state = FakeOverviewState(records=[_cached_income(security)])
    provider = FakeOverviewProvider()

    result = _service(state, provider, universe=CandidateUniverse("one-name", (security,))).bootstrap()

    assert result.fetched == (security,)
    assert result.skipped == ()
    assert provider.calls == [security]


def test_same_ticker_different_exchange_does_not_count_as_cached():
    universe_identity = VALUE_US_EQUITIES_V1.identities[0]
    assert universe_identity.ticker == "MSFT"
    other_exchange = _equity("MSFT", exchange="NYSE")
    state = FakeOverviewState(records=[_cached_overview(other_exchange)])
    provider = FakeOverviewProvider()

    result = _service(state, provider, universe=CandidateUniverse("msft-only", (universe_identity,))).bootstrap()

    assert result.fetched == (universe_identity,)
    assert result.skipped == ()
    assert provider.calls == [universe_identity]
    persisted = [record for record in state.records if record.record_id.startswith("MSFT-OVERVIEW-")]
    assert persisted[0].security == universe_identity
    assert persisted[0].security != other_exchange


def test_caps_fetches_at_25_and_lists_remaining_in_universe_order():
    universe = _large_universe(30)
    state = FakeOverviewState(records=[_cached_overview(universe.identities[0])])
    provider = FakeOverviewProvider()

    result = _service(state, provider, universe=universe).bootstrap()

    assert ALPHA_VANTAGE_DAILY_REQUEST_LIMIT == 25
    assert result.request_count == 25
    assert result.skipped == (universe.identities[0],)
    assert result.fetched == universe.identities[1:26]
    assert result.remaining == universe.identities[26:]
    assert provider.calls == list(universe.identities[1:26])
    assert all(record.endpoint is ProviderEndpoint.OVERVIEW for record in state.records)


def test_unparseable_latest_quarter_still_persists_overview_row():
    security = VALUE_US_EQUITIES_V1.identities[0]
    state = FakeOverviewState()
    provider = FakeOverviewProvider(latest_quarter="Q2 2026")

    result = _service(state, provider, universe=CandidateUniverse("one-name", (security,))).bootstrap()

    assert result.fetched == (security,)
    assert state.records[0].fiscal_period is None
    assert state.records[0].endpoint is ProviderEndpoint.OVERVIEW


def test_persists_successful_overview_before_a_later_failure(tmp_path):
    path = tmp_path / "bootstrap.sqlite"
    store = SQLiteLocalRunStore(path)
    store.initialize_run(initialized_at=AS_OF)
    first, second = VALUE_US_EQUITIES_V1.identities[:2]
    provider = FakeOverviewProvider(fail_on=second)
    service = BootstrapOverviewService(
        provider=provider,
        state=SQLiteOverviewBootstrapState(store),
        universe=CandidateUniverse("two-name", (first, second)),
        now=lambda: AS_OF,
    )

    with pytest.raises(ResearchProviderError, match="later OVERVIEW fetch failed"):
        service.bootstrap()

    reopened = SQLiteLocalRunStore(path).open_run()
    assert reopened is not None
    fetched = [record for record in reopened.fundamental_records if not record.record_id.startswith("cached-")]
    assert [record.security for record in fetched] == [first]
    assert fetched[0].endpoint is ProviderEndpoint.OVERVIEW
    assert reopened.research_batches == ()
    assert reopened.screening_runs == ()


def test_sqlite_reopen_preserves_bootstrapped_overview_and_skips_on_rerun(tmp_path):
    path = tmp_path / "bootstrap.sqlite"
    store = SQLiteLocalRunStore(path)
    store.initialize_run(initialized_at=AS_OF)
    universe = CandidateUniverse("two-name", VALUE_US_EQUITIES_V1.identities[:2])
    provider = FakeOverviewProvider()
    service = BootstrapOverviewService(
        provider=provider,
        state=SQLiteOverviewBootstrapState(store),
        universe=universe,
        now=lambda: AS_OF,
    )

    first = service.bootstrap()
    reopened_store = SQLiteLocalRunStore(path)
    second_provider = FakeOverviewProvider()
    second = BootstrapOverviewService(
        provider=second_provider,
        state=SQLiteOverviewBootstrapState(reopened_store),
        universe=universe,
        now=lambda: AS_OF,
    ).bootstrap()

    persisted = reopened_store.open_run()
    assert first.fetched == universe.identities
    assert first.request_count == 2
    assert second.fetched == ()
    assert second.skipped == universe.identities
    assert second.remaining == ()
    assert second.request_count == 0
    assert second_provider.calls == []
    assert persisted is not None
    assert [record.security for record in persisted.fundamental_records] == list(universe.identities)
    assert all(record.endpoint is ProviderEndpoint.OVERVIEW for record in persisted.fundamental_records)


def test_sqlite_overview_persist_rejects_non_overview_and_rewrite(tmp_path):
    path = tmp_path / "bootstrap.sqlite"
    store = SQLiteLocalRunStore(path)
    store.initialize_run(initialized_at=AS_OF)
    state = SQLiteOverviewBootstrapState(store)
    record = _cached_overview(VALUE_US_EQUITIES_V1.identities[0])
    state.persist_overview_record(record)
    with pytest.raises(ValueError, match="OVERVIEW records only"):
        state.persist_overview_record(_cached_income(VALUE_US_EQUITIES_V1.identities[0]))
    with pytest.raises(ValueError, match="must not rewrite"):
        state.persist_overview_record(record)


def test_adapter_transport_never_requests_statements_during_bootstrap():
    calls: list[str] = []
    security = VALUE_US_EQUITIES_V1.identities[0]

    def transport(url: str):
        query = parse_qs(urlparse(url).query)
        function = query["function"][0]
        calls.append(function)
        if function != "OVERVIEW":
            raise AssertionError(f"unexpected Alpha Vantage function {function}")
        return {
            "Symbol": security.ticker,
            "Name": security.ticker,
            "Exchange": security.exchange,
            "Currency": "USD",
            "AssetType": "Common Stock",
            "LatestQuarter": "2026-06-30",
        }

    result = BootstrapOverviewService(
        provider=AlphaVantageResearchProvider(api_key="key", transport=transport, sleep=lambda _: None),
        state=FakeOverviewState(),
        universe=CandidateUniverse("one-name", (security,)),
        now=lambda: AS_OF,
    ).bootstrap()

    assert calls == ["OVERVIEW"]
    assert result.fetched == (security,)
    assert result.provider_identity == "alpha-vantage"


def test_in_memory_demo_bootstrap_is_unavailable():
    response = TestClient(create_app()).post("/commands/bootstrap-overview")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "overview_bootstrap_unavailable"


def test_bootstrap_command_uses_injected_fake_without_live_calls():
    fetched = VALUE_US_EQUITIES_V1.identities[:2]
    remaining = VALUE_US_EQUITIES_V1.identities[2:]

    class Injected:
        def bootstrap(self) -> BootstrapOverviewResult:
            return BootstrapOverviewResult(
                fetched=fetched,
                skipped=(),
                remaining=remaining,
                request_count=2,
                provider_identity="alpha-vantage",
            )

    response = TestClient(create_app(bootstrap_overview_service=Injected())).post("/commands/bootstrap-overview")
    assert response.status_code == 200
    body = response.json()
    assert [item["ticker"] for item in body["fetched"]] == [security.ticker for security in fetched]
    assert [item["exchange"] for item in body["fetched"]] == [security.exchange for security in fetched]
    assert [item["ticker"] for item in body["remaining"]] == [security.ticker for security in remaining]
    assert body["skipped"] == []
    assert body["request_count"] == 2
    assert body["provider_identity"] == "alpha-vantage"


def test_research_latest_exposes_operator_slot_roles_without_rank():
    demo = MvpReadStateSnapshot.from_dashboard_demo(build_demo_dashboard_data())
    batch = demo.latest_journal_entry.decision_result.context.research_batch
    run_id = uuid4()
    identities = (
        _equity("AAPL"),
        _equity("MSFT"),
        _equity("GOOGL"),
    )
    run = ScreeningRun(
        screening_run_id=run_id,
        universe_version="value-us-equities-v1",
        universe_identities=identities,
        as_of=batch.as_of_timestamp,
        results=(
            ScreeningCandidateResult(
                security=identities[0],
                eligible=True,
                ineligibility_reason=None,
                rank_key=("1", "secret-rank"),
                rank_reason="do not serialize",
                slot_role=ResearchSlotRole.RANKED,
            ),
            ScreeningCandidateResult(
                security=identities[1],
                eligible=True,
                ineligibility_reason=None,
                rank_key=("2",),
                rank_reason="do not serialize",
                slot_role=ResearchSlotRole.COVERAGE,
            ),
            ScreeningCandidateResult(
                security=identities[2],
                eligible=False,
                ineligibility_reason="ineligible: missing current-cycle price",
                rank_key=(),
                rank_reason="ineligible: missing current-cycle price",
            ),
        ),
        selected=identities[:2],
    )
    state = replace(
        demo,
        research_batches=(replace(batch, screening_run_id=run_id),),
        screening_runs=(run,),
    )
    client = TestClient(create_app(state=state))

    research = client.get("/research/latest")
    dashboard = client.get("/dashboard")

    assert research.status_code == dashboard.status_code == 200
    body = research.json()
    assert body["screening_run_id"] == str(run_id)
    assert [(item["security"]["ticker"], item["slot_role"]) for item in body["selected"]] == [
        ("AAPL", "RANKED"),
        ("MSFT", "COVERAGE"),
    ]
    assert "rank_key" not in body
    assert "rank_reason" not in body
    assert all("rank_key" not in item and "rank_reason" not in item for item in body["selected"])
    dashboard_research = dashboard.json()["research"]
    assert dashboard_research["screening_run_id"] == str(run_id)
    assert dashboard_research["selected"] == body["selected"]


def test_bootstrap_module_does_not_call_live_providers():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "agentic_portfolio_lab"
        / "application"
        / "bootstrap_overview.py"
    ).read_text(encoding="utf-8")
    assert "urlopen" not in source
    assert "alphavantage.co" not in source
    assert "twelvedata" not in source
    assert "get_company_research" not in source
    assert "fetch_income_statement" not in source
    assert "fetch_balance_sheet" not in source
    assert "fetch_cash_flow" not in source
    assert "fetch_earnings" not in source
