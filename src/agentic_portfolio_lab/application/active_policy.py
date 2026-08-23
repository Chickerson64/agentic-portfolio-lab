"""Narrow repository-owned active policy selection for the single Value manager."""

from __future__ import annotations

from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.policy import CurrentPolicyReference, InvestmentConstitutionReference, PolicyLoader


def load_active_value_policy() -> CurrentPolicyReference:
    """Return the one approved current Value policy set, with exact identities."""
    investment = InvestmentConstitutionReference.from_constitution(
        ConstitutionLoader.load_value_manager_constitution_v2()
    )
    risk = PolicyLoader.load_value_manager_risk_constitution_v2(
        compatible_investment_constitution=investment
    )
    return CurrentPolicyReference(
        investment_constitution=investment,
        system_safety_envelope=PolicyLoader.load_system_safety_envelope_v1(),
        manager_risk_constitution=risk,
    )
