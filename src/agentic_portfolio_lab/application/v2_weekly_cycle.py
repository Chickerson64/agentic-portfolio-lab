"""Artifact-derived V2 weekly-cycle orchestration.

This deliberately has no lifecycle enum.  The durable local-run aggregate is
the sole source of truth; readiness is projected from immutable artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Protocol
from uuid import UUID, uuid4

from agentic_portfolio_lab.domain.portfolio import Portfolio
from agentic_portfolio_lab.domain.portfolio_decisions_v2 import PortfolioTargetAllocation
from agentic_portfolio_lab.domain.research_v3 import ResearchBatchV3
from agentic_portfolio_lab.domain.screening_v2 import ScreeningRunV2
from agentic_portfolio_lab.domain.target_execution_v2 import BatchApproval, BatchRejection, BatchSystemSafetyResult, BatchTradePlan, SimulatedBatchExecution, V2PriceSnapshot, build_batch_trade_plan, evaluate_batch_plan_safety, execute_approved_batch
from agentic_portfolio_lab.domain.value_manager import ValueManagerDecisionContext
from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.v2_advisory import V2AIReviewer, V2ManagerRiskAdvisor, V2ManagerRiskAssessment, V2ReviewerResult
from .active_policy import load_active_value_policy
from agentic_portfolio_lab.domain.valuation import PortfolioValuation


@dataclass(frozen=True, slots=True)
class V2CycleArtifacts:
    """One append-preserving V2 lineage inside the authoritative local run."""
    cycle_id: UUID
    started_at: datetime
    original_portfolio: Portfolio
    universe_snapshot_id: str
    screening: ScreeningRunV2
    research: ResearchBatchV3
    target: PortfolioTargetAllocation
    plan: BatchTradePlan
    system_safety: BatchSystemSafetyResult
    manager_risk: V2ManagerRiskAssessment
    reviewer: V2ReviewerResult | None = None
    approval: BatchApproval | None = None
    rejection: BatchRejection | None = None
    execution: SimulatedBatchExecution | None = None
    reconciled_at: datetime | None = None
    execution_backend: str = "internal-simulator"

    def __post_init__(self) -> None:
        if self.target.portfolio_id != self.original_portfolio.portfolio_id:
            raise ValueError("V2 target must retain managed-portfolio lineage")
        if self.plan.target != self.target or self.plan.original_portfolio != self.original_portfolio:
            raise ValueError("V2 plan must retain the exact target and current portfolio")
        if self.research.screening_run_id != self.screening.screening_run_id:
            raise ValueError("V2 research must retain screening lineage")
        if self.research.snapshot_id != self.universe_snapshot_id:
            raise ValueError("V2 research must retain universe lineage")
        if self.system_safety.plan.identity != self.plan.identity:
            raise ValueError("V2 System Safety must retain the exact plan")
        if self.manager_risk.plan_identity != self.plan.identity or self.manager_risk.target_identity != self.plan.target_identity:
            raise ValueError("V2 Manager Risk must retain the exact plan and target")
        if self.reviewer is not None and self.reviewer.plan_identity != self.plan.identity:
            raise ValueError("V2 reviewer must retain the exact plan")
        if self.approval is not None and self.approval.plan != self.plan:
            raise ValueError("V2 approval must bind to the exact immutable plan")
        if self.rejection is not None and self.rejection.plan != self.plan:
            raise ValueError("V2 rejection must bind to the exact immutable plan")
        if self.approval is not None and self.rejection is not None:
            raise ValueError("V2 cycle cannot have both approval and rejection")
        if self.execution is not None and (self.approval is None or self.execution.approval != self.approval):
            raise ValueError("V2 execution must bind to the exact immutable approval")
        if not self.plan.legs and (self.approval is not None or self.execution is not None):
            raise ValueError("a V2 no-action plan cannot have approval or execution")

    @property
    def no_action(self) -> bool:
        return not self.plan.legs

    def readiness(self) -> dict[str, object]:
        completed = ["universe", "screening", "research_v3", "target", "target_diff", "system_safety", "manager_risk"]
        if self.reviewer is not None: completed.append("ai_reviewer")
        if self.approval is not None: completed.append("human_approval")
        if self.execution is not None: completed.append("paper_execution")
        if self.reconciled_at is not None: completed.append("reconciliation")
        if self.no_action:
            return {"completed": tuple(completed), "available_next": (), "blocked": ("NO_EXECUTABLE_TRADES",), "terminal": True, "approval_status": "NOT_APPLICABLE", "execution_status": "NOT_APPLICABLE"}
        if not self.system_safety.passed:
            return {"completed": tuple(completed), "available_next": (), "blocked": ("SYSTEM_SAFETY_FAILED",), "terminal": True, "approval_status": "BLOCKED", "execution_status": "BLOCKED"}
        if self.rejection is not None:
            return {"completed": tuple(completed), "available_next": (), "blocked": ("REJECTED",), "terminal": True, "approval_status": "REJECTED", "execution_status": "BLOCKED"}
        if self.approval is None:
            return {"completed": tuple(completed), "available_next": ("human_approval", "human_rejection"), "blocked": (), "terminal": False, "approval_status": "PENDING", "execution_status": "BLOCKED"}
        if self.execution is None:
            return {"completed": tuple(completed), "available_next": ("paper_execution",), "blocked": (), "terminal": False, "approval_status": "APPROVED", "execution_status": "PENDING"}
        return {"completed": tuple(completed), "available_next": () if self.reconciled_at else ("reconciliation",), "blocked": (), "terminal": self.reconciled_at is not None, "approval_status": "APPROVED", "execution_status": "EXECUTED"}


class V2WeeklyCycleService:
    """Compose #36--#39 artifacts and persist them through the existing run."""
    def __init__(self, store, *, now: Callable[[], datetime]) -> None:
        self._store, self._now = store, now

    def record_preapproval(self, *, universe_snapshot_id: str, screening: ScreeningRunV2, research: ResearchBatchV3, target: PortfolioTargetAllocation, snapshot: V2PriceSnapshot, manager_risk: V2ManagerRiskAssessment, reviewer: V2ReviewerResult | None = None) -> V2CycleArtifacts:
        """Persist artifacts already produced by the authoritative services."""
        state = self._state()
        plan = build_batch_trade_plan(target, state.managed_portfolio, snapshot, created_at=self._now())
        safety = evaluate_batch_plan_safety(plan, evaluated_at=self._now())
        return self._record(state, universe_snapshot_id, screening, research, target, plan, safety, manager_risk, reviewer)

    def _record(self, state, universe_snapshot_id, screening, research, target, plan, safety, manager_risk, reviewer):
        if not isinstance(manager_risk, V2ManagerRiskAssessment):
            raise TypeError("manager_risk must be a V2ManagerRiskAssessment")
        if reviewer is not None and not isinstance(reviewer, V2ReviewerResult):
            raise TypeError("reviewer must be a V2ReviewerResult or None")
        cycle = V2CycleArtifacts(uuid4(), self._now(), state.managed_portfolio, universe_snapshot_id, screening, research, target, plan, safety, manager_risk, reviewer)
        self._store.save_transition(replace(state, v2_cycles=(*getattr(state, "v2_cycles", ()), cycle)))
        return cycle

    def prepare(
        self,
        *,
        snapshot_id: str,
        profile_identity,
        as_of: datetime,
        screening_service,
        research_service,
        manager,
        price_snapshot,
        manager_risk_service: V2ManagerRiskAdvisor,
        reviewer: V2AIReviewer | None = None,
    ) -> V2CycleArtifacts:
        """Compose the bounded V2 weekly preparation path.

        The collaborators are the repository's authoritative universe/screen,
        Research V3, manager, and advisory services.  This façade deliberately
        owns no screening, research, allocation, safety, or review rules.
        """
        state = self._state()
        screening = screening_service.execute(
            snapshot_id=snapshot_id, profile_identity=profile_identity, as_of=as_of
        )
        research = research_service.build(screening_run=screening, portfolio=state.managed_portfolio)
        policy = load_active_value_policy()
        context = ValueManagerDecisionContext(
            portfolio=state.managed_portfolio,
            research_batch=research,
            constitution=ConstitutionLoader.load_value_manager_constitution_v2(),
            manager_risk_constitution=policy.manager_risk_constitution,
        )
        target = manager.decide_v2(context)
        if not isinstance(target, PortfolioTargetAllocation):
            raise TypeError("V2 manager must return PortfolioTargetAllocation")
        # Advisory collaborators return their own typed, provenance-bearing
        # artifacts.  Nothing here derives a status string from a successful
        # target diff.
        snapshot = price_snapshot if isinstance(price_snapshot, V2PriceSnapshot) else price_snapshot.snapshot(state.managed_portfolio, target)
        if not isinstance(snapshot, V2PriceSnapshot):
            raise TypeError("V2 price snapshot provider must return V2PriceSnapshot")
        plan = build_batch_trade_plan(target, state.managed_portfolio, snapshot, created_at=self._now())
        safety = evaluate_batch_plan_safety(plan, evaluated_at=self._now())
        manager_risk = manager_risk_service.assess(portfolio=state.managed_portfolio, target=target, plan=plan, research=research, assessed_at=self._now())
        review = None if reviewer is None else reviewer.review(portfolio=state.managed_portfolio, target=target, plan=plan, system_safety=safety, manager_risk=manager_risk, research=research, reviewed_at=self._now())
        return self._record(state, snapshot_id, screening, research, target, plan, safety, manager_risk, review)

    def approve(self, cycle_id: UUID, *, decision_maker_id: str, decided_at: datetime) -> V2CycleArtifacts:
        state, cycle = self._cycle(cycle_id)
        if cycle.no_action: raise ValueError("no-action V2 cycle cannot be approved")
        if not cycle.system_safety.passed: raise ValueError("System Safety must pass before approval")
        if cycle.rejection is not None: raise ValueError("rejected V2 cycle cannot be approved")
        if cycle.approval is not None: raise ValueError("V2 cycle already has immutable approval")
        return self._replace(state, cycle, replace(cycle, approval=BatchApproval(cycle.plan, decision_maker_id, decided_at)))

    def reject(self, cycle_id: UUID, *, decision_maker_id: str, decided_at: datetime, reason: str | None = None) -> V2CycleArtifacts:
        state, cycle = self._cycle(cycle_id)
        if cycle.no_action: raise ValueError("no-action V2 cycle cannot be rejected")
        if cycle.approval is not None or cycle.rejection is not None: raise ValueError("V2 cycle already has an immutable human outcome")
        return self._replace(state, cycle, replace(cycle, rejection=BatchRejection(cycle.plan, decision_maker_id, decided_at, reason)))

    def get(self, cycle_id: UUID) -> V2CycleArtifacts:
        return self._cycle(cycle_id)[1]

    def execute(self, cycle_id: UUID, *, executed_at: datetime) -> V2CycleArtifacts:
        state, cycle = self._cycle(cycle_id)
        if cycle.approval is None: raise ValueError("V2 execution requires exact human approval")
        if cycle.rejection is not None: raise ValueError("rejected V2 cycle cannot be executed")
        if cycle.execution is not None: raise ValueError("V2 cycle already executed")
        execution = execute_approved_batch(cycle.approval, state.managed_portfolio, cycle.plan.price_snapshot, executed_at=executed_at)
        # The internal simulator is the #41 paper backend.  Its resulting
        # Portfolio, not a frontend reconstruction, becomes the run's current
        # account state and receives a normal durable valuation snapshot.
        observations = cycle.plan.price_snapshot.observations
        first = observations[0]
        valuation = PortfolioValuation.from_portfolio(
            execution.resulting_portfolio, observations, as_of_timestamp=executed_at,
            market_date=first.market_date, source_price_timestamp=first.observed_at,
            source_provider_identity=first.source_provider_identity,
            price_convention=first.price_convention,
        )
        updated_cycle = replace(cycle, execution=execution, reconciled_at=executed_at)
        cycles = tuple(updated_cycle if item == cycle else item for item in state.v2_cycles)
        self._store.save_transition(replace(
            state, v2_cycles=cycles, managed_portfolio=execution.resulting_portfolio,
            managed_history=state.managed_history.append(execution.resulting_portfolio, valuation),
            price_observations=(*state.price_observations, *observations),
        ))
        return updated_cycle

    def _state(self):
        state = self._store.open_run()
        if state is None: raise ValueError("local SQLite run has not been initialized")
        return state
    def _cycle(self, cycle_id):
        state = self._state(); cycle = next((x for x in getattr(state, "v2_cycles", ()) if x.cycle_id == cycle_id), None)
        if cycle is None: raise ValueError("unknown V2 cycle")
        return state, cycle
    def _replace(self, state, old, new):
        cycles = tuple(new if item == old else item for item in state.v2_cycles)
        self._store.save_transition(replace(state, v2_cycles=cycles))
        return new
