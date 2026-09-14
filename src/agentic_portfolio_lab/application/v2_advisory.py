"""Repository-owned V2 advisory services; neither service gates execution."""
from __future__ import annotations

from datetime import datetime

from agentic_portfolio_lab.domain.policy import ManagerRiskConstitution
from agentic_portfolio_lab.domain.v2_advisory import V2AdvisoryStatus, V2ManagerRiskAssessment, V2ReviewerResult


class V2ManagerRiskService:
    """Deterministic application of the active Manager Risk constitution to a target."""
    def __init__(self, constitution: ManagerRiskConstitution) -> None:
        self._constitution = constitution

    def assess(self, *, portfolio, target, plan, research, assessed_at: datetime) -> V2ManagerRiskAssessment:
        weights = tuple(position.target_weight for position in target.positions)
        limit = None if self._constitution.sizing_limits is None else self._constitution.sizing_limits.maximum_total_single_name_target_weight
        findings = tuple(
            f"Largest target weight is {max(weights, default=target.cash_target.weight):.6f}; advisory concentration review retained."
            for _ in [None] if limit is not None and max(weights, default=target.cash_target.weight) > limit
        )
        return V2ManagerRiskAssessment(
            portfolio, target, plan, research, self._constitution,
            V2AdvisoryStatus.ATTENTION if findings else V2AdvisoryStatus.RECORDED,
            findings, "V2 advisory assessment retained the exact target, cash allocation, and deterministic batch plan.",
            assessed_at,
        )


class DeterministicV2Reviewer:
    """Offline reviewer adapter used only when explicitly configured by the host."""
    def review(self, *, portfolio, target, plan, system_safety, manager_risk, research, reviewed_at: datetime) -> V2ReviewerResult:
        findings = manager_risk.findings
        return V2ReviewerResult(
            portfolio, target, plan, system_safety, manager_risk, research,
            V2AdvisoryStatus.ATTENTION if findings else V2AdvisoryStatus.RECORDED,
            findings, "Deterministic V2 reviewer examined target, plan, System Safety, and Manager Risk artifacts.",
            reviewed_at, "deterministic-v2-reviewer", "v1", "deterministic",
        )
