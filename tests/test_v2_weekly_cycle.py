"""Offline #41 application-path regression coverage."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agentic_portfolio_lab.application.v2_weekly_cycle import V2WeeklyCycleService
from agentic_portfolio_lab.domain import CashBalance, CashClassification, CashTarget, Portfolio, PortfolioTargetAllocation, PortfolioTargetPosition, RecommendationEvidenceReference, SecurityIdentity, V2PriceSnapshot
from agentic_portfolio_lab.domain.recommendations import ReviewTrigger
from agentic_portfolio_lab.domain.research_v3 import ResearchBatchV3, ResearchSubjectRole, ResearchV3Evidence, ResearchV3Subject, ScreeningEvidenceContext
from agentic_portfolio_lab.domain.screening_v2 import ScreeningFeatures, ScreeningProfile, ScreeningProfileIdentity, ScreeningProvenance, ScreeningRunV2
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore
from uuid import uuid4

NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
def sec(t): return SecurityIdentity(t, "EQUITY", "NASDAQ", "USD")
def quote(t, p): return PriceObservation(sec(t), Decimal(p), NOW.date(), NOW, "USD", "offline", "close")

def artifacts(portfolio, *, weight="0.600000", cash="0.400000"):
    identity = ScreeningProfileIdentity("value", "offline", "v3")
    profile = ScreeningProfile(identity, Decimal("1"), Decimal("1"))
    run_id = uuid4()
    screening = ScreeningRunV2(run_id, profile, ScreeningProvenance(NOW, ("offline",), "universe-offline", NOW), "universe-offline", (), (), (), ())
    evidence = ResearchV3Evidence("e1", "offline", "FILING", "Offline filing", date(2026, 9, 1), "ref", "CURRENT")
    subject = ResearchV3Subject("aapl", sec("AAPL"), ResearchSubjectRole.NEW_CANDIDATE, NOW, (evidence,), "offline", ScreeningEvidenceContext("universe-offline", identity, run_id, 1, ScreeningFeatures(Decimal("10"), Decimal("100"), Decimal("1"), None, Decimal("1"))))
    research = ResearchBatchV3("research-v3", run_id, "universe-offline", identity, NOW, (subject,))
    position = PortfolioTargetPosition(sec("AAPL"), Decimal(weight), "core", "Offline evidence-backed thesis", 80, (RecommendationEvidenceReference("e1", "FILING", "Offline filing", date(2026, 9, 1), "supports thesis"),), (), (ReviewTrigger("scheduled", "quarterly"),), "INITIATE")
    target = PortfolioTargetAllocation(portfolio.portfolio_id, "multi-position target rationale", "risk", "concentration", "SPY context", CashTarget(Decimal(cash), CashClassification.STRATEGIC, "intentional cash"), (position,))
    return screening, research, target

def test_v2_cycle_persists_exact_target_approval_execution_and_reconciliation(tmp_path):
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    state = store.initialize_run(initialized_at=NOW)
    # The initialized $1,000 all-cash account is adjusted only through the
    # authoritative state fixture; the cycle itself starts from that state.
    service = V2WeeklyCycleService(store, now=lambda: NOW)
    screening, research, target = artifacts(state.managed_portfolio)
    cycle = service.record_preapproval(universe_snapshot_id="universe-offline", screening=screening, research=research, target=target, snapshot=V2PriceSnapshot((quote("AAPL", "10"),)))
    assert cycle.plan.legs and cycle.readiness()["approval_status"] == "PENDING"
    approved = service.approve(cycle.cycle_id, decision_maker_id="human", decided_at=NOW + timedelta(minutes=1))
    completed = service.execute(approved.cycle_id, executed_at=NOW + timedelta(minutes=2))
    reloaded = SQLiteLocalRunStore(tmp_path / "run.sqlite").open_run()
    assert reloaded is not None and reloaded.v2_cycles[0] == completed
    assert reloaded.managed_portfolio == completed.execution.resulting_portfolio
    assert completed.readiness()["execution_status"] == "EXECUTED"

def test_v2_no_action_is_terminal_without_approval_or_execution(tmp_path):
    store = SQLiteLocalRunStore(tmp_path / "no-action.sqlite")
    state = store.initialize_run(initialized_at=NOW)
    service = V2WeeklyCycleService(store, now=lambda: NOW)
    screening, research, _ = artifacts(state.managed_portfolio)
    # A zero-weight REMOVE needs a valid target position, so use the complete
    # all-cash target directly with the researched name omitted.
    target = PortfolioTargetAllocation(state.managed_portfolio.portfolio_id, "cash", "risk", "concentration", "SPY", CashTarget(Decimal("1"), CashClassification.STRATEGIC, "intentional"), ())
    cycle = service.record_preapproval(universe_snapshot_id="universe-offline", screening=screening, research=research, target=target, snapshot=V2PriceSnapshot((quote("AAPL", "10"),)))
    assert cycle.no_action and cycle.readiness()["approval_status"] == "NOT_APPLICABLE"
    with pytest.raises(ValueError, match="no-action"):
        service.approve(cycle.cycle_id, decision_maker_id="human", decided_at=NOW)
