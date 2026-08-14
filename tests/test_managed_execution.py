from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agentic_portfolio_lab.api.app import create_app
from agentic_portfolio_lab.application.managed_execution import ManagedPaperExecutionError, ManagedPaperExecutionService
from agentic_portfolio_lab.domain.approval import ApprovalDecision, DecisionApproval
from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
from agentic_portfolio_lab.domain.recommendations import PortfolioRecommendation, RecommendationAction, RecommendationEvidenceReference, ReviewTrigger, ReviewTriggerType
from agentic_portfolio_lab.domain.risk_validation import DeterministicRiskValidator
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.domain.value_manager import ValueManagerDecisionContext
from agentic_portfolio_lab.domain.value_manager_workflow import ValueManagerDecisionResult
from agentic_portfolio_lab.dashboard_demo import _demo_research_batch
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore

UTC = timezone.utc


def _prepared_store(tmp_path):
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    base = store.initialize_run(initialized_at=datetime(2026, 8, 12, 14, tzinfo=UTC))
    cycle, produced = uuid4(), base.metadata.initialized_at + timedelta(minutes=1)
    batch = replace(_demo_research_batch(base.managed_portfolio, batch_id=f"batch-{cycle}", decision_cycle_id=cycle), created_at=base.metadata.initialized_at, as_of_timestamp=base.metadata.initialized_at)
    context = ValueManagerDecisionContext(base.managed_portfolio, batch, ConstitutionLoader.load_value_manager_constitution())
    evidence = next(item for packet in batch.packets for item in packet.evidence_items if item.evidence_id == "demo_ev_003")
    reference = RecommendationEvidenceReference(evidence.evidence_id, evidence.source_type, evidence.source_title, evidence.source_date, evidence.claim_supported)
    recommendation = PortfolioRecommendation(RecommendationAction.BUY, "MSFT", Decimal("0.2"), "rationale", "thesis", "valuation", ("risk",), 70, (reference,), "why", ("invalidate",), (ReviewTrigger(ReviewTriggerType.EVENT_BASED, "trigger"),))
    decision = ValueManagerDecisionResult(context, recommendation, produced)
    security = SecurityIdentity("MSFT", "EQUITY", "NASDAQ", "USD")
    validation_quote = PriceObservation(security, Decimal("100"), produced.date(), produced, "USD", "test-provider", "provider-quote-close")
    validation = DeterministicRiskValidator().validate(decision, validation_timestamp=produced, price_observation=validation_quote)
    journal = DecisionJournalEntry(decision, validation, produced)
    approval = DecisionApproval(journal, "human", ApprovalDecision.APPROVED, produced + timedelta(minutes=1))
    quote = PriceObservation(validation.validated_trade.security, Decimal("101"), produced.date(), approval.decided_at + timedelta(minutes=1), "USD", "test-provider", "provider-quote-close")
    store.save_transition(replace(base, research_batches=(batch,), journal_entries=(journal,), approvals=(approval,), price_observations=(validation_quote, quote)))
    return store, journal, approval, quote


def test_approved_buy_executes_with_latest_canonical_quote_and_survives_restart(tmp_path):
    store, journal, approval, quote = _prepared_store(tmp_path)
    result = ManagedPaperExecutionService(store).execute(decision_cycle_id=journal.decision_cycle_id, executed_at=quote.observed_at + timedelta(minutes=1))
    assert result.comparison_refreshed is False
    assert result.execution.execution_observation == quote
    assert result.execution.executed_trade.executed_quantity == Decimal("1.98019801")
    assert result.execution.updated_portfolio.cash_balance.amount == Decimal("800.00000099")
    reopened = store.open_run()
    assert reopened is not None and len(reopened.executions) == 1
    assert len(reopened.benchmark_history.snapshots) == 1
    assert reopened.executions[0].execution_observation == reopened.price_observations[-1]
    assert reopened.executions[0].executed_trade.validated_trade is reopened.journal_entries[0].risk_validation_result.validated_trade
    assert reopened.history_entries[0].executed_trade is reopened.executions[0].executed_trade
    client = TestClient(create_app(database_path=str(tmp_path / "run.sqlite")))
    assert client.get("/portfolio").status_code == 200
    assert client.get("/decisions/latest").json()["execution"]["executed_trade_id"] == str(reopened.executions[0].executed_trade.executed_trade_id)
    history = client.get("/decisions"); assert history.status_code == 200 and history.json()["entries_newest_first"][0]["execution"]["executed_trade_id"] == str(reopened.executions[0].executed_trade.executed_trade_id)
    dashboard = client.get("/dashboard"); assert dashboard.status_code == 200 and dashboard.json()["performance"] is None
    assert client.get("/performance").json() is None
    body = client.post(f"/commands/decisions/{journal.decision_cycle_id}/execute-paper-trade", params={"executed_at": (quote.observed_at + timedelta(minutes=2)).isoformat()})
    assert body.status_code == 422 and "already been executed" in body.json()["detail"]["message"]


def test_missing_approval_and_preapproval_quote_are_rejected_without_mutation(tmp_path):
    store, journal, approval, quote = _prepared_store(tmp_path)
    state = store.open_run(); assert state is not None
    class MissingApprovalStore:
        def open_run(self): return replace(state, approvals=())
        def save_transition(self, _): raise AssertionError("ineligible execution must not persist")
    with pytest.raises(ManagedPaperExecutionError, match="no matching approval"):
        ManagedPaperExecutionService(MissingApprovalStore()).execute(decision_cycle_id=journal.decision_cycle_id, executed_at=quote.observed_at + timedelta(minutes=1))
    assert store.open_run().executions == ()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda state, approval: replace(state, approvals=(replace(state.approvals[0], decision=ApprovalDecision.REJECTED),)), "requires an APPROVED approval"),
        (lambda state, approval: replace(state, price_observations=()), "no eligible persisted PriceObservation"),
    ],
)
def test_ineligible_execution_gates_leave_state_unwritten(tmp_path, change, message):
    store, journal, approval, quote = _prepared_store(tmp_path)
    state = store.open_run(); assert state is not None
    class IneligibleStore:
        def open_run(self): return change(state, approval)
        def save_transition(self, _): raise AssertionError("ineligible execution must not persist")
    with pytest.raises(ManagedPaperExecutionError, match=message):
        ManagedPaperExecutionService(IneligibleStore()).execute(decision_cycle_id=journal.decision_cycle_id, executed_at=quote.observed_at + timedelta(minutes=1))


def test_command_has_no_price_body_and_returns_execution_lineage(tmp_path):
    store, journal, approval, quote = _prepared_store(tmp_path)
    app = create_app(database_path=str(tmp_path / "run.sqlite"))
    assert "requestBody" not in app.openapi()["paths"]["/commands/decisions/{decision_cycle_id}/execute-paper-trade"]["post"]
    response = TestClient(app).post(f"/commands/decisions/{journal.decision_cycle_id}/execute-paper-trade", params={"executed_at": (quote.observed_at + timedelta(minutes=1)).isoformat()})
    assert response.status_code == 200
    assert response.json()["provider_identity"] == "test-provider"


def test_command_rejects_body_and_naive_execution_timestamp_without_mutation(tmp_path):
    store, journal, approval, quote = _prepared_store(tmp_path)
    client = TestClient(create_app(database_path=str(tmp_path / "run.sqlite")))
    url = f"/commands/decisions/{journal.decision_cycle_id}/execute-paper-trade"
    body = client.post(url, params={"executed_at": (quote.observed_at + timedelta(minutes=1)).isoformat()}, json={"price": "1"})
    assert body.status_code == 422 and body.json()["detail"]["code"] == "paper_execution_invalid"
    naive = client.post(url, params={"executed_at": "2026-08-12T14:04:00"})
    assert naive.status_code == 422 and "timezone-aware" in naive.json()["detail"]["message"]
    state = store.open_run(); assert state is not None and state.executions == ()


@pytest.mark.parametrize(
    ("action", "passed", "same_journal", "message"),
    [
        (RecommendationAction.HOLD, True, True, "requires a BUY recommendation"),
        (RecommendationAction.BUY, False, True, "requires passed deterministic validation"),
        (RecommendationAction.BUY, True, False, "does not reference the canonical journal"),
    ],
)
def test_early_eligibility_gates_reach_their_intended_error(action, passed, same_journal, message):
    cycle, portfolio_id = uuid4(), uuid4()
    validation = SimpleNamespace(passed=passed, validated_trade=None)
    journal = SimpleNamespace(decision_cycle_id=cycle, portfolio_id=portfolio_id, decision_result=SimpleNamespace(recommendation=SimpleNamespace(action=action)), risk_validation_result=validation)
    approval = SimpleNamespace(decision_cycle_id=cycle, journal_entry=journal if same_journal else object(), decision=ApprovalDecision.APPROVED)
    state = SimpleNamespace(journal_entries=(journal,), approvals=(approval,), executions=(), managed_portfolio=SimpleNamespace(portfolio_id=portfolio_id), price_observations=())
    class Store:
        def open_run(self): return state
    with pytest.raises(ManagedPaperExecutionError, match=message):
        ManagedPaperExecutionService(Store()).execute(decision_cycle_id=cycle, executed_at=datetime(2026,8,12,15,tzinfo=UTC))
