"""Map persisted provider fundamental records into metric-derivation inputs.

This mapper does not compute FCF, EV, TTM, or yield. Missing or unparseable
facts stay ``None`` so ``derive_fundamental_metrics`` can mark TTM as
``NOT_AVAILABLE`` without annualizing.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence

from agentic_portfolio_lab.application.fundamental_metrics import FundamentalMetricInputs
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.provider_fundamentals import (
    FreshnessClass,
    ProviderEndpoint,
    ProviderFundamentalRecord,
)

_QUARTER_COUNT = 4


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation:
        return None
    return parsed


def _facts(record: ProviderFundamentalRecord | None) -> dict[str, str]:
    if record is None:
        return {}
    return dict(record.facts)


def _latest_record(
    records: Sequence[ProviderFundamentalRecord],
    endpoint: ProviderEndpoint,
    security: SecurityIdentity,
) -> ProviderFundamentalRecord | None:
    matches = [
        record
        for record in records
        if record.endpoint is endpoint and record.security == security
    ]
    if not matches:
        return None
    return max(matches, key=lambda record: record.fetched_at)


def _fact(facts: Mapping[str, str], key: str) -> Decimal | None:
    return _parse_decimal(facts.get(key))


def _period_values(facts: Mapping[str, str], field: str) -> tuple[Decimal | None, ...]:
    return tuple(_fact(facts, f"period_{index}_{field}") for index in range(_QUARTER_COUNT))


def fundamental_metric_inputs_from_records(
    records: Sequence[ProviderFundamentalRecord],
    *,
    price: Decimal | None,
    security: SecurityIdentity,
    input_freshness: Mapping[str, FreshnessClass] | None = None,
) -> FundamentalMetricInputs:
    """Build ``FundamentalMetricInputs`` from per-endpoint records and a cycle price.

    ``period_0_*`` is the latest quarter. ``period_3_*`` shares are shares four
    quarters ago. Quarterly tuples are ``period_0`` through ``period_3`` in order.
    Only records whose exact ``SecurityIdentity`` matches ``security`` are used.
    """

    overview = _facts(_latest_record(records, ProviderEndpoint.OVERVIEW, security))
    income = _facts(_latest_record(records, ProviderEndpoint.INCOME_STATEMENT, security))
    balance = _facts(_latest_record(records, ProviderEndpoint.BALANCE_SHEET, security))
    cash_flow = _facts(_latest_record(records, ProviderEndpoint.CASH_FLOW, security))
    latest_shares = _fact(balance, "period_0_shares_outstanding")
    return FundamentalMetricInputs(
        cash=_fact(balance, "period_0_cash"),
        total_debt=_fact(balance, "period_0_debt"),
        current_assets=_fact(balance, "period_0_current_assets"),
        current_liabilities=_fact(balance, "period_0_current_liabilities"),
        gross_profit=_fact(income, "period_0_gross_profit"),
        operating_income=_fact(income, "period_0_operating_income"),
        net_income=_fact(income, "period_0_net_income"),
        revenue=_fact(income, "period_0_total_revenue"),
        operating_cash_flow=_fact(cash_flow, "period_0_operating_cash_flow"),
        capex=_fact(cash_flow, "period_0_capex"),
        quarterly_revenue=_period_values(income, "total_revenue"),
        quarterly_net_income=_period_values(income, "net_income"),
        quarterly_operating_cash_flow=_period_values(cash_flow, "operating_cash_flow"),
        quarterly_capex=_period_values(cash_flow, "capex"),
        latest_shares=latest_shares,
        shares_4q_ago=_fact(balance, "period_3_shares_outstanding"),
        price=price,
        statement_shares=latest_shares,
        overview_shares=_fact(overview, "shares_outstanding"),
        input_freshness=dict(input_freshness or {}),
    )
