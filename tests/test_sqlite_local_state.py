"""Focused persistence checks for the single-user local SQLite run."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from agentic_portfolio_lab.api.app import create_app
from agentic_portfolio_lab.application.local_state_codec import decode_run_state, encode
from agentic_portfolio_lab.domain.approval import ApprovalDecision, DecisionApproval
from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
from agentic_portfolio_lab.domain.recommendations import PortfolioRecommendation, RecommendationAction, RecommendationEvidenceReference, ReviewTrigger, ReviewTriggerType
from agentic_portfolio_lab.domain.risk_validation import DeterministicRiskValidator
from agentic_portfolio_lab.domain.simulated_execution import SimulatedExecutionWorkflow
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.valuation import BenchmarkPortfolio, PortfolioValuation, PriceObservation
from agentic_portfolio_lab.domain.value_manager import ValueManagerDecisionContext
from agentic_portfolio_lab.domain.value_manager_workflow import ValueManagerDecisionResult
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SCHEMA_VERSION, SQLiteLocalRunStore


UTC = timezone.utc
INITIALIZED_AT = datetime(2026, 8, 12, 14, 30, tzinfo=UTC)


def _store(tmp_path: Path) -> SQLiteLocalRunStore:
    return SQLiteLocalRunStore(tmp_path / "local-run.sqlite")


def _executed_state(base_state):
    """A complete BUY graph whose canonical execution can survive reopening."""
    from agentic_portfolio_lab.application.local_state import PersistedRunState
    from agentic_portfolio_lab.dashboard import DecisionHistoryArtifacts

    from agentic_portfolio_lab.dashboard_demo import _demo_research_batch

    original = base_state.managed_portfolio
    decision_cycle_id = uuid4()
    research_batch = replace(
        _demo_research_batch(original, batch_id=f"local-batch-{decision_cycle_id}", decision_cycle_id=decision_cycle_id),
        created_at=base_state.metadata.initialized_at,
        as_of_timestamp=base_state.metadata.initialized_at,
    )
    context = ValueManagerDecisionContext(original, research_batch, ConstitutionLoader.load_value_manager_constitution())
    recommendation = PortfolioRecommendation(
        action=RecommendationAction.BUY,
        ticker="MSFT",
        target_weight=Decimal("0.20"),
        decision_rationale="Persistence test BUY.",
        investment_thesis="Test thesis.",
        valuation="Test valuation.",
        risks=("Test risk.",),
        confidence_score=72,
        evidence=(RecommendationEvidenceReference("demo_ev_003", "FILING", "Microsoft Quarterly Report", base_state.metadata.initialized_at.date() - timedelta(days=2), "Microsoft reported enterprise software and cloud operating context."),),
        why_not_spy="Test candidate-specific evidence.",
        thesis_invalidation=("Test invalidation.",),
        review_triggers=(ReviewTrigger(ReviewTriggerType.EVENT_BASED, "Test trigger."),),
    )
    produced_at = base_state.metadata.initialized_at + timedelta(minutes=1)
    decision_result = ValueManagerDecisionResult(context, recommendation, produced_at)
    validation_observation = PriceObservation(
        security=SecurityIdentity("MSFT", "EQUITY", "NASDAQ", "USD"),
        observed_price=Decimal("100"), market_date=produced_at.date(), observed_at=produced_at,
        currency="USD", source_provider_identity="demo-provider", price_convention="regular-session-close",
    )
    validation = DeterministicRiskValidator().validate(decision_result, validation_timestamp=produced_at, price_observation=validation_observation)
    journal = DecisionJournalEntry(decision_result, validation, produced_at)
    approval = DecisionApproval(journal, "local-human", ApprovalDecision.APPROVED, produced_at + timedelta(minutes=1))
    executed_at = approval.decided_at + timedelta(minutes=1)
    observation = PriceObservation(
        security=validation.validated_trade.security,
        observed_price=Decimal("100"),
        market_date=executed_at.date(),
        observed_at=executed_at,
        currency="USD",
        source_provider_identity="demo-provider",
        price_convention="regular-session-close",
    )
    execution = SimulatedExecutionWorkflow.execute(approval, original, observation, executed_at=executed_at)
    managed_history = base_state.managed_history
    managed_valuation = PortfolioValuation.from_portfolio(
        execution.updated_portfolio,
        (
            observation,
        ),
        as_of_timestamp=executed_at,
        market_date=executed_at.date(),
        source_price_timestamp=executed_at,
        source_provider_identity="demo-provider",
        price_convention="regular-session-close",
    )
    managed_history = managed_history.append(execution.updated_portfolio, managed_valuation)
    benchmark = base_state.benchmark_portfolio
    benchmark_history = base_state.benchmark_history
    benchmark_valuation = PortfolioValuation.from_benchmark(
        benchmark,
        (),
        as_of_timestamp=executed_at,
        market_date=executed_at.date(),
        source_price_timestamp=executed_at,
        source_provider_identity="demo-provider",
        price_convention="regular-session-close",
    )
    benchmark_history = benchmark_history.append(benchmark, benchmark_valuation)
    return PersistedRunState(
        metadata=base_state.metadata,
        managed_portfolio=execution.updated_portfolio,
        benchmark_portfolio=benchmark,
        managed_history=managed_history,
        benchmark_history=benchmark_history,
        funding_results=base_state.funding_results,
        price_observations=(validation_observation, observation),
        research_batches=(research_batch,),
        journal_entries=(journal,),
        approvals=(approval,),
        executions=(execution,),
        history_entries=(DecisionHistoryArtifacts(journal, approval, execution.executed_trade),),
    )


def _raw_replace(state, **changes):
    """Bypass dataclass construction only to prove save_transition revalidates."""
    raw = object.__new__(type(state))
    for field in fields(type(state)):
        object.__setattr__(raw, field.name, changes.get(field.name, getattr(state, field.name)))
    return raw


def test_initialize_creates_real_paired_funding_baseline(tmp_path: Path) -> None:
    state = _store(tmp_path).initialize_run(initialized_at=INITIALIZED_AT)

    assert state.managed_portfolio.cash_balance.amount == Decimal("1000")
    assert state.benchmark_portfolio.portfolio.cash_balance.amount == Decimal("1000")
    assert not state.managed_portfolio.positions
    assert not state.benchmark_portfolio.portfolio.positions
    assert len(state.funding_results) == 1
    assert state.funding_results[0].cash_event.amount == Decimal("1000")
    assert state.managed_history.snapshots[0].portfolio is state.managed_portfolio
    assert state.benchmark_history.snapshots[0].portfolio == state.benchmark_portfolio.portfolio


def test_open_reconstructs_portfolios_history_and_exact_scalar_values(tmp_path: Path) -> None:
    store = _store(tmp_path)
    created = store.initialize_run(initialized_at=INITIALIZED_AT)
    reopened = store.open_run()

    assert reopened is not None
    assert reopened.managed_portfolio == created.managed_portfolio
    assert reopened.benchmark_portfolio == created.benchmark_portfolio
    assert reopened.managed_history == created.managed_history
    assert reopened.managed_portfolio.portfolio_id == created.managed_portfolio.portfolio_id
    assert reopened.funding_results[0].cash_event.event_id == created.funding_results[0].cash_event.event_id
    assert reopened.metadata.initialized_at == INITIALIZED_AT
    assert reopened.managed_portfolio.cash_balance.amount == Decimal("1000")


def test_codec_round_trips_complete_execution_graph_with_canonical_lineage() -> None:
    base_state = SQLiteLocalRunStore._initial_state(INITIALIZED_AT)
    state = _executed_state(base_state)
    decoded = decode_run_state(encode(state))

    assert decoded.managed_history == state.managed_history
    journal = decoded.journal_entries[0]
    execution = decoded.executions[0]
    assert decoded.approvals[0].journal_entry is journal
    assert execution.approval is decoded.approvals[0]
    assert execution.executed_trade.validated_trade is journal.risk_validation_result.validated_trade
    assert decoded.history_entries[0].journal_entry is journal
    assert decoded.history_entries[0].executed_trade is execution.executed_trade


def test_save_reopen_preserves_historical_buy_execution_without_data_loss(tmp_path: Path) -> None:
    store = _store(tmp_path)
    initialized = store.initialize_run(initialized_at=INITIALIZED_AT)
    state = _executed_state(initialized)
    store.save_transition(state)

    reopened = store.open_run()
    assert reopened is not None
    assert reopened.executions[0].executed_trade.executed_trade_id == state.executions[0].executed_trade.executed_trade_id
    assert reopened.history_entries[0].executed_trade is reopened.executions[0].executed_trade


def test_history_execution_without_persisted_execution_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    initialized = store.initialize_run(initialized_at=INITIALIZED_AT)
    state = _executed_state(initialized)
    invalid = _raw_replace(state, executions=())

    with pytest.raises(ValueError, match="history execution requires a canonical persisted execution artifact"):
        store.save_transition(invalid)
    assert store.open_run() == initialized


def test_execution_without_history_is_rejected_before_persistence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    initialized = store.initialize_run(initialized_at=INITIALIZED_AT)
    state = _executed_state(initialized)

    with pytest.raises(ValueError, match="every persisted execution must appear in one canonical history entry"):
        store.save_transition(_raw_replace(state, history_entries=()))

    assert store.open_run() == initialized


def test_one_execution_has_exactly_one_canonical_history_entry(tmp_path: Path) -> None:
    store = _store(tmp_path)
    state = _executed_state(store.initialize_run(initialized_at=INITIALIZED_AT))
    store.save_transition(state)

    reopened = store.open_run()
    assert reopened is not None
    assert len(reopened.executions) == len(reopened.history_entries) == 1
    assert reopened.history_entries[0].executed_trade is reopened.executions[0].executed_trade


def test_removing_initial_funding_provenance_is_rejected_and_rolls_back(tmp_path: Path) -> None:
    store = _store(tmp_path)
    initialized = store.initialize_run(initialized_at=INITIALIZED_AT)

    with pytest.raises(ValueError, match="funding results must not remove persisted artifact"):
        store.save_transition(_raw_replace(initialized, funding_results=()))

    assert store.open_run() == initialized


@pytest.mark.parametrize(
    ("field_name", "message"),
    (
        ("price_observations", "price observations must not remove persisted artifact"),
        ("research_batches", "research batches must not remove persisted artifact"),
        ("journal_entries", "approval must reference an exact canonical persisted journal"),
        ("approvals", "execution must belong to a canonical persisted journal and approval"),
        ("executions", "history execution requires a canonical persisted execution artifact"),
        ("history_entries", "every persisted execution must appear in one canonical history entry"),
    ),
)
def test_removing_persisted_audit_artifact_is_rejected_and_rolls_back(
    tmp_path: Path, field_name: str, message: str
) -> None:
    store = _store(tmp_path)
    state = _executed_state(store.initialize_run(initialized_at=INITIALIZED_AT))
    store.save_transition(state)

    with pytest.raises(ValueError, match=message):
        store.save_transition(_raw_replace(state, **{field_name: ()}))

    assert store.open_run() == state


def test_performance_history_truncation_is_rejected_and_rolls_back(tmp_path: Path) -> None:
    store = _store(tmp_path)
    state = _executed_state(store.initialize_run(initialized_at=INITIALIZED_AT))
    store.save_transition(state)
    managed_history = _raw_history_with_snapshots(state.managed_history, state.managed_history.snapshots[:1])
    benchmark_history = _raw_history_with_snapshots(state.benchmark_history, state.benchmark_history.snapshots[:1])
    truncated = _raw_replace(
        state,
        managed_portfolio=managed_history.snapshots[-1].portfolio,
        benchmark_portfolio=replace(state.benchmark_portfolio, portfolio=benchmark_history.snapshots[-1].portfolio),
        managed_history=managed_history,
        benchmark_history=benchmark_history,
    )

    with pytest.raises(ValueError, match="managed performance history must preserve the persisted prefix"):
        store.save_transition(truncated)

    assert store.open_run() == state


def test_performance_history_reordering_is_rejected_and_rolls_back(tmp_path: Path) -> None:
    store = _store(tmp_path)
    state = _executed_state(store.initialize_run(initialized_at=INITIALIZED_AT))
    store.save_transition(state)
    reordered_history = _raw_history_with_snapshots(state.managed_history, tuple(reversed(state.managed_history.snapshots)))
    reordered = _raw_replace(
        state,
        managed_portfolio=reordered_history.snapshots[-1].portfolio,
        managed_history=reordered_history,
    )

    with pytest.raises(ValueError, match="managed performance history must preserve the persisted prefix"):
        store.save_transition(reordered)

    assert store.open_run() == state


def test_valid_append_only_transition_succeeds(tmp_path: Path) -> None:
    store = _store(tmp_path)
    initial = store.initialize_run(initialized_at=INITIALIZED_AT)
    state = _executed_state(initial)

    store.save_transition(state)
    assert store.open_run() == state


def test_stale_writer_revalidates_against_winner_inside_write_transaction(tmp_path: Path) -> None:
    database_path = tmp_path / "local-run.sqlite"
    writer_a = SQLiteLocalRunStore(database_path)
    writer_b = SQLiteLocalRunStore(database_path)
    initial = writer_a.initialize_run(initialized_at=INITIALIZED_AT)

    # Both writers observe the same initial run. B then appends immutable
    # artifacts before A submits its now-stale otherwise-valid transition.
    stale_transition_a = replace(initial, metadata=replace(initial.metadata, status="A_PENDING"))
    winner_transition_b = _executed_state(writer_b.open_run())
    writer_b.save_transition(winner_transition_b)

    with pytest.raises(ValueError, match="managed performance history must preserve the persisted prefix"):
        writer_a.save_transition(stale_transition_a)

    reopened = writer_a.open_run()
    assert reopened is not None
    assert reopened.executions[0].executed_trade.executed_trade_id == winner_transition_b.executions[0].executed_trade.executed_trade_id
    assert reopened.history_entries[0].executed_trade is reopened.executions[0].executed_trade


def test_same_immutable_price_identity_must_not_be_rewritten(tmp_path: Path) -> None:
    store = _store(tmp_path)
    state = _executed_state(store.initialize_run(initialized_at=INITIALIZED_AT))
    store.save_transition(state)

    unchanged = store.open_run()
    assert unchanged is not None
    store.save_transition(unchanged)  # Resupplying an equal immutable record is valid.

    original_observation = state.price_observations[0]
    rewritten = replace(
        state,
        price_observations=(
            replace(original_observation, observed_price=Decimal("101")),
            *state.price_observations[1:],
        ),
    )
    with pytest.raises(ValueError, match="price observations must not rewrite persisted artifact"):
        store.save_transition(rewritten)

    assert store.open_run() == state


def test_duplicate_history_decision_cycle_is_rejected_before_persistence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    state = _executed_state(store.initialize_run(initialized_at=INITIALIZED_AT))
    duplicate = _raw_replace(state, history_entries=(state.history_entries[0], state.history_entries[0]))

    with pytest.raises(ValueError, match="history_entries must not contain duplicate decision cycles"):
        store.save_transition(duplicate)


def _raw_history_with_snapshots(history, snapshots):
    raw = object.__new__(type(history))
    for field in fields(type(history)):
        object.__setattr__(raw, field.name, snapshots if field.name == "snapshots" else getattr(history, field.name))
    return raw


def test_failed_transition_rolls_back_to_prior_durable_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path)
    original = store.initialize_run(initialized_at=INITIALIZED_AT)
    replacement = replace(original, metadata=replace(original.metadata, status="CHANGED"))

    def fail(*_args: object) -> None:
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(store, "_replace_index_rows", fail)
    with pytest.raises(RuntimeError, match="simulated write failure"):
        store.save_transition(replacement)

    assert store.open_run() == original


def test_stable_run_identity_is_required_for_transitions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = store.initialize_run(initialized_at=INITIALIZED_AT)

    with pytest.raises(ValueError, match="must not change run_id"):
        store.save_transition(replace(original, metadata=replace(original.metadata, run_id=UUID("00000000-0000-0000-0000-000000000055"))))
    with pytest.raises(ValueError, match="must not change initialized_at"):
        store.save_transition(replace(original, metadata=replace(original.metadata, initialized_at=INITIALIZED_AT + timedelta(minutes=1))))

    changed = replace(original, metadata=replace(original.metadata, status="PAUSED"))
    store.save_transition(changed)
    assert store.open_run() == changed


def test_invalid_aggregate_validation_rolls_back_before_persistence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = store.initialize_run(initialized_at=INITIALIZED_AT)
    # Construct a bypassed aggregate only to prove save_transition validates it
    # before writing; normal construction already rejects this mismatch.
    invalid = object.__new__(type(original))
    for name in (
        "metadata", "managed_portfolio", "benchmark_portfolio", "managed_history", "benchmark_history",
        "funding_results", "price_observations", "research_batches", "journal_entries", "approvals", "executions", "history_entries",
    ):
        object.__setattr__(invalid, name, getattr(original, name))
    object.__setattr__(invalid, "managed_portfolio", original.benchmark_portfolio.portfolio)

    with pytest.raises(ValueError, match="current managed portfolio must match"):
        store.save_transition(invalid)
    assert store.open_run() == original


def test_schema_version_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.initialize_run(initialized_at=INITIALIZED_AT)
    with store._connect() as connection:
        connection.execute("UPDATE run_metadata SET schema_version = ?", (SCHEMA_VERSION + 1,))
    with pytest.raises(ValueError, match="unsupported local SQLite schema version"):
        store.open_run()


def test_sqlite_state_is_usable_by_existing_fastapi_queries(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.initialize_run(initialized_at=INITIALIZED_AT)
    client = TestClient(create_app(database_path=str(tmp_path / "local-run.sqlite")))

    health = client.get("/health")
    dashboard = client.get("/dashboard")

    assert health.json() == {
        "status": "ok",
        "state_mode": "local-sqlite",
        "persisted": True,
        "synthetic": False,
    }
    assert dashboard.status_code == 200
    assert dashboard.json()["portfolio"]["cash_value"] == "1000"
    assert dashboard.json()["benchmark"]["snapshot"]["cash_value"] == "1000"
    assert dashboard.json()["latest_decision"] is None


def test_reopen_uses_same_database_not_demo_state(tmp_path: Path) -> None:
    path = tmp_path / "local-run.sqlite"
    SQLiteLocalRunStore(path).initialize_run(initialized_at=INITIALIZED_AT)
    reopened = SQLiteLocalRunStore(path).open_run()

    assert reopened is not None
    assert reopened.metadata.initialized_at + timedelta(days=1) == INITIALIZED_AT + timedelta(days=1)
    assert reopened.metadata.status == "ACTIVE"
