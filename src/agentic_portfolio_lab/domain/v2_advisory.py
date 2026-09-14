"""Typed, immutable advisory artifacts for complete V2 portfolio targets."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from .policy import ManagerRiskConstitution
from .portfolio import Portfolio, _require_aware_datetime, _require_non_empty_text
from .portfolio_decisions_v2 import PortfolioTargetAllocation
from .research_v3 import ResearchBatchV3
from .target_execution_v2 import BatchSystemSafetyResult, BatchTradePlan


class V2AdvisoryStatus(StrEnum):
    RECORDED = "RECORDED"
    ATTENTION = "ATTENTION"


@dataclass(frozen=True, slots=True)
class V2ManagerRiskAssessment:
    portfolio: Portfolio
    target: PortfolioTargetAllocation
    plan: BatchTradePlan
    research: ResearchBatchV3
    constitution: ManagerRiskConstitution
    status: V2AdvisoryStatus
    findings: tuple[str, ...]
    rationale: str
    assessed_at: datetime
    provider_identity: str = "deterministic-v2-manager-risk"
    schema_version: str = "v2-manager-risk-v1"

    def __post_init__(self) -> None:
        if self.target.portfolio_id != self.portfolio.portfolio_id or self.plan.target != self.target:
            raise ValueError("V2 Manager Risk must retain exact portfolio and target lineage")
        _require_aware_datetime(self.assessed_at, field_name="assessed_at")
        object.__setattr__(self, "findings", tuple(_require_non_empty_text(x, field_name="finding") for x in self.findings))
        object.__setattr__(self, "rationale", _require_non_empty_text(self.rationale, field_name="rationale"))
        object.__setattr__(self, "provider_identity", _require_non_empty_text(self.provider_identity, field_name="provider_identity"))

    @property
    def target_identity(self) -> str: return self.plan.target_identity
    @property
    def plan_identity(self) -> str: return self.plan.identity


@dataclass(frozen=True, slots=True)
class V2ReviewerResult:
    portfolio: Portfolio
    target: PortfolioTargetAllocation
    plan: BatchTradePlan
    system_safety: BatchSystemSafetyResult
    manager_risk: V2ManagerRiskAssessment
    research: ResearchBatchV3
    status: V2AdvisoryStatus
    findings: tuple[str, ...]
    rationale: str
    reviewed_at: datetime
    reviewer_identity: str
    reviewer_version: str
    provider_identity: str
    model: str | None = None

    def __post_init__(self) -> None:
        if self.target.portfolio_id != self.portfolio.portfolio_id or self.plan.target != self.target:
            raise ValueError("V2 reviewer must retain exact portfolio and target lineage")
        if self.system_safety.plan != self.plan or self.manager_risk.plan != self.plan:
            raise ValueError("V2 reviewer must retain exact safety and Manager Risk lineage")
        _require_aware_datetime(self.reviewed_at, field_name="reviewed_at")
        object.__setattr__(self, "findings", tuple(_require_non_empty_text(x, field_name="finding") for x in self.findings))
        for name in ("rationale", "reviewer_identity", "reviewer_version", "provider_identity"):
            object.__setattr__(self, name, _require_non_empty_text(getattr(self, name), field_name=name))

    @property
    def target_identity(self) -> str: return self.plan.target_identity
    @property
    def plan_identity(self) -> str: return self.plan.identity


@runtime_checkable
class V2ManagerRiskAdvisor(Protocol):
    def assess(self, *, portfolio: Portfolio, target: PortfolioTargetAllocation, plan: BatchTradePlan, research: ResearchBatchV3, assessed_at: datetime) -> V2ManagerRiskAssessment: ...


@runtime_checkable
class V2AIReviewer(Protocol):
    def review(self, *, portfolio: Portfolio, target: PortfolioTargetAllocation, plan: BatchTradePlan, system_safety: BatchSystemSafetyResult, manager_risk: V2ManagerRiskAssessment, research: ResearchBatchV3, reviewed_at: datetime) -> V2ReviewerResult: ...
