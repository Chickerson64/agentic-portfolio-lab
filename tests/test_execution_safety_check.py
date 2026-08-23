"""Focused Lane 5 execution-time System Safety regressions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agentic_portfolio_lab.application.decision_commands import (
    DecisionApprovalService,
    RunValueManagerService,
)
from agentic_portfolio_lab.application.managed_execution import (
    ManagedPaperExecutionError,
    ManagedPaperExecutionService,
)
from agentic_portfolio_lab.dashboard_demo import _demo_research_batch
from agentic_portfolio_lab.domain.approval import ApprovalDecision
from agentic_portfolio_lab.domain.execution_check import ExecutionSafetyCheck
from agentic_portfolio_lab.domain.policy import CurrentPolicyReference, LegacyPolicyReference
from agentic_portfolio_lab.domain.portfolio import CashBalance, Position, SecurityIdentity
from agentic_portfolio_lab.domain.recommendations import (
    PortfolioRecommendation,
    RecommendationEvidenceReference,
    ReviewTrigger,
)
from agentic_portfolio_lab.domain.risk_validation import TwoLayerRiskEvaluator
from agentic_portfolio_lab.domain.valuation import PortfolioValuation, PriceObservation
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore


UTC = timezone.utc
START = datetime(2026, 8, 21, 14, 0, tzinfo=UTC)


class _Manager:
    def __init__(self, target_weight: Decimal) -> None:
        self.target_weight = target_weight

    def decide(self, context):
        packet = context.research_batch.packets[0]
        evidence = packet.evidence_items[0]
        return PortfolioRecommendation(
            action="BUY",
            ticker=packet.ticker,
            target_weight=self.target_weight,
            decision_rationale="Structured execution-check regression.",
            investment_thesis="A deterministic fixture thesis.",
            valuation="Fixture valuation.",
            risks=("Fixture risk.",),
            confidence_score=70,
            evidence=(
                RecommendationEvidenceReference(
                    evidence.evidence_id,
                    evidence.source_type,
                    evidence.source_title,
                    evidence.source_date,
                    evidence.claim_supported,
                ),
            ),
            why_not_spy="Fixture-specific evidence.",
            thesis_invalidation=("Fixture invalidation.",),
            review_triggers=(ReviewTrigger("EVENT_BASED", "Fixture trigger."),),
        )


@dataclass(frozen=True)
class _ExecutionFixture:
    store: SQLiteLocalRunStore
    journal: object
    approval: object
    validation_quote: PriceObservation
    execution_quote: PriceObservation
    executed_at: datetime


@pytest.fixture
def current_policy_execution_fixture(tmp_path):
    """Build an approved current-policy journal with a persisted execution quote."""

    sequence = 0

    def prepare(*, target_weight: Decimal = Decimal("0.25")) -> _ExecutionFixture:
        nonlocal sequence
        sequence += 1
        store = SQLiteLocalRunStore(tmp_path / f"run-{sequence}.sqlite")
        state = store.initialize_run(initialized_at=START)
        batch = replace(
            _demo_research_batch(state.managed_portfolio, batch_id=f"execution-batch-{sequence}"),
            created_at=START + timedelta(minutes=1),
            as_of_timestamp=START + timedelta(minutes=1),
        )
        packet = batch.packets[0]
        security = SecurityIdentity(packet.ticker, packet.security_type, packet.exchange, packet.currency)
        validation_quote = PriceObservation(
            security=security,
            observed_price=Decimal("100"),
            market_date=START.date(),
            observed_at=START + timedelta(minutes=2),
            currency="USD",
            source_provider_identity="fake",
            price_convention="fake-quote",
        )
        store.save_transition(
            replace(state, research_batches=(batch,), price_observations=(validation_quote,))
        )
        journal = RunValueManagerService(
            store, manager=_Manager(target_weight)
        ).run(occurred_at=START + timedelta(minutes=3)).journal_entry
        approval = DecisionApprovalService(store).decide(
            decision_cycle_id=journal.decision_cycle_id,
            decision=ApprovalDecision.APPROVED,
            decision_maker_id="local-operator",
            decided_at=START + timedelta(minutes=4),
        )
        execution_quote = replace(
            validation_quote,
            observed_price=Decimal("101"),
            observed_at=START + timedelta(minutes=5),
        )
        approved_state = store.open_run()
        assert approved_state is not None
        store.save_transition(
            replace(
                approved_state,
                price_observations=(*approved_state.price_observations, execution_quote),
            )
        )
        return _ExecutionFixture(
            store,
            journal,
            approval,
            validation_quote,
            execution_quote,
            START + timedelta(minutes=6),
        )

    return prepare


def test_passed_check_links_trade_and_restart_canonicalizes_graph(
    current_policy_execution_fixture,
) -> None:
    fixture = current_policy_execution_fixture()

    result = ManagedPaperExecutionService(fixture.store).execute(
        decision_cycle_id=fixture.journal.decision_cycle_id,
        executed_at=fixture.executed_at,
    )

    state = fixture.store.open_run()
    assert state is not None
    assert len(state.execution_checks) == 1
    check = state.execution_checks[0]
    execution = state.executions[0]
    assert check.passed
    assert execution.executed_trade.execution_check_id == check.check_id
    assert execution.execution_observation is check.execution_observation
    assert check.approval is state.approvals[0]
    assert execution.approval is state.approvals[0]
    assert result.execution.executed_trade.execution_check_id == check.check_id


@pytest.mark.parametrize("drift", ("cash", "position"))
def test_drifted_portfolio_persists_failed_check_without_trade(
    current_policy_execution_fixture, drift
) -> None:
    fixture = current_policy_execution_fixture()
    state = fixture.store.open_run()
    assert state is not None
    portfolio = state.managed_portfolio
    if drift == "cash":
        drifted = replace(portfolio, cash_balance=CashBalance("USD", Decimal("0")))
    else:
        drifted = replace(
            portfolio,
            cash_balance=CashBalance("USD", Decimal("0")),
            positions=(
                Position(
                    security=fixture.execution_quote.security,
                    quantity=Decimal("10"),
                    total_cost_basis=Decimal("1000"),
                    market_price=fixture.execution_quote.observed_price,
                ),
            ),
        )
    drifted_at = fixture.execution_quote.observed_at + timedelta(seconds=30)
    valuation = PortfolioValuation.from_portfolio(
        drifted,
        () if drift == "cash" else (fixture.execution_quote,),
        as_of_timestamp=drifted_at,
        market_date=fixture.execution_quote.market_date,
        source_price_timestamp=fixture.execution_quote.observed_at,
        source_provider_identity=fixture.execution_quote.source_provider_identity,
        price_convention=fixture.execution_quote.price_convention,
    )
    fixture.store.save_transition(
        replace(
            state,
            managed_portfolio=drifted,
            managed_history=state.managed_history.append(drifted, valuation),
        )
    )

    with pytest.raises(
        ManagedPaperExecutionError,
        match="execution-time System Safety revalidation failed",
    ):
        ManagedPaperExecutionService(fixture.store).execute(
            decision_cycle_id=fixture.journal.decision_cycle_id,
            executed_at=fixture.executed_at,
        )

    reopened = fixture.store.open_run()
    assert reopened is not None
    assert reopened.executions == ()
    assert len(reopened.execution_checks) == 1
    assert not reopened.execution_checks[0].passed
    assert reopened.execution_checks[0].safety_validation.validated_trade is None


def test_advisory_findings_do_not_gate_execution(current_policy_execution_fixture) -> None:
    fixture = current_policy_execution_fixture(target_weight=Decimal("0.25"))
    assessment = fixture.journal.two_layer_evaluation.manager_assessment
    assert assessment is not None
    assert any(
        finding.finding_id == "NORMAL_STARTER_GUIDANCE_DEVIATION"
        and finding.severity.value == "MATERIAL"
        for finding in assessment.findings
    )

    ManagedPaperExecutionService(fixture.store).execute(
        decision_cycle_id=fixture.journal.decision_cycle_id,
        executed_at=fixture.executed_at,
    )

    reopened = fixture.store.open_run()
    assert reopened is not None
    assert reopened.execution_checks[0].passed
    assert len(reopened.executions) == 1


@pytest.mark.parametrize("target_weight", (Decimal("0.80"), Decimal("1")))
def test_funded_long_only_targets_execute_at_original_weight(
    current_policy_execution_fixture, target_weight
) -> None:
    fixture = current_policy_execution_fixture(target_weight=target_weight)

    ManagedPaperExecutionService(fixture.store).execute(
        decision_cycle_id=fixture.journal.decision_cycle_id,
        executed_at=fixture.executed_at,
    )

    reopened = fixture.store.open_run()
    assert reopened is not None
    execution = reopened.executions[0]
    assert reopened.execution_checks[0].passed
    assert execution.execution_target_purchase.target_weight == target_weight
    assert execution.executed_trade.validated_trade.proposal.target_weight == target_weight
    assert execution.executed_trade.executed_quantity > 0


def test_duplicate_cross_cycle_and_stale_execution_check_links_are_rejected(
    current_policy_execution_fixture,
) -> None:
    first = current_policy_execution_fixture()
    ManagedPaperExecutionService(first.store).execute(
        decision_cycle_id=first.journal.decision_cycle_id,
        executed_at=first.executed_at,
    )
    state = first.store.open_run()
    assert state is not None
    check = state.execution_checks[0]

    with pytest.raises(ValueError, match="duplicate identities"):
        replace(state, execution_checks=(check, check)).validate()

    second = current_policy_execution_fixture()
    ManagedPaperExecutionService(second.store).execute(
        decision_cycle_id=second.journal.decision_cycle_id,
        executed_at=second.executed_at,
    )
    second_state = second.store.open_run()
    assert second_state is not None
    foreign_check = second_state.execution_checks[0]
    cross_cycle_execution = replace(
        state.executions[0],
        executed_trade=replace(
            state.executions[0].executed_trade,
            execution_check_id=foreign_check.check_id,
        ),
    )
    with pytest.raises(ValueError, match="canonical approvals|passed execution safety check"):
        replace(
            state,
            executions=(cross_cycle_execution,),
            execution_checks=(foreign_check,),
        ).validate()

    stale_execution = replace(
        state.executions[0],
        executed_trade=replace(
            state.executions[0].executed_trade,
            executed_at=state.executions[0].executed_trade.executed_at + timedelta(seconds=1),
        ),
    )
    with pytest.raises(ValueError, match="performed at execution time"):
        replace(state, executions=(stale_execution,)).validate()

    missing_link_execution = replace(
        state.executions[0],
        executed_trade=replace(
            state.executions[0].executed_trade,
            execution_check_id=uuid4(),
        ),
    )
    with pytest.raises(ValueError, match="passed execution safety check"):
        replace(state, executions=(missing_link_execution,)).validate()


def test_linked_check_must_use_execution_original_portfolio_and_target(
    current_policy_execution_fixture,
) -> None:
    fixture = current_policy_execution_fixture()
    ManagedPaperExecutionService(fixture.store).execute(
        decision_cycle_id=fixture.journal.decision_cycle_id,
        executed_at=fixture.executed_at,
    )
    state = fixture.store.open_run()
    assert state is not None
    execution = state.executions[0]
    existing_check = state.execution_checks[0]
    mismatched_portfolio = replace(
        execution.original_portfolio,
        cash_balance=CashBalance("USD", Decimal("20000")),
    )
    mismatched_decision = replace(
        state.journal_entries[0].decision_result,
        context=replace(
            state.journal_entries[0].decision_result.context,
            portfolio=mismatched_portfolio,
        ),
    )
    mismatched_safety = TwoLayerRiskEvaluator().evaluate(
        mismatched_decision,
        validation_timestamp=existing_check.checked_at,
        price_observation=existing_check.execution_observation,
        system_safety_envelope=existing_check.policy_reference.system_safety_envelope,
    ).safety_validation
    mismatched_check = ExecutionSafetyCheck(
        approval=state.approvals[0],
        policy_reference=existing_check.policy_reference,
        safety_validation=mismatched_safety,
        checked_at=existing_check.checked_at,
        execution_observation=existing_check.execution_observation,
    )
    mismatched_execution = replace(
        execution,
        executed_trade=replace(
            execution.executed_trade,
            execution_check_id=mismatched_check.check_id,
        ),
    )

    with pytest.raises(ValueError, match="portfolio must match execution original portfolio"):
        replace(
            state,
            executions=(mismatched_execution,),
            execution_checks=(mismatched_check,),
        )


def test_policy_lineage_mismatch_persists_denied_check(
    current_policy_execution_fixture, monkeypatch
) -> None:
    fixture = current_policy_execution_fixture()
    journal_policy = fixture.journal.policy_reference
    assert isinstance(journal_policy, CurrentPolicyReference)
    different_manager_policy = replace(
        journal_policy.manager_risk_constitution,
        loading_source="future-policy-source",
        content_hash=None,
    )
    active_policy = replace(
        journal_policy,
        manager_risk_constitution=different_manager_policy,
    )
    monkeypatch.setattr(
        "agentic_portfolio_lab.application.managed_execution.load_active_value_policy",
        lambda: active_policy,
    )

    with pytest.raises(
        ManagedPaperExecutionError,
        match="execution-time System Safety revalidation failed",
    ):
        ManagedPaperExecutionService(fixture.store).execute(
            decision_cycle_id=fixture.journal.decision_cycle_id,
            executed_at=fixture.executed_at,
        )

    reopened = fixture.store.open_run()
    assert reopened is not None
    assert reopened.executions == ()
    assert len(reopened.execution_checks) == 1
    check = reopened.execution_checks[0]
    assert check.safety_validation.passed
    assert not check.policy_lineage_matches
    assert not check.passed
    assert check.policy_lineage_failure_reason is not None


def test_passed_check_persists_when_post_check_valuation_aborts_execution(
    current_policy_execution_fixture,
) -> None:
    fixture = current_policy_execution_fixture()
    state = fixture.store.open_run()
    assert state is not None
    other_security = SecurityIdentity("MSFT", "EQUITY", "NASDAQ", "USD")
    other_quote = PriceObservation(
        security=other_security,
        observed_price=Decimal("100"),
        market_date=fixture.execution_quote.market_date,
        observed_at=fixture.execution_quote.observed_at + timedelta(seconds=30),
        currency="USD",
        source_provider_identity="fake",
        price_convention="fake-quote",
    )
    portfolio_with_other_position = replace(
        state.managed_portfolio,
        positions=(
            Position(
                security=other_security,
                quantity=Decimal("1"),
                total_cost_basis=Decimal("100"),
                market_price=Decimal("100"),
            ),
        ),
    )
    valuation = PortfolioValuation.from_portfolio(
        portfolio_with_other_position,
        (other_quote,),
        as_of_timestamp=other_quote.observed_at,
        market_date=other_quote.market_date,
        source_price_timestamp=other_quote.observed_at,
        source_provider_identity=other_quote.source_provider_identity,
        price_convention=other_quote.price_convention,
    )
    fixture.store.save_transition(
        replace(
            state,
            managed_portfolio=portfolio_with_other_position,
            managed_history=state.managed_history.append(
                portfolio_with_other_position,
                valuation,
            ),
            price_observations=(*state.price_observations, other_quote),
        )
    )

    with pytest.raises(
        ManagedPaperExecutionError,
        match="synchronized observations",
    ):
        ManagedPaperExecutionService(fixture.store).execute(
            decision_cycle_id=fixture.journal.decision_cycle_id,
            executed_at=fixture.executed_at,
        )

    reopened = fixture.store.open_run()
    assert reopened is not None
    assert reopened.executions == ()
    assert len(reopened.execution_checks) == 1
    assert reopened.execution_checks[0].passed


def test_legacy_execution_remains_compatible_without_execution_check(
    current_policy_execution_fixture,
) -> None:
    fixture = current_policy_execution_fixture()
    state = fixture.store.open_run()
    assert state is not None
    legacy_journal = replace(
        state.journal_entries[0],
        policy_reference=LegacyPolicyReference(),
        two_layer_evaluation=None,
    )
    legacy_approval = replace(state.approvals[0], journal_entry=legacy_journal)
    legacy_history = replace(
        state.history_entries[0],
        journal_entry=legacy_journal,
        approval=legacy_approval,
    )
    legacy_state = replace(
        state,
        journal_entries=(legacy_journal,),
        approvals=(legacy_approval,),
        history_entries=(legacy_history,),
    )

    class LegacyStore:
        def __init__(self, current):
            self.current = current

        def open_run(self):
            return self.current

        def save_transition(self, proposed):
            proposed.validate()
            self.current = proposed

    legacy_store = LegacyStore(legacy_state)
    ManagedPaperExecutionService(legacy_store).execute(
        decision_cycle_id=legacy_journal.decision_cycle_id,
        executed_at=fixture.executed_at,
    )

    assert legacy_store.current.execution_checks == ()
    assert legacy_store.current.executions[0].executed_trade.execution_check_id is None
