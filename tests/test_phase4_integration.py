"""Focused Phase 4 durable BUY-to-paper-execution integration coverage."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from agentic_portfolio_lab.api.app import create_app
from agentic_portfolio_lab.dashboard_demo import _demo_research_batch
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.recommendations import (
    PortfolioRecommendation,
    RecommendationEvidenceReference,
    ReviewTrigger,
)
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore


UTC = timezone.utc
START = datetime(2026, 9, 1, 14, tzinfo=UTC)


class _BuyManager:
    """Deterministic fake that supplies an otherwise valid managed BUY."""

    def decide(self, context):
        packet = context.research_batch.packets[0]
        evidence = packet.evidence_items[0]
        return PortfolioRecommendation(
            action="BUY",
            ticker=packet.ticker,
            target_weight=Decimal("0.25"),
            decision_rationale="Durable integration recommendation.",
            investment_thesis="Integration-only test thesis.",
            valuation="Integration valuation.",
            risks=("Integration risk.",),
            confidence_score=75,
            evidence=(RecommendationEvidenceReference(
                evidence.evidence_id, evidence.source_type, evidence.source_title,
                evidence.source_date, evidence.claim_supported,
            ),),
            why_not_spy="Security-specific evidence exists.",
            thesis_invalidation=("Integration invalidation.",),
            review_triggers=(ReviewTrigger("EVENT_BASED", "Integration trigger."),),
        )


def test_durable_buy_approval_execution_flow_survives_restart_and_api_reads(tmp_path) -> None:
    database_path = tmp_path / "run.sqlite"
    store = SQLiteLocalRunStore(database_path)
    initial = store.initialize_run(initialized_at=START)
    research = replace(
        _demo_research_batch(initial.managed_portfolio, batch_id="phase4-batch"),
        created_at=START + timedelta(minutes=1),
        as_of_timestamp=START + timedelta(minutes=1),
    )
    packet = research.packets[0]
    security = SecurityIdentity(packet.ticker, packet.security_type, packet.exchange, packet.currency)
    unrelated_security = SecurityIdentity("GOOGL", "EQUITY", "NASDAQ", "USD")
    validation_quote = PriceObservation(
        security, Decimal("100"), START.date(), START + timedelta(minutes=2), "USD", "fake", "fake-quote",
    )
    unrelated_quote = PriceObservation(
        unrelated_security, Decimal("200"), START.date(), START + timedelta(minutes=2), "USD", "fake", "fake-quote",
    )
    store.save_transition(replace(
        initial,
        research_batches=(research,),
        price_observations=(validation_quote, unrelated_quote),
    ))

    client = TestClient(create_app(database_path=str(database_path), value_manager=_BuyManager()))
    run = client.post("/commands/run-value-manager", json={"occurred_at": (START + timedelta(minutes=3)).isoformat()})
    assert run.status_code == 200
    cycle_id = run.json()["decision_cycle_id"]
    assert cycle_id == str(research.decision_cycle_id)
    assert run.json()["execution_readiness"]["reason_code"] == "NOT_APPROVED"

    approved = client.post(
        f"/commands/decisions/{cycle_id}/approve",
        json={"decision_maker_id": "local-operator", "decided_at": (START + timedelta(minutes=4)).isoformat()},
    )
    assert approved.status_code == 200
    assert approved.json()["execution_readiness"]["reason_code"] == "READY"

    # Execution must choose a persisted quote after the approval boundary.
    current = store.open_run()
    assert current is not None
    execution_quote = PriceObservation(
        security, Decimal("101"), START.date(), START + timedelta(minutes=5), "USD", "fake", "fake-quote",
    )
    store.save_transition(replace(current, price_observations=(*current.price_observations, execution_quote)))
    executed = client.post(
        f"/commands/decisions/{cycle_id}/execute-paper-trade",
        params={"executed_at": (START + timedelta(minutes=6)).isoformat()},
    )
    assert executed.status_code == 200
    assert executed.json()["validated_trade_id"]
    assert executed.json()["ticker"] == packet.ticker

    reopened = SQLiteLocalRunStore(database_path).open_run()
    assert reopened is not None
    assert len(reopened.executions) == 1
    journal = reopened.journal_entries[0]
    approval = reopened.approvals[0]
    execution = reopened.executions[0]
    assert journal.decision_cycle_id == research.decision_cycle_id
    assert journal.decision_result.context.research_batch is reopened.research_batches[0]
    assert approval.journal_entry is journal
    assert execution.executed_trade.validated_trade is journal.risk_validation_result.validated_trade
    assert reopened.managed_portfolio.cash_balance.amount < initial.managed_portfolio.cash_balance.amount
    assert reopened.managed_portfolio.positions
    assert len(reopened.managed_history.snapshots) == 2
    assert reopened.history_entries[0].executed_trade is execution.executed_trade
    assert reopened.research_batches[0] == research
    assert unrelated_quote in reopened.price_observations
    assert reopened.benchmark_history == initial.benchmark_history

    portfolio = client.get("/portfolio")
    latest = client.get("/decisions/latest")
    history = client.get("/decisions")
    dashboard = client.get("/dashboard")
    performance = client.get("/performance")
    assert portfolio.status_code == latest.status_code == history.status_code == dashboard.status_code == performance.status_code == 200
    assert portfolio.json()["positions"]
    assert latest.json()["execution"]["executed_trade_id"] == str(execution.executed_trade.executed_trade_id)
    assert latest.json()["execution_readiness"]["reason_code"] == "ALREADY_EXECUTED"
    assert history.json()["entries_newest_first"][0]["execution"]["executed_trade_id"] == str(execution.executed_trade.executed_trade_id)
    assert dashboard.json()["latest_decision"]["execution_readiness"]["reason_code"] == "ALREADY_EXECUTED"
    assert performance.json() is None

    second_execution = client.post(
        f"/commands/decisions/{cycle_id}/execute-paper-trade",
        params={"executed_at": (START + timedelta(minutes=7)).isoformat()},
    )
    assert second_execution.status_code == 422
    assert "already been executed" in second_execution.json()["detail"]["message"]
