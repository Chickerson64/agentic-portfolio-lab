"""Focused tests for the read-only FastAPI application adapter."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from agentic_portfolio_lab.api.app import create_app
from agentic_portfolio_lab.application.market_configuration import CANDIDATE_UNIVERSE, SPY_BENCHMARK
from agentic_portfolio_lab.application.refresh_prices import InMemoryPriceRefreshState, RefreshPricesService
from agentic_portfolio_lab.domain.market_prices import MarketPriceError
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.api.queries import MvpReadStateSnapshot, StateSourceMetadata
from agentic_portfolio_lab.dashboard_demo import build_demo_dashboard_data
from datetime import date, datetime
from decimal import Decimal


class _RefreshProvider:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def get_observation(self, security):
        if self.error:
            raise self.error
        return PriceObservation(
            security=security, observed_price=Decimal("101.2500"), currency="USD", market_date=date(2026, 8, 13),
            observed_at=datetime(2026, 8, 13, 20, 0, tzinfo=timezone.utc), source_provider_identity="fake-provider",
            price_convention="fake-price",
        )


def _refresh_client(provider: _RefreshProvider) -> tuple[TestClient, InMemoryPriceRefreshState]:
    refresh_state = InMemoryPriceRefreshState()
    refresh_service = RefreshPricesService(
        provider=provider, state=refresh_state, candidate_universe=CANDIDATE_UNIVERSE, spy_benchmark=SPY_BENCHMARK,
    )
    return TestClient(create_app(refresh_service=refresh_service)), refresh_state


def _client() -> TestClient:
    return TestClient(create_app())


def _state() -> MvpReadStateSnapshot:
    return MvpReadStateSnapshot.from_dashboard_demo(build_demo_dashboard_data())


def test_health_endpoint_describes_the_explicit_demo_state() -> None:
    response = _client().get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "state_mode": "synthetic-in-memory",
        "persisted": False,
        "synthetic": True,
    }


def test_portfolio_and_benchmark_responses_preserve_snapshot_identity_and_decimal_strings() -> None:
    client = _client()
    portfolio = client.get("/portfolio")
    benchmark = client.get("/benchmark")

    assert portfolio.status_code == benchmark.status_code == 200
    portfolio_body = portfolio.json()
    benchmark_body = benchmark.json()
    assert portfolio_body["portfolio_id"] == "00000000-0000-0000-0000-000000000018"
    assert portfolio_body["cash_value"] == "450"
    assert isinstance(portfolio_body["total_value"], str)
    assert portfolio_body["as_of_timestamp"].endswith("+00:00")
    assert benchmark_body["benchmark_security"]["ticker"] == "SPY"
    assert benchmark_body["snapshot"]["portfolio_id"] == "00000000-0000-0000-0000-000000000019"


def test_performance_and_latest_decision_preserve_lineage_and_optional_execution() -> None:
    client = _client()
    performance = client.get("/performance")
    decision = client.get("/decisions/latest")

    assert performance.status_code == decision.status_code == 200
    performance_body = performance.json()
    decision_body = decision.json()
    assert isinstance(performance_body["absolute_alpha"], str)
    assert decision_body["decision_cycle_id"] == "00000000-0000-0000-0000-000000000021"
    assert decision_body["portfolio_id"] == performance_body["managed_portfolio_id"]
    assert decision_body["research_batch_id"] == "demo_batch_001"
    assert decision_body["reviewer"]["decision"] == "APPROVE"
    assert decision_body["approval"]["decision"] == "APPROVED"
    assert decision_body["execution"] is None


def test_research_and_history_responses_expose_immutable_artifact_metadata() -> None:
    client = _client()
    research = client.get("/research/latest")
    history = client.get("/decisions")

    assert research.status_code == history.status_code == 200
    research_body = research.json()
    history_body = history.json()
    assert research_body["decision_cycle_id"] == "00000000-0000-0000-0000-000000000021"
    assert research_body["packets"][0]["evidence"][0]["evidence_id"] == "demo_ev_001"
    assert history_body["entries_newest_first"][0]["action"] == "HOLD"
    assert history_body["entries_newest_first"][0]["execution"]["status"] == "No execution — HOLD"
    assert history_body["entries_newest_first"][1]["action"] == "BUY"
    assert history_body["entries_newest_first"][1]["execution"]["executed_at"].endswith("+00:00")
    assert isinstance(history_body["chart_points_oldest_first"][0]["portfolio_value"], str)


def test_dashboard_composes_existing_query_models_without_mutating_injected_state() -> None:
    state = _state()
    histories_before = (state.managed_history, state.benchmark_history, state.history_entries)
    response = TestClient(create_app(state=state)).get("/dashboard")

    assert response.status_code == 200
    body = response.json()
    assert body["latest_decision"]["decision_cycle_id"] == body["research"]["decision_cycle_id"]
    assert body["portfolio"]["portfolio_id"] == body["performance"]["managed_portfolio_id"]
    assert histories_before == (state.managed_history, state.benchmark_history, state.history_entries)


def test_injected_state_can_expose_absent_reviewer_and_approval_without_fake_values() -> None:
    state = _state()
    journal_without_reviewer = replace(state.latest_journal_entry, reviewer_result=None)
    state_without_optional_artifacts = replace(
        state,
        latest_journal_entry=journal_without_reviewer,
        latest_approval=None,
    )

    response = TestClient(create_app(state=state_without_optional_artifacts)).get("/decisions/latest")

    assert response.status_code == 200
    assert response.json()["reviewer"] is None
    assert response.json()["approval"] is None


def test_latest_approval_must_reference_the_exact_latest_journal_for_both_composed_routes() -> None:
    state = _state()
    mismatched_approval = state.history_entries[0].approval
    assert mismatched_approval is not None
    mismatched_state = replace(state, latest_approval=mismatched_approval)
    client = TestClient(create_app(state=mismatched_state))

    latest = client.get("/decisions/latest")
    dashboard = client.get("/dashboard")

    assert latest.status_code == dashboard.status_code == 503
    assert "exact latest journal entry" in latest.json()["detail"]
    assert "exact latest journal entry" in dashboard.json()["detail"]


def test_latest_decision_and_dashboard_share_the_same_matching_approval() -> None:
    client = TestClient(create_app(state=_state()))

    latest = client.get("/decisions/latest")
    dashboard = client.get("/dashboard")

    assert latest.status_code == dashboard.status_code == 200
    assert latest.json()["approval"] == dashboard.json()["latest_decision"]["approval"]
    assert latest.json()["decision_cycle_id"] == dashboard.json()["latest_decision"]["decision_cycle_id"]


def test_absent_latest_decision_and_research_are_explicit_404s_and_dashboard_is_partial() -> None:
    state_without_latest = replace(_state(), latest_journal_entry=None, latest_approval=None)
    client = TestClient(create_app(state=state_without_latest))

    latest = client.get("/decisions/latest")
    research = client.get("/research/latest")
    dashboard = client.get("/dashboard")

    assert latest.status_code == research.status_code == 404
    assert latest.json()["detail"]["code"] == "latest_resource_not_found"
    assert research.json()["detail"]["message"] == "no latest decision is available"
    assert dashboard.status_code == 200
    assert dashboard.json()["latest_decision"] is None
    assert dashboard.json()["research"] is None


def test_history_buy_execution_includes_execution_and_validation_lineage() -> None:
    response = _client().get("/decisions")

    assert response.status_code == 200
    buy_entry = response.json()["entries_newest_first"][1]
    execution = buy_entry["execution"]
    assert execution["executed_trade_id"] == "00000000-0000-0000-0000-000000000025"
    assert execution["validated_trade_id"] == "00000000-0000-0000-0000-000000000024"
    assert execution["security"]["ticker"] == "MSFT"
    assert execution["action"] == "BUY"
    assert execution["execution_price"] == "105"
    assert execution["quantity"] is not None
    assert execution["notional"] is not None
    assert execution["executed_at"].endswith("+00:00")


def test_injected_state_source_metadata_is_reported_without_demo_hardcoding() -> None:
    durable_state = replace(
        _state(),
        source_metadata=StateSourceMetadata(mode="sqlite-local", persisted=True, synthetic=False),
    )

    response = TestClient(create_app(state=durable_state)).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "state_mode": "sqlite-local",
        "persisted": True,
        "synthetic": False,
    }


def test_latest_timestamp_preserves_non_utc_offset_serialization() -> None:
    state = _state()
    offset_journal = replace(
        state.latest_journal_entry,
        journaled_at=state.latest_journal_entry.journaled_at.astimezone(timezone(-timedelta(hours=4))),
    )
    offset_state = replace(state, latest_journal_entry=offset_journal, latest_approval=None)

    response = TestClient(create_app(state=offset_state)).get("/decisions/latest")

    assert response.status_code == 200
    assert response.json()["journaled_at"].endswith("-04:00")


def test_structurally_incomplete_latest_state_does_not_silently_drop_an_approval() -> None:
    invalid_state = replace(_state(), latest_journal_entry=None)
    client = TestClient(create_app(state=invalid_state))

    assert client.get("/decisions/latest").status_code == 503
    assert client.get("/dashboard").status_code == 503


def test_domain_import_does_not_depend_on_fastapi() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "PYTHONPATH": str(repository_root / "src")}

    result = subprocess.run(
        [sys.executable, "-c", "import sys; import agentic_portfolio_lab.domain; assert 'fastapi' not in sys.modules"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr


def test_local_frontend_cors_allowlist_is_narrow_and_allows_command_post() -> None:
    client = _client()

    def preflight(origin: str, method: str) -> object:
        return client.options(
            "/dashboard",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": method,
            },
        )

    localhost = preflight("http://localhost:8001", "GET")
    loopback = preflight("http://127.0.0.1:8001", "GET")
    denied = client.options(
        "/dashboard",
        headers={
            "Origin": "http://malicious.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    unsupported_method = preflight("http://localhost:8001", "PUT")

    assert localhost.status_code == loopback.status_code == 200
    assert localhost.headers["access-control-allow-origin"] == "http://localhost:8001"
    assert loopback.headers["access-control-allow-origin"] == "http://127.0.0.1:8001"
    assert localhost.headers["access-control-allow-methods"] == "GET, POST"
    assert denied.status_code == 400
    assert unsupported_method.status_code == 400


def test_refresh_prices_command_returns_provider_metadata_and_includes_spy() -> None:
    client, refresh_state = _refresh_client(_RefreshProvider())
    response = client.post("/commands/refresh-prices")

    assert response.status_code == 200
    assert response.json() == {
        "refreshed_tickers": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "JPM", "V", "COST", "SPY"],
        "provider_identity": "fake-provider",
        "latest_source_timestamp": "2026-08-13T20:00:00+00:00",
        "price_convention": "fake-price",
    }
    assert refresh_state.latest_observations[-1].security.ticker == "SPY"


def test_refresh_prices_command_reports_provider_failure() -> None:
    client, refresh_state = _refresh_client(_RefreshProvider(MarketPriceError("provider unavailable")))
    response = client.post("/commands/refresh-prices")

    assert response.status_code == 502
    assert response.json()["detail"] == {"code": "market_price_unavailable", "message": "provider unavailable"}
    assert refresh_state.latest_observations == ()
