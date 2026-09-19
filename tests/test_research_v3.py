from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from tempfile import TemporaryDirectory
from uuid import uuid4

from agentic_portfolio_lab.application.build_research_v3 import BuildResearchV3Service
from agentic_portfolio_lab.application.v2_weekly_cycle import V2WeeklyCycleService
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio, Position, SecurityIdentity
from agentic_portfolio_lab.domain.research_provider import (
    NormalizedEarningsFacts, NormalizedIncomeFacts, NormalizedOverviewFacts,
    ResearchProviderError, SourceResearchDocument, SourceResearchRecord,
)
from agentic_portfolio_lab.domain.screening_v2 import (
    ScreeningFeatures, ScreeningProfile, ScreeningProfileIdentity, ScreeningProvenance,
    ScreeningRunV2, ScreeningSecurityResult,
)
from agentic_portfolio_lab.infrastructure.v3_batch_store import SQLiteResearchV3Store
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore


NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


def _security(ticker: str) -> SecurityIdentity:
    return SecurityIdentity(ticker, "EQUITY", "NYSE", "USD")


def _run(*candidates: SecurityIdentity) -> ScreeningRunV2:
    profile = ScreeningProfile(ScreeningProfileIdentity("manager", "profile", "1"), Decimal("1"), Decimal("1"))
    results = tuple(ScreeningSecurityResult(x.ticker, x, True, "RANKED", None, ScreeningFeatures(Decimal("10"), Decimal("2"), Decimal("1"), None, Decimal(".1")), Decimal("1"), ("score_desc",), i + 1) for i, x in enumerate(candidates))
    provenance = ScreeningProvenance(NOW, ("screening-provider",), "snapshot-36", NOW)
    return ScreeningRunV2(uuid4(), profile, provenance, "snapshot-36", results, candidates, (), candidates)


def _portfolio(*positions: Position) -> Portfolio:
    return Portfolio(uuid4(), "test", "USD", Decimal("1000"), CashBalance("USD", Decimal("1000")), NOW, positions)


class _Provider:
    def __init__(self): self.calls = []
    def get_company_research(self, security):
        self.calls.append(security)
        raise ResearchProviderError("offline")


def _document(security: SecurityIdentity) -> SourceResearchDocument:
    def source(kind: str, value: str) -> SourceResearchRecord:
        return SourceResearchRecord(kind, f"{kind} source", date(2020, 1, 1), (("shared", value),), f"provider-ref:{kind}")
    overview = NormalizedOverviewFacts(
        source=source("overview", "one"), company_name="Example", description=None,
        exchange="NYSE", currency="USD", asset_type="EQUITY", sector=None,
        industry=None, market_cap=None, pe_ratio=None, peg_ratio=None, eps=None,
        revenue_per_share=None, profit_margin=None, operating_margin=None,
        return_on_equity=None, quarterly_revenue_growth=None,
        quarterly_earnings_growth=None, fifty_two_week_high=None,
        fifty_two_week_low=None, analyst_target_price=None, price_to_book_ratio=None,
        beta=None, dividend_yield=None, latest_quarter=None,
    )
    return SourceResearchDocument(security, "offline-provider", overview, NormalizedIncomeFacts(source("income", "two"), "2020", "USD", "1", None, None, None), NormalizedEarningsFacts(source("earnings", "one"), "2020", "2020", "1", None, None, None))


class _DocumentProvider:
    def __init__(self): self.calls = []
    def get_company_research(self, security):
        self.calls.append(security)
        return _document(security)


def test_v3_researches_candidates_and_holdings_with_roles_and_lineage():
    candidate, held = _security("NEW"), _security("HELD")
    provider = _Provider()
    batch = BuildResearchV3Service(provider=provider, now=lambda: NOW).build(
        screening_run=_run(candidate),
        portfolio=_portfolio(Position(held, Decimal("2"), Decimal("10"), Decimal("5"))),
    )
    assert tuple(item.security for item in batch.subjects) == (candidate, held)
    assert batch.subjects[0].role.value == "NEW_CANDIDATE"
    assert batch.subjects[1].role.value == "EXISTING_HOLDING"
    assert batch.subjects[0].screening_context.snapshot_id == "snapshot-36"
    assert batch.subjects[0].screening_context.rank == 1
    assert batch.subjects[0].missing_data
    assert tuple(provider.calls) == (candidate, held)


def test_v3_total_retrieval_is_bounded_and_holdings_are_carried_forward():
    candidates = tuple(_security(f"C{i}") for i in range(5))
    held = _security("HELD")
    provider = _Provider()
    batch = BuildResearchV3Service(provider=provider, now=lambda: NOW, max_deep_research_subjects=2).build(
        screening_run=_run(*candidates),
        portfolio=_portfolio(Position(held, Decimal("1"), Decimal("1"), Decimal("1"))),
    )
    assert tuple(item.security for item in batch.subjects) == (*candidates, held)
    assert len(provider.calls) == 2
    assert held in tuple(item.security for item in batch.subjects)


def test_v3_represents_every_holding_when_provider_retrieval_is_capped():
    candidate = _security("NEW")
    holdings = tuple(_security(f"HELD{i}") for i in range(3))
    provider = _Provider()
    batch = BuildResearchV3Service(provider=provider, now=lambda: NOW, max_deep_research_subjects=2).build(
        screening_run=_run(candidate),
        portfolio=_portfolio(*(Position(security, Decimal("1"), Decimal("1"), Decimal("1")) for security in holdings)),
    )
    assert tuple(item.security for item in batch.subjects) == (candidate, *holdings)
    assert [item.role.value for item in batch.subjects[1:]] == ["EXISTING_HOLDING"] * 3
    assert tuple(provider.calls) == (candidate, holdings[0])
    assert batch.subjects[2].missing_data[0].details == "Deep research was not retrieved because max_deep_research_subjects was reached."


def test_v3_successful_provider_evidence_keeps_reference_stale_missing_and_contradiction_state():
    security = _security("NEW")
    batch = BuildResearchV3Service(provider=_DocumentProvider(), now=lambda: NOW).build(
        screening_run=_run(security), portfolio=_portfolio(),
    )
    subject = batch.subjects[0]
    assert subject.evidence_references[0] == "provider-ref:overview"
    assert {item.freshness for item in subject.evidence} == {"STALE"}
    assert subject.missing_data
    assert subject.contradictions == ("shared has conflicting provider values",)


def test_v3_sqlite_round_trip_does_not_mutate_batch():
    batch = BuildResearchV3Service(provider=_Provider(), now=lambda: NOW).build(screening_run=_run(_security("NEW")), portfolio=_portfolio())
    with TemporaryDirectory() as directory:
        store = SQLiteResearchV3Store(f"{directory}/state.db")
        store.save(batch)
        assert store.load(batch.batch_id) == batch


def test_v3_reuses_fresh_durable_company_research_without_provider_call():
    security = _security("NEW")
    provider = _DocumentProvider()
    with TemporaryDirectory() as directory:
        store = SQLiteResearchV3Store(f"{directory}/state.db")
        BuildResearchV3Service(provider=provider, store=store, now=lambda: NOW).build(screening_run=_run(security), portfolio=_portfolio())
        second = BuildResearchV3Service(provider=provider, store=store, now=lambda: NOW + timedelta(days=1)).build(screening_run=_run(security), portfolio=_portfolio())
        assert provider.calls == [security]
        assert {item.freshness for item in second.subjects[0].evidence} == {"CACHED_FRESH"}
        assert second.subjects[0].provider_document == _document(security)


def test_v3_refreshes_stale_company_research_and_preserves_append_only_history():
    security = _security("NEW")
    provider = _DocumentProvider()
    with TemporaryDirectory() as directory:
        store = SQLiteResearchV3Store(f"{directory}/state.db")
        BuildResearchV3Service(provider=provider, store=store, now=lambda: NOW).build(screening_run=_run(security), portfolio=_portfolio())
        BuildResearchV3Service(provider=provider, store=store, now=lambda: NOW + timedelta(days=8)).build(screening_run=_run(security), portfolio=_portfolio())
        history = store.company_research_history(security)
        assert provider.calls == [security, security]
        assert len(history) == 2
        assert {item.retrieved_at for item in history} == {NOW, NOW + timedelta(days=8)}


def test_v3_keeps_full_slate_and_marks_subjects_not_retrieved_when_daily_budget_is_spent():
    securities = tuple(_security(f"C{i}") for i in range(3))
    provider = _DocumentProvider()
    with TemporaryDirectory() as directory:
        store = SQLiteResearchV3Store(f"{directory}/state.db")
        service = BuildResearchV3Service(provider=provider, store=store, now=lambda: NOW, max_deep_research_subjects=2)
        service.build(screening_run=_run(*securities[:2]), portfolio=_portfolio())
        batch = service.build(screening_run=_run(*securities), portfolio=_portfolio())
        assert provider.calls == [securities[0], securities[1]]
        assert tuple(subject.security for subject in batch.subjects) == securities
        assert {item.freshness for item in batch.subjects[0].evidence} == {"CACHED_FRESH"}
        assert batch.subjects[2].evidence[0].freshness == "NOT_RETRIEVED"


def test_v3_persists_each_successful_company_version_when_later_v2_cycle_stage_fails():
    security = _security("NEW")
    provider = _DocumentProvider()

    class _ScreeningService:
        def execute(self, **kwargs):
            return _run(security)

    class _FailingManager:
        def decide_v2(self, context):
            raise RuntimeError("manager stage failed")

    with TemporaryDirectory() as directory:
        cache = SQLiteResearchV3Store(f"{directory}/state.db")
        local_state = SQLiteLocalRunStore(f"{directory}/local-state.db")
        local_state.initialize_run(initialized_at=NOW)
        cycle = V2WeeklyCycleService(local_state, now=lambda: NOW)
        research = BuildResearchV3Service(provider=provider, store=cache, now=lambda: NOW)
        try:
            cycle.prepare(
                snapshot_id="snapshot-36", profile_identity="unused", as_of=NOW,
                screening_service=_ScreeningService(), research_service=research,
                manager=_FailingManager(), price_snapshot=None,
                manager_risk_service=object(), reviewer=None,
            )
        except RuntimeError as error:
            assert str(error) == "manager stage failed"
        else:
            raise AssertionError("expected manager-stage failure")
        assert cache.latest_company_research(security) is not None
