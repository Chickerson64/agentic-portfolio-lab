"""Immutable current-state System Safety check performed immediately before execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from .approval import DecisionApproval
from .policy import CurrentPolicyReference
from .portfolio import _require_aware_datetime
from .risk_validation import RiskValidationResult
from .valuation import PriceObservation


@dataclass(frozen=True, slots=True)
class ExecutionSafetyCheck:
    """One immutable execution-time check over an approved current-policy cycle."""

    approval: DecisionApproval
    policy_reference: CurrentPolicyReference
    safety_validation: RiskValidationResult
    checked_at: datetime
    execution_observation: PriceObservation | None
    policy_lineage_matches: bool = True
    policy_lineage_failure_reason: str | None = None
    check_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not isinstance(self.approval, DecisionApproval):
            raise TypeError("approval must be DecisionApproval")
        if not isinstance(self.policy_reference, CurrentPolicyReference):
            raise TypeError("policy_reference must be CurrentPolicyReference")
        if not isinstance(self.safety_validation, RiskValidationResult):
            raise TypeError("safety_validation must be RiskValidationResult")
        if self.safety_validation.decision_result.decision_cycle_id != self.approval.decision_cycle_id:
            raise ValueError("safety validation must belong to approval cycle")
        journal_policy = self.approval.journal_entry.policy_reference
        if not isinstance(journal_policy, CurrentPolicyReference):
            raise ValueError("execution safety checks require a current-policy approval")
        lineage_matches = (
            self.policy_reference.investment_constitution == journal_policy.investment_constitution
            and self.policy_reference.manager_risk_constitution == journal_policy.manager_risk_constitution
        )
        if not isinstance(self.policy_lineage_matches, bool):
            raise TypeError("policy_lineage_matches must be a bool")
        if self.policy_lineage_matches != lineage_matches:
            raise ValueError("policy_lineage_matches must reflect the journaled policy lineage")
        if self.policy_lineage_matches:
            if self.policy_lineage_failure_reason is not None:
                raise ValueError("matching policy lineage must not carry a failure reason")
        elif not isinstance(self.policy_lineage_failure_reason, str) or not self.policy_lineage_failure_reason.strip():
            raise ValueError("mismatched policy lineage requires a failure reason")
        if not isinstance(self.check_id, UUID):
            raise TypeError("check_id must be UUID")
        checked_at = _require_aware_datetime(self.checked_at, field_name="checked_at")
        if checked_at < self.approval.decided_at:
            raise ValueError("checked_at must not precede approval")
        if self.safety_validation.validation_timestamp != checked_at:
            raise ValueError("safety validation timestamp must match checked_at")
        if self.execution_observation != self.safety_validation.price_observation:
            raise ValueError("execution observation must match safety validation price observation")
        if self.execution_observation is not None and self.execution_observation.observed_at > checked_at:
            raise ValueError("execution observation must not postdate check")
        journal_decision = self.approval.journal_entry.decision_result
        checked_decision = self.safety_validation.decision_result
        if (
            checked_decision.recommendation != journal_decision.recommendation
            or checked_decision.produced_at != journal_decision.produced_at
            or checked_decision.context.research_batch != journal_decision.context.research_batch
            or checked_decision.context.constitution != journal_decision.context.constitution
            or checked_decision.context.manager_risk_constitution
            != journal_decision.context.manager_risk_constitution
            or checked_decision.context.prior_reviewer_feedback
            != journal_decision.context.prior_reviewer_feedback
        ):
            raise ValueError("execution check must preserve the approved decision lineage")
        policy_version = (
            self.policy_reference.system_safety_envelope.system_safety_envelope_version.value
        )
        if any(rule.policy_version != policy_version for rule in self.safety_validation.rule_results):
            raise ValueError("execution safety rules must match the checked System Safety policy version")
        object.__setattr__(self, "checked_at", checked_at)

    @property
    def passed(self) -> bool:
        return (
            self.policy_lineage_matches
            and self.safety_validation.passed
            and self.safety_validation.validated_trade is not None
        )

    @property
    def decision_cycle_id(self) -> UUID:
        return self.approval.decision_cycle_id
