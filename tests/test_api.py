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
from agentic_portfolio_lab.application.local_state_codec import decode_run_state, encode
from agentic_portfolio_lab.application.market_configuration import CANDIDATE_UNIVERSE, SPY_BENCHMARK
from agentic_portfolio_lab.application.refresh_prices import InMemoryPriceRefreshState, RefreshPricesService
from agentic_portfolio_lab.application.wave2_commands import BenchmarkFulfillmentService
from agentic_portfolio_lab.domain.market_prices import MarketPriceError
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.api.queries import MvpQueryService, MvpReadStateSnapshot, StateSourceMetadata
from agentic_portfolio_lab.dashboard_demo import build_demo_dashboard_data
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore, SQLiteMvpReadState, SQLitePriceRefreshState
from datetime import date, datetime
from decimal import Decimal
from agentic_portfolio_lab.domain.price_refresh import PriceRefreshOperation, PriceRefreshOperationStatus
from agentic_portfolio_lab.domain.approval import ApprovalDecision, DecisionApproval
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
from agentic_portfolio_lab.domain.risk_validation import DeterministicRiskValidator
from uuid import uuid4


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


def test_workflow_checklist_is_ordered_deterministic_and_represents_hold() -> None:
    state = _state()
    first = MvpQueryService(state).workflow_checklist()
    second = MvpQueryService(state).workflow_checklist()

    assert first == second
    assert [step.step_id for step in first.steps] == [
        "price_refresh", "spy_benchmark", "research",
        "value_manager_decision_validation", "ai_reviewer", "human_approval", "paper_execution",
    ]
    decision, reviewer, approval, execution = first.steps[3:]
    assert (decision.status, decision.reason_code, decision.terminal) == ("PASSED", "HOLD", True)
    assert reviewer.artifact is None
    assert approval.status == "APPROVED"
    assert (execution.reason_code, execution.terminal, execution.available_action) == ("HOLD", True, None)


def test_workflow_checklist_uses_durable_refresh_artifact_without_a_reporting_clock() -> None:
    state = _state()
    started = datetime(2026, 8, 14, 14, 0, tzinfo=timezone.utc)
    operation = PriceRefreshOperation(
        operation_id=uuid4(), status=PriceRefreshOperationStatus.FAILED,
        started_at=started, completed_at=started + timedelta(minutes=1),
        provider_identity="test-provider", expected_security_count=31,
        failure_code="provider_unavailable", failure_message="offline",
    )
    projection = MvpQueryService(replace(state, latest_price_refresh_operation=operation)).workflow_checklist()

    refresh = projection.steps[0]
    assert (refresh.status, refresh.reason_code, refresh.completed, refresh.terminal) == (
        "FAILED", "provider_unavailable", False, False,
    )
    assert refresh.artifact is not None
    assert refresh.artifact.occurred_at == operation.completed_at.isoformat()


def test_workflow_checklist_refresh_states_have_explicit_operator_semantics() -> None:
    state = _state()
    started = datetime(2026, 8, 14, 14, 0, tzinfo=timezone.utc)
    cases = (
        (PriceRefreshOperation(uuid4(), PriceRefreshOperationStatus.IN_PROGRESS, started, "test-provider", 31),
         ("IN_PROGRESS", None, False, False)),
        (PriceRefreshOperation(uuid4(), PriceRefreshOperationStatus.COMPLETED, started, "test-provider", 31,
                               started + timedelta(minutes=1), 31, started + timedelta(minutes=1)),
         ("COMPLETED", None, True, False)),
    )
    for operation, expected in cases:
        step = MvpQueryService(replace(state, latest_price_refresh_operation=operation)).workflow_checklist().steps[0]
        assert (step.status, step.reason_code, step.completed, step.terminal) == expected
        assert step.artifact is not None


def test_workflow_checklist_selects_standalone_research_or_legacy_journal_lineage() -> None:
    state = _state()
    legacy = MvpQueryService(state).workflow_checklist().steps[2]
    journal_batch = state.latest_journal_entry.decision_result.context.research_batch
    standalone = replace(journal_batch, batch_id="standalone-batch", created_at=journal_batch.created_at + timedelta(minutes=1))
    selected = MvpQueryService(replace(state, research_batches=(standalone,))).workflow_checklist().steps[2]

    assert legacy.artifact is not None and legacy.artifact.artifact_id == journal_batch.batch_id
    assert selected.artifact is not None and selected.artifact.artifact_id == standalone.batch_id


def test_workflow_checklist_projects_every_durable_benchmark_outcome_and_artifact(tmp_path: Path) -> None:
    started = datetime(2026, 8, 14, 14, 0, tzinfo=timezone.utc)
    store = SQLiteLocalRunStore(tmp_path / "benchmark.sqlite")
    initial = store.initialize_run(initialized_at=started)
    pending = MvpQueryService(SQLiteMvpReadState(store)).workflow_checklist().steps[1]
    assert (pending.status, pending.completed, pending.terminal, pending.artifact) == (
        "PENDING_NO_ELIGIBLE_PRICE", False, False, None,
    )

    quote_at = started + timedelta(minutes=1)
    quote = PriceObservation(initial.benchmark_portfolio.benchmark_security, Decimal("500"), quote_at.date(), quote_at,
                             "USD", "test-provider", "test-quote")
    SQLitePriceRefreshState(store).apply_price_refresh((quote,))
    assert BenchmarkFulfillmentService(store).fulfill(fulfilled_at=quote_at).status.value == "FULFILLED"
    fulfilled = MvpQueryService(SQLiteMvpReadState(store)).workflow_checklist().steps[1]
    assert (fulfilled.status, fulfilled.completed, fulfilled.terminal) == ("FULFILLED", True, False)
    assert fulfilled.artifact is not None and fulfilled.artifact.artifact_type == "benchmark_fulfillment"

    assert BenchmarkFulfillmentService(store).fulfill(fulfilled_at=quote_at + timedelta(minutes=1)).status.value == "NO_ACTION_ZERO_CASH"
    zero_cash = MvpQueryService(SQLiteMvpReadState(store)).workflow_checklist().steps[1]
    assert (zero_cash.status, zero_cash.completed, zero_cash.terminal) == ("NO_ACTION_ZERO_CASH", True, False)
    assert zero_cash.artifact is not None and zero_cash.artifact.artifact_id == fulfilled.artifact.artifact_id

    insufficient_store = SQLiteLocalRunStore(tmp_path / "insufficient.sqlite")
    insufficient_initial = insufficient_store.initialize_run(initialized_at=started)
    expensive = PriceObservation(insufficient_initial.benchmark_portfolio.benchmark_security, Decimal("1000000000000"), quote_at.date(), quote_at,
                                 "USD", "test-provider", "test-quote")
    SQLitePriceRefreshState(insufficient_store).apply_price_refresh((expensive,))
    assert BenchmarkFulfillmentService(insufficient_store).fulfill(fulfilled_at=quote_at).status.value == "NO_ACTION_INSUFFICIENT_BUYING_POWER"
    insufficient = MvpQueryService(SQLiteMvpReadState(insufficient_store)).workflow_checklist().steps[1]
    assert (insufficient.status, insufficient.completed, insufficient.terminal, insufficient.artifact) == (
        "NO_ACTION_INSUFFICIENT_BUYING_POWER", True, False, None,
    )


def test_workflow_checklist_covers_failed_buy_reviewer_and_rejected_approval() -> None:
    state = _state()
    buy_journal = state.history_entries[0].journal_entry
    failed = DecisionJournalEntry(
        buy_journal.decision_result,
        DeterministicRiskValidator().validate(
            buy_journal.decision_result, validation_timestamp=state.latest_journal_entry.journaled_at,
        ),
        state.latest_journal_entry.journaled_at,
    )
    failed_steps = MvpQueryService(replace(state, latest_journal_entry=failed, latest_approval=None)).workflow_checklist().steps
    assert (failed_steps[3].status, failed_steps[3].terminal) == ("FAILED", True)
    assert (failed_steps[6].reason_code, failed_steps[6].terminal) == ("VALIDATION_FAILED", True)

    reviewer = state.latest_journal_entry.reviewer_result
    rejected = DecisionApproval(buy_journal, "operator", ApprovalDecision.REJECTED, buy_journal.journaled_at + timedelta(minutes=1))
    reviewed_steps = MvpQueryService(replace(
        state,
        latest_journal_entry=buy_journal,
        latest_approval=rejected,
        history_entries=tuple(item for item in state.history_entries if item.journal_entry is not buy_journal),
    )).workflow_checklist().steps

    reviewer_steps = MvpQueryService(replace(state, reviewer_results=(reviewer,))).workflow_checklist().steps
    assert reviewer_steps[4].status == reviewer.decision.value
    assert reviewer_steps[4].artifact is not None
    assert (reviewed_steps[5].status, reviewed_steps[5].terminal) == ("REJECTED", True)
    assert (reviewed_steps[6].reason_code, reviewed_steps[6].terminal) == ("REJECTED", True)


def test_workflow_checklist_empty_durable_run_survives_sqlite_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "checklist.sqlite"
    initialized_at = datetime(2026, 8, 13, 14, 30, tzinfo=timezone.utc)
    SQLiteLocalRunStore(database_path).initialize_run(initialized_at=initialized_at)

    before = MvpQueryService(SQLiteMvpReadState(SQLiteLocalRunStore(database_path))).workflow_checklist()
    after = MvpQueryService(SQLiteMvpReadState(SQLiteLocalRunStore(database_path))).workflow_checklist()

    assert before == after
    assert before.steps[2].artifact is None
    assert before.steps[3].artifact is None
    assert before.steps[6].available_action is None


def test_workflow_checklist_reconstructs_a_legacy_persisted_run_without_newer_artifacts() -> None:
    legacy_document = encode(SQLiteLocalRunStore._initial_state(datetime(2026, 8, 13, 14, 30, tzinfo=timezone.utc)))
    for field_name in (
        "latest_price_refresh_operation", "reviewer_results", "execution_checks",
        "benchmark_fulfillments", "screening_runs", "fundamental_records",
        "benchmark_fulfillment_status",
    ):
        legacy_document["fields"].pop(field_name, None)
    state = decode_run_state(legacy_document)
    snapshot = MvpReadStateSnapshot(
        managed_history=state.managed_history,
        benchmark_history=state.benchmark_history,
        comparison=None,
        latest_journal_entry=state.latest_journal_entry,
        latest_approval=state.latest_approval,
        history_entries=state.history_entries,
        source_metadata=StateSourceMetadata(mode="legacy-persisted", persisted=True, synthetic=False),
        research_batches=state.research_batches,
        screening_runs=state.screening_runs,
        benchmark_fulfillments=state.benchmark_fulfillments,
        benchmark_fulfillment_status=state.benchmark_fulfillment_status,
        price_observations=state.price_observations,
        latest_price_refresh_operation=state.latest_price_refresh_operation,
        reviewer_results=state.reviewer_results,
        run_id=state.metadata.run_id,
        run_status=state.metadata.status,
        run_initialized_at=state.metadata.initialized_at,
    )

    checklist = MvpQueryService(snapshot).workflow_checklist()

    assert state.latest_price_refresh_operation is None
    assert state.reviewer_results == ()
    assert state.execution_checks == ()
    assert (checklist.steps[0].status, checklist.steps[1].status) == (None, "PENDING_NO_ELIGIBLE_PRICE")


def test_weekly_run_readiness_endpoint_is_schema_validated_read_only_and_represents_terminal_hold() -> None:
    state = _state()
    before = (state.managed_history, state.benchmark_history, state.history_entries, state.price_observations)

    response = TestClient(create_app(state=state)).get("/weekly-run/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["current_run"] is None
    assert [step["step_id"] for step in body["steps"]] == [
        "price_refresh", "spy_benchmark", "research",
        "value_manager_decision_validation", "ai_reviewer", "human_approval", "paper_execution",
    ]
    assert body["next_action"] is None
    assert body["blockers"] == [{
        "step_id": "paper_execution", "reason_code": "HOLD", "artifact": None,
    }]
    assert before == (state.managed_history, state.benchmark_history, state.history_entries, state.price_observations)


def test_health_endpoint_describes_the_explicit_demo_state() -> None:
    response = _client().get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "state_mode": "synthetic-in-memory",
        "persisted": False,
        "synthetic": True,
    }


def test_cash_event_command_serializes_the_persisted_funding_graph_once(tmp_path: Path) -> None:
    database_path = tmp_path / "local-run.sqlite"
    initialized_at = datetime(2026, 8, 13, 14, 30, tzinfo=timezone.utc)
    initial = SQLiteLocalRunStore(database_path).initialize_run(initialized_at=initialized_at)
    effective_at = initialized_at + timedelta(minutes=1)
    client = TestClient(create_app(database_path=str(database_path)))

    response = client.post(
        "/commands/cash-events",
        json={
            "amount": "1000",
            "currency": "USD",
            "source": "weekly deposit",
            "effective_at": effective_at.isoformat(),
        },
    )

    assert response.status_code == 200
    persisted = SQLiteLocalRunStore(database_path).open_run()
    assert persisted is not None
    assert len(persisted.funding_results) == len(initial.funding_results) + 1
    submitted = tuple(
        item for item in persisted.funding_results
        if item.cash_event.amount == Decimal("1000")
        and item.cash_event.effective_at == effective_at
        and item.cash_event.source == "weekly deposit"
    )
    assert len(submitted) == 1
    funding = submitted[0]
    assert response.json() == {
        "event_id": str(funding.cash_event.event_id),
        "managed_cash": format(funding.funded_managed_portfolio.cash_balance.amount, "f"),
        "benchmark_cash": format(funding.funded_benchmark_portfolio.portfolio.cash_balance.amount, "f"),
        "currency": funding.cash_event.currency,
        "effective_at": funding.cash_event.effective_at.isoformat(),
    }
    assert funding.cash_event.effective_at == effective_at
    assert funding.funded_managed_portfolio.cash_balance.amount == initial.managed_portfolio.cash_balance.amount + Decimal("1000")
    assert funding.funded_benchmark_portfolio.portfolio.cash_balance.amount == initial.benchmark_portfolio.portfolio.cash_balance.amount + Decimal("1000")
    # Response projection is read-only; it cannot append another funding result.
    assert len(SQLiteLocalRunStore(database_path).open_run().funding_results) == len(initial.funding_results) + 1


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
    assert research_body["screening_run_id"] is None
    assert research_body["selected"] == []
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
    body = response.json()
    assert body == {
        "refreshed_tickers": [observation.security.ticker for observation in refresh_state.latest_observations],
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
