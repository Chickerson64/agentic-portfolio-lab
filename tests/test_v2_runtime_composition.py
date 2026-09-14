"""Release-gate coverage for the default configured V2 composition path."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import importlib
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

app_module = importlib.import_module("agentic_portfolio_lab.api.app")
from agentic_portfolio_lab.application.v2_advisory import DeterministicV2Reviewer
from agentic_portfolio_lab.application.wave2_commands import CashEventService
from agentic_portfolio_lab.domain import CashClassification, CashTarget, PortfolioTargetAllocation, PortfolioTargetPosition, RecommendationEvidenceReference, SecurityIdentity, V2PriceSnapshot
from agentic_portfolio_lab.domain.recommendations import ReviewTrigger
from agentic_portfolio_lab.domain.research_v3 import ResearchBatchV3, ResearchSubjectRole, ResearchV3Evidence, ResearchV3Subject, ScreeningEvidenceContext
from agentic_portfolio_lab.domain.screening_v2 import ScreeningFeatures, ScreeningProfile, ScreeningProfileIdentity, ScreeningProvenance, ScreeningRunV2
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.domain.universe_snapshots import EligibilityOutcome, UniverseEligibilityRules, UniverseSnapshot
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore


NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
IDENTITY = ScreeningProfileIdentity("configured-manager", "configured-screen", "v2.1")


def _profile(identity: ScreeningProfileIdentity = IDENTITY) -> ScreeningProfile:
    return ScreeningProfile(identity, Decimal("1"), Decimal("1"), liquidity_window=5, momentum_window=5, relative_strength_window=5, volatility_window=5)


def _configure(monkeypatch, database_path, *, profile: ScreeningProfile | None = None) -> None:
    for name, value in {
        "AGENTIC_PORTFOLIO_LAB_DB_PATH": str(database_path),
        "V2_SCREENING_MANAGER_ID": IDENTITY.manager_id,
        "V2_SCREENING_PROFILE_NAME": IDENTITY.profile_name,
        "V2_SCREENING_PROFILE_VERSION": IDENTITY.profile_version,
        "ALPACA_API_KEY_ID": "test-key", "ALPACA_API_SECRET_KEY": "test-secret",
        "ALPHA_VANTAGE_API_KEY": "test-key", "OPENAI_API_KEY": "test-key",
    }.items(): monkeypatch.setenv(name, value)
    store = SQLiteLocalRunStore(database_path)
    store.initialize_run(initialized_at=NOW)
    # The V2 release scenario begins from the intended $100,000 all-cash
    # managed portfolio through the same durable funding command an operator uses.
    CashEventService(store).apply(amount=Decimal("99000"), currency="USD", source="V2_RELEASE_FIXTURE", effective_at=NOW + timedelta(seconds=1))
    if profile is not None: store.save_screening_profile(profile)


def test_v2_readiness_matrix_uses_only_the_exact_persisted_composite_profile(monkeypatch, tmp_path) -> None:
    # No DB is a different condition from a DB missing V2 configuration.
    response = TestClient(app_module.create_app()).get("/v2/readiness")
    assert response.json() == {"ready": False, "reason_code": "DURABLE_STATE_UNAVAILABLE"}

    database = tmp_path / "matrix.sqlite"
    monkeypatch.setenv("AGENTIC_PORTFOLIO_LAB_DB_PATH", str(database))
    SQLiteLocalRunStore(database).initialize_run(initialized_at=NOW)
    assert TestClient(app_module.create_app()).get("/v2/readiness").json() == {"ready": False, "reason_code": "SCREENING_PROFILE_UNCONFIGURED"}

    monkeypatch.setenv("V2_SCREENING_MANAGER_ID", IDENTITY.manager_id)
    monkeypatch.setenv("V2_SCREENING_PROFILE_NAME", IDENTITY.profile_name)
    monkeypatch.setenv("V2_SCREENING_PROFILE_VERSION", IDENTITY.profile_version)
    assert TestClient(app_module.create_app()).get("/v2/readiness").json() == {"ready": False, "reason_code": "SCREENING_PROFILE_NOT_FOUND"}

    store = SQLiteLocalRunStore(database)
    first = _profile(ScreeningProfileIdentity("other-manager", IDENTITY.profile_name, IDENTITY.profile_version))
    latest = _profile(ScreeningProfileIdentity(IDENTITY.manager_id, "later-profile", "v9"))
    store.save_screening_profile(first); store.save_screening_profile(latest)
    # Neither first nor latest is guessed in place of the requested composite identity.
    assert TestClient(app_module.create_app()).get("/v2/readiness").json() == {"ready": False, "reason_code": "SCREENING_PROFILE_NOT_FOUND"}

    store.save_screening_profile(_profile())
    assert TestClient(app_module.create_app()).get("/v2/readiness").json() == {"ready": False, "reason_code": "PROVIDER_UNCONFIGURED"}


def test_default_create_app_composes_and_persists_a_real_v2_cycle_without_live_providers(monkeypatch, tmp_path) -> None:
    database = tmp_path / "configured.sqlite"
    _configure(monkeypatch, database, profile=_profile())
    securities = (SecurityIdentity("AAPL", "EQUITY", "NASDAQ", "USD"), SecurityIdentity("MSFT", "EQUITY", "NASDAQ", "USD"))
    evidence = ResearchV3Evidence("fixture-evidence", "fixture-research", "FILING", "Fixture filing", date(2026, 9, 13), "fixture-ref", "CURRENT")

    class FakeUniverse:
        def __init__(self, *, state, **kwargs): self.store = state
        def refresh(self):
            snapshot = UniverseSnapshot("fixture-universe", "fixture-market", NOW, NOW, UniverseEligibilityRules(), tuple(EligibilityOutcome(security.ticker, True, "eligible", security) for security in securities), ())
            self.store.save_universe_snapshot(snapshot)
            return snapshot
    class FakeScreen:
        def __init__(self, store, market): self.store = store
        def execute(self, *, snapshot_id, profile_identity, as_of):
            assert profile_identity == IDENTITY
            profile = self.store.load_screening_profile(profile_identity)
            return ScreeningRunV2(uuid4(), profile, ScreeningProvenance(NOW, ("fixture-market",), snapshot_id, NOW), snapshot_id, (), securities, (), securities)
    class FakeResearch:
        def __init__(self, **kwargs): pass
        def build(self, *, screening_run, portfolio):
            subjects = tuple(ResearchV3Subject(
                security.ticker.lower(), security, ResearchSubjectRole.NEW_CANDIDATE, NOW, (evidence,), "fixture-research",
                ScreeningEvidenceContext(screening_run.universe_snapshot_id, IDENTITY, screening_run.screening_run_id, index + 1, ScreeningFeatures(Decimal("100"), Decimal("1000000"), Decimal("1"), None, Decimal("1"))),
            ) for index, security in enumerate(securities))
            return ResearchBatchV3("fixture-research-v3", screening_run.screening_run_id, screening_run.universe_snapshot_id, IDENTITY, NOW, subjects)
    class FakeManager:
        def decide(self, context): raise AssertionError("V1 manager path must not run during V2 preparation")
        def decide_v2(self, context):
            positions = tuple(PortfolioTargetPosition(security, Decimal("0.35"), "core", f"{security.ticker} thesis", 80, (RecommendationEvidenceReference("fixture-evidence", "FILING", "Fixture filing", date(2026, 9, 13), "supports thesis"),), (), (ReviewTrigger("scheduled", "quarterly"),), "INITIATE") for security in securities)
            return PortfolioTargetAllocation(context.portfolio.portfolio_id, "Diversified researched target.", "Risk retained.", "Two names.", "SPY context.", CashTarget(Decimal("0.30"), CashClassification.STRATEGIC, "Intentional cash reserve."), positions)
    class FakePrices:
        def __init__(self, market): pass
        def snapshot(self, portfolio, target):
            return V2PriceSnapshot(tuple(PriceObservation(security, Decimal("100"), NOW.date(), NOW, "USD", "fixture-market", "quote") for security in securities))
    class FakeReviewer:
        def review(self, **kwargs): return DeterministicV2Reviewer().review(**kwargs)

    monkeypatch.setattr(app_module, "AlpacaClient", lambda: object())
    monkeypatch.setattr(app_module, "RefreshUniverseService", FakeUniverse)
    monkeypatch.setattr(app_module, "ScreenUniverseV2Service", FakeScreen)
    monkeypatch.setattr(app_module, "BuildResearchV3Service", FakeResearch)
    monkeypatch.setattr(app_module, "OpenAIValueManager", FakeManager)
    monkeypatch.setattr(app_module, "MarketDataV2PriceSnapshotProvider", FakePrices)
    monkeypatch.setattr(app_module, "OpenAIV2Reviewer", FakeReviewer)

    client = TestClient(app_module.create_app())
    assert client.get("/v2/readiness").json() == {"ready": True, "reason_code": None}
    created = client.post("/v2/cycles")
    assert created.status_code == 200
    cycle = created.json()
    assert Decimal(cycle["current_portfolio"]["cash"]) == Decimal("100000")
    assert len(cycle["target"]["positions"]) == 2 and Decimal(cycle["target"]["cash"]["weight"]) == Decimal("0.30")
    assert cycle["target"]["total_weight"] == "1.000000" and cycle["plan"]["legs"]
    assert cycle["system_safety"]["passed"] is True
    assert cycle["manager_risk"]["target_identity"] == cycle["audit"]["target_identity"]
    assert cycle["ai_reviewer"]["plan_identity"] == cycle["audit"]["plan_identity"]
    assert cycle["readiness"]["approval_status"] == "PENDING"
    assert SQLiteLocalRunStore(database).load_universe_snapshot("fixture-universe") is not None

    cycle_id = cycle["cycle_id"]
    decision_time = datetime.now(timezone.utc) + timedelta(minutes=1)
    approved = client.post(f"/v2/cycles/{cycle_id}/approve", json={"decision_maker_id": "operator", "decided_at": decision_time.isoformat()})
    assert approved.status_code == 200
    executed = client.post(f"/v2/cycles/{cycle_id}/execute", params={"executed_at": (decision_time + timedelta(minutes=1)).isoformat()})
    assert executed.status_code == 200
    assert executed.json()["execution"]["backend"] == "internal-simulator"
    assert executed.json()["reconciliation"]["resulting_portfolio"]["positions"]
    reloaded = SQLiteLocalRunStore(database).open_run()
    assert reloaded is not None and len(reloaded.v2_cycles) == 1
    assert reloaded.v2_cycles[0].execution is not None and reloaded.v2_cycles[0].reconciled_at is not None
