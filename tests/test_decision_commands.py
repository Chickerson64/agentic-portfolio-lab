"""Focused durable tests for the managed decision and human-outcome commands."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agentic_portfolio_lab.application.decision_commands import (
    DecisionApprovalService,
    DecisionCommandConflict,
    RunValueManagerService,
    _eligible_buy_observation,
)
from agentic_portfolio_lab.api.app import create_app
from agentic_portfolio_lab.api.models import decision_memo_response
from agentic_portfolio_lab.dashboard_demo import _demo_research_batch
from agentic_portfolio_lab.dashboard_demo import build_demo_dashboard_data
from agentic_portfolio_lab.domain.approval import ApprovalDecision, DecisionApproval
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.recommendations import (
    PortfolioRecommendation,
    RecommendationEvidenceReference,
    ReviewTrigger,
)
from agentic_portfolio_lab.domain.risk_validation import DeterministicRiskValidator
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore


UTC = timezone.utc
START = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)


class _Manager:
    def __init__(self, action: str = "BUY", error: Exception | None = None) -> None:
        self.action, self.error, self.calls = action, error, 0

    def decide(self, context):
        self.calls += 1
        if self.error:
            raise self.error
        evidence = context.research_batch.packets[0].evidence_items[0]
        return PortfolioRecommendation(
            action=self.action,
            ticker=context.research_batch.packets[0].ticker if self.action == "BUY" else None,
            target_weight=Decimal("0.25") if self.action == "BUY" else None,
            decision_rationale="Structured test recommendation.",
            investment_thesis="A test thesis." if self.action == "BUY" else None,
            valuation="Test valuation.",
            risks=("Test risk.",),
            confidence_score=70,
            evidence=(RecommendationEvidenceReference(evidence.evidence_id, evidence.source_type, evidence.source_title, evidence.source_date, evidence.claim_supported),),
            why_not_spy="Test-specific evidence.",
            thesis_invalidation=("Test invalidation.",) if self.action == "BUY" else (),
            review_triggers=(ReviewTrigger("EVENT_BASED", "Test trigger."),),
        )


def _prepared_store(tmp_path, *, include_price: bool = True):
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    state = store.initialize_run(initialized_at=START)
    batch = replace(
        _demo_research_batch(state.managed_portfolio, batch_id="decision-batch"),
        created_at=START + timedelta(minutes=1),
        as_of_timestamp=START + timedelta(minutes=1),
    )
    packet = batch.packets[0]
    price = PriceObservation(
        security=SecurityIdentity(packet.ticker, packet.security_type, packet.exchange, packet.currency),
        observed_price=Decimal("100"), market_date=START.date(), observed_at=START + timedelta(minutes=2),
        currency="USD", source_provider_identity="fake", price_convention="fake-quote",
    )
    store.save_transition(replace(state, research_batches=(batch,), price_observations=(price,) if include_price else ()))
    return store, batch, price


def test_buy_reuses_batch_cycle_persists_null_reviewer_and_approval_survives_restart(tmp_path) -> None:
    store, batch, _ = _prepared_store(tmp_path)
    journal = RunValueManagerService(store, manager=_Manager()).run(occurred_at=START + timedelta(minutes=3)).journal_entry
    assert journal.decision_cycle_id == batch.decision_cycle_id
    assert journal.decision_result.context.research_batch == batch
    assert journal.reviewer_result is None
    approval = DecisionApprovalService(store).decide(
        decision_cycle_id=batch.decision_cycle_id, decision=ApprovalDecision.APPROVED,
        decision_maker_id="local-operator", decided_at=START + timedelta(minutes=4),
    )
    reopened = SQLiteLocalRunStore(tmp_path / "run.sqlite").open_run()
    assert reopened is not None
    assert reopened.approvals[0].journal_entry is reopened.journal_entries[0]
    assert reopened.history_entries[0].approval is reopened.approvals[0]
    assert approval.decision_cycle_id == batch.decision_cycle_id


def test_hold_is_journaled_and_can_be_rejected_without_execution(tmp_path) -> None:
    store, batch, _ = _prepared_store(tmp_path)
    journal = RunValueManagerService(store, manager=_Manager("HOLD")).run(occurred_at=START + timedelta(minutes=3)).journal_entry
    approval = DecisionApprovalService(store).decide(
        decision_cycle_id=journal.decision_cycle_id, decision=ApprovalDecision.REJECTED,
        decision_maker_id="local-operator", decided_at=START + timedelta(minutes=4),
    )
    assert approval.decision is ApprovalDecision.REJECTED
    assert not store.open_run().executions
    assert batch.decision_cycle_id == journal.decision_cycle_id


def test_validation_failed_buy_is_journaled_but_cannot_be_approved(tmp_path) -> None:
    store, _, _ = _prepared_store(tmp_path, include_price=False)
    journal = RunValueManagerService(store, manager=_Manager()).run(occurred_at=START + timedelta(minutes=3)).journal_entry
    assert not journal.risk_validation_result.passed
    with pytest.raises(ValueError, match="APPROVED requires passed deterministic validation"):
        DecisionApprovalService(store).decide(
            decision_cycle_id=journal.decision_cycle_id, decision=ApprovalDecision.APPROVED,
            decision_maker_id="local-operator", decided_at=START + timedelta(minutes=4),
        )
    assert not store.open_run().approvals


def test_provider_failure_persists_no_decision_graph(tmp_path) -> None:
    store, _, _ = _prepared_store(tmp_path)
    before = store.open_run()
    with pytest.raises(RuntimeError, match="provider failed"):
        RunValueManagerService(store, manager=_Manager(error=RuntimeError("provider failed"))).run(
            occurred_at=START + timedelta(minutes=3)
        )
    assert store.open_run() == before


def test_ambiguous_latest_batch_and_duplicate_or_conflicting_approval_are_rejected(tmp_path) -> None:
    store, batch, _ = _prepared_store(tmp_path)
    state = store.open_run()
    duplicate_time_batch = replace(batch, batch_id="second-batch")
    store.save_transition(replace(state, research_batches=(batch, duplicate_time_batch)))
    with pytest.raises(ValueError, match="latest persisted ResearchBatch is ambiguous"):
        RunValueManagerService(store, manager=_Manager()).run(occurred_at=START + timedelta(minutes=3))

    # Use a fresh non-ambiguous store to prove first human outcome is terminal.
    store, batch, _ = _prepared_store(tmp_path / "fresh")
    journal = RunValueManagerService(store, manager=_Manager()).run(occurred_at=START + timedelta(minutes=3)).journal_entry
    approvals = DecisionApprovalService(store)
    approvals.decide(decision_cycle_id=journal.decision_cycle_id, decision=ApprovalDecision.APPROVED, decision_maker_id="operator", decided_at=START + timedelta(minutes=4))
    with pytest.raises(DecisionCommandConflict, match="immutable APPROVED"):
        approvals.decide(decision_cycle_id=journal.decision_cycle_id, decision=ApprovalDecision.REJECTED, decision_maker_id="operator", decided_at=START + timedelta(minutes=5))


def test_equal_latest_conflicting_price_observations_are_not_selected(tmp_path) -> None:
    store, batch, price = _prepared_store(tmp_path)
    state = store.open_run()
    manager = _Manager()
    recommendation = manager.decide(
        type("Context", (), {"research_batch": batch})()
    )
    conflicting = replace(price, observed_price=Decimal("101"))
    raw_state = object.__new__(type(state))
    for field in state.__dataclass_fields__:
        object.__setattr__(raw_state, field, getattr(state, field))
    object.__setattr__(raw_state, "price_observations", (price, conflicting))
    with pytest.raises(ValueError, match="latest eligible PriceObservation is ambiguous"):
        _eligible_buy_observation(raw_state, recommendation, batch, START + timedelta(minutes=3))


def test_api_commands_and_readiness_are_authoritative_after_restart(tmp_path) -> None:
    from fastapi.testclient import TestClient

    store, batch, _ = _prepared_store(tmp_path)
    client = TestClient(create_app(database_path=str(tmp_path / "run.sqlite"), value_manager=_Manager()))
    run = client.post("/commands/run-value-manager", json={"occurred_at": (START + timedelta(minutes=3)).isoformat()})
    assert run.status_code == 200
    assert run.json()["reviewer"] is None
    assert run.json()["execution_readiness"]["reason_code"] == "NOT_APPROVED"
    assert run.json()["decision_cycle_id"] == str(batch.decision_cycle_id)
    approved = client.post(
        f"/commands/decisions/{batch.decision_cycle_id}/approve",
        json={"decision_maker_id": "operator", "decided_at": (START + timedelta(minutes=4)).isoformat()},
    )
    assert approved.status_code == 200
    assert approved.json()["execution_readiness"] == {
        "executable": True, "reason_code": "READY", "decision_cycle_id": str(batch.decision_cycle_id),
        "action": "BUY", "security": {"ticker": batch.packets[0].ticker, "security_type": "EQUITY", "exchange": "NASDAQ", "currency": "USD"},
        "approval_status": "APPROVED", "validation_status": "PASSED",
    }
    assert client.get("/decisions/latest").json()["approval"]["decision"] == "APPROVED"
    assert len(client.get("/decisions").json()["entries_newest_first"]) == 1
    assert client.get("/dashboard").json()["latest_decision"]["execution_readiness"]["reason_code"] == "READY"


def test_latest_research_is_shared_by_read_and_command_paths_not_insertion_order(tmp_path) -> None:
    from fastapi.testclient import TestClient

    store, newer, price = _prepared_store(tmp_path)
    state = store.open_run()
    older = replace(
        newer,
        batch_id="older-batch",
        decision_cycle_id=uuid4(),
        created_at=START,
        as_of_timestamp=START,
    )
    # Persist in deliberately non-chronological insertion order.
    store.save_transition(replace(state, research_batches=(newer, older)))
    client = TestClient(create_app(database_path=str(tmp_path / "run.sqlite"), value_manager=_Manager()))
    research = client.get("/research/latest")
    assert research.status_code == 200
    assert research.json()["batch_id"] == newer.batch_id
    run = client.post("/commands/run-value-manager", json={"occurred_at": (START + timedelta(minutes=3)).isoformat()})
    assert run.status_code == 200
    assert run.json()["decision_cycle_id"] == str(newer.decision_cycle_id)


def test_equal_latest_research_batch_is_rejected_by_read_and_command_paths(tmp_path) -> None:
    from fastapi.testclient import TestClient

    store, batch, _ = _prepared_store(tmp_path)
    state = store.open_run()
    tied = replace(batch, batch_id="tied-batch")
    store.save_transition(replace(state, research_batches=(batch, tied)))
    client = TestClient(create_app(database_path=str(tmp_path / "run.sqlite"), value_manager=_Manager()))
    assert client.get("/research/latest").status_code == 503
    command = client.post("/commands/run-value-manager", json={"occurred_at": (START + timedelta(minutes=3)).isoformat()})
    assert command.status_code == 422
    assert "ambiguous" in command.json()["detail"]["message"]


def test_serialized_execution_readiness_covers_every_current_reason() -> None:
    demo = build_demo_dashboard_data()
    ready_journal = demo.history_entries[0].journal_entry
    ready_approval = demo.history_entries[0].approval
    executed_trade = demo.history_entries[0].executed_trade
    assert ready_approval is not None and executed_trade is not None
    cases = {
        "READY": decision_memo_response(ready_journal, ready_approval, None),
        "ALREADY_EXECUTED": decision_memo_response(ready_journal, ready_approval, executed_trade),
        "HOLD": decision_memo_response(demo.journal_entry, None, None),
        "NOT_APPROVED": decision_memo_response(ready_journal, None, None),
    }
    rejected = DecisionApproval(
        ready_journal, "operator", ApprovalDecision.REJECTED, ready_journal.journaled_at + timedelta(minutes=1)
    )
    cases["REJECTED"] = decision_memo_response(ready_journal, rejected, None)
    failed_journal = DecisionJournalEntry(
        ready_journal.decision_result,
        DeterministicRiskValidator().validate(
            ready_journal.decision_result,
            validation_timestamp=demo.journal_entry.journaled_at,
        ),
        demo.journal_entry.journaled_at,
    )
    cases["VALIDATION_FAILED"] = decision_memo_response(failed_journal, None, None)
    for reason, response in cases.items():
        readiness = response.execution_readiness
        assert readiness.reason_code == reason
        assert readiness.executable is (reason == "READY")
        assert readiness.decision_cycle_id == str(response.decision_cycle_id)
        assert readiness.action == response.recommendation.action
        if reason in {"HOLD", "VALIDATION_FAILED"}:
            assert readiness.security is None
        else:
            assert readiness.security is not None
