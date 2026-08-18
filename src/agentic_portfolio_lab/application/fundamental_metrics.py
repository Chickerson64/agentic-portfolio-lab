"""Deterministic derived fundamental metrics from normalized statement inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Callable, Mapping, Sequence

from agentic_portfolio_lab.domain.provider_fundamentals import FreshnessClass, ReliabilityClass
from agentic_portfolio_lab.domain.research import DerivedMetric, MissingData, MissingDataReason

_METRIC_DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
_FRESHNESS_RANK = {
    FreshnessClass.FRESH: 0,
    FreshnessClass.STALE: 1,
    FreshnessClass.UNKNOWN: 2,
}


def _compute(operation: Callable[[], Decimal]) -> Decimal:
    with localcontext(_METRIC_DECIMAL_CONTEXT):
        return operation()


@dataclass(frozen=True, slots=True)
class FundamentalMetricInputs:
    """Inputs for locked derived metrics.

    ``cash`` is cash_for_net_debt (see ADR-007), not cash-and-equivalents alone.
    """

    cash: Decimal | None = None
    total_debt: Decimal | None = None
    current_assets: Decimal | None = None
    current_liabilities: Decimal | None = None
    gross_profit: Decimal | None = None
    operating_income: Decimal | None = None
    net_income: Decimal | None = None
    revenue: Decimal | None = None
    operating_cash_flow: Decimal | None = None
    capex: Decimal | None = None
    quarterly_revenue: tuple[Decimal | None, ...] = ()
    quarterly_net_income: tuple[Decimal | None, ...] = ()
    quarterly_operating_cash_flow: tuple[Decimal | None, ...] = ()
    quarterly_capex: tuple[Decimal | None, ...] = ()
    latest_shares: Decimal | None = None
    shares_4q_ago: Decimal | None = None
    price: Decimal | None = None
    statement_shares: Decimal | None = None
    overview_shares: Decimal | None = None
    input_freshness: Mapping[str, FreshnessClass] = field(default_factory=dict)


def derive_fundamental_metrics(inputs: FundamentalMetricInputs) -> tuple[DerivedMetric, ...]:
    """Return the locked derived-metric set. ROIC is intentionally omitted."""

    freshness = dict(inputs.input_freshness)
    shares = inputs.statement_shares if inputs.statement_shares is not None else inputs.overview_shares
    share_keys = ("statement_shares",) if inputs.statement_shares is not None else ("overview_shares",)
    net_debt = _difference("net_debt", inputs.total_debt, inputs.cash, ("total_debt", "cash"), freshness)
    current_ratio = _current_ratio(inputs.current_assets, inputs.current_liabilities, freshness)
    gross_margin = _margin("gross_margin", inputs.gross_profit, inputs.revenue, ("gross_profit", "revenue"), freshness)
    operating_margin = _margin("operating_margin", inputs.operating_income, inputs.revenue, ("operating_income", "revenue"), freshness)
    net_margin = _margin("net_margin", inputs.net_income, inputs.revenue, ("net_income", "revenue"), freshness)
    fcf = _free_cash_flow(inputs.operating_cash_flow, inputs.capex, freshness)
    ttm_ocf = _ttm("ttm_ocf", inputs.quarterly_operating_cash_flow, ("quarterly_operating_cash_flow",), freshness)
    ttm_capex = _ttm("ttm_capex", inputs.quarterly_capex, ("quarterly_capex",), freshness)
    ttm_net_income = _ttm("ttm_net_income", inputs.quarterly_net_income, ("quarterly_net_income",), freshness)
    ttm_revenue = _ttm("ttm_revenue", inputs.quarterly_revenue, ("quarterly_revenue",), freshness)
    ttm_fcf = _ttm_free_cash_flow(inputs.quarterly_operating_cash_flow, inputs.quarterly_capex, freshness)
    cash_conversion = _cash_conversion(ttm_ocf, ttm_net_income, freshness)
    share_count_change = _share_count_change(inputs.latest_shares, inputs.shares_4q_ago, freshness)
    market_cap = _market_cap(inputs.price, shares, share_keys, freshness)
    enterprise_value = _enterprise_value(market_cap, net_debt, freshness)
    fcf_yield = _fcf_yield(ttm_fcf, market_cap, freshness)
    return (
        net_debt,
        current_ratio,
        gross_margin,
        operating_margin,
        net_margin,
        fcf,
        ttm_ocf,
        ttm_capex,
        ttm_fcf,
        ttm_net_income,
        ttm_revenue,
        cash_conversion,
        share_count_change,
        market_cap,
        enterprise_value,
        fcf_yield,
    )


def _inherited_freshness(keys: Sequence[str], freshness: Mapping[str, FreshnessClass]) -> FreshnessClass:
    classes = [freshness[key] for key in keys if key in freshness]
    if not classes:
        return FreshnessClass.FRESH
    return max(classes, key=lambda item: _FRESHNESS_RANK[item])


def _present(metric_id: str, value: Decimal, input_keys: Sequence[str], freshness: Mapping[str, FreshnessClass]) -> DerivedMetric:
    return DerivedMetric(
        metric_id=metric_id,
        value=value,
        formula_id=metric_id,
        input_keys=tuple(input_keys),
        reliability=ReliabilityClass.DERIVED_DETERMINISTIC,
        freshness=_inherited_freshness(input_keys, freshness),
    )


def _missing(
    metric_id: str,
    input_keys: Sequence[str],
    freshness: Mapping[str, FreshnessClass],
    missing: MissingData,
) -> DerivedMetric:
    return DerivedMetric(
        metric_id=metric_id,
        value=missing,
        formula_id=metric_id,
        input_keys=tuple(input_keys),
        reliability=ReliabilityClass.DERIVED_DETERMINISTIC,
        freshness=_inherited_freshness(input_keys, freshness),
    )


def _unavailable(metric_id: str, input_keys: Sequence[str], freshness: Mapping[str, FreshnessClass], details: str) -> DerivedMetric:
    return _missing(metric_id, input_keys, freshness, MissingData(MissingDataReason.NOT_AVAILABLE, details))


def _difference(
    metric_id: str,
    left: Decimal | None,
    right: Decimal | None,
    input_keys: Sequence[str],
    freshness: Mapping[str, FreshnessClass],
) -> DerivedMetric:
    if left is None or right is None:
        return _unavailable(metric_id, input_keys, freshness, "required inputs are missing")
    return _present(metric_id, _compute(lambda: left - right), input_keys, freshness)


def _current_ratio(
    current_assets: Decimal | None,
    current_liabilities: Decimal | None,
    freshness: Mapping[str, FreshnessClass],
) -> DerivedMetric:
    keys = ("current_assets", "current_liabilities")
    if current_liabilities is None:
        return _unavailable("current_ratio", keys, freshness, "current liabilities are missing or not positive")
    if current_liabilities <= 0:
        return _missing(
            "current_ratio",
            keys,
            freshness,
            MissingData(MissingDataReason.NOT_APPLICABLE, "current liabilities are missing or not positive"),
        )
    if current_assets is None:
        return _unavailable("current_ratio", keys, freshness, "required inputs are missing")
    return _present("current_ratio", _compute(lambda: current_assets / current_liabilities), keys, freshness)


def _ratio(
    metric_id: str,
    numerator: Decimal | None,
    denominator: Decimal | None,
    input_keys: Sequence[str],
    freshness: Mapping[str, FreshnessClass],
    *,
    non_positive_denominator: MissingData,
) -> DerivedMetric:
    if denominator is None or denominator <= 0:
        return _missing(metric_id, input_keys, freshness, non_positive_denominator)
    if numerator is None:
        return _unavailable(metric_id, input_keys, freshness, "required inputs are missing")
    return _present(metric_id, _compute(lambda: numerator / denominator), input_keys, freshness)


def _margin(
    metric_id: str,
    numerator: Decimal | None,
    revenue: Decimal | None,
    input_keys: Sequence[str],
    freshness: Mapping[str, FreshnessClass],
) -> DerivedMetric:
    return _ratio(
        metric_id,
        numerator,
        revenue,
        input_keys,
        freshness,
        non_positive_denominator=MissingData(MissingDataReason.NOT_AVAILABLE, "revenue is missing or not positive"),
    )


def _free_cash_flow(
    operating_cash_flow: Decimal | None,
    capex: Decimal | None,
    freshness: Mapping[str, FreshnessClass],
) -> DerivedMetric:
    keys = ("operating_cash_flow", "capex")
    if operating_cash_flow is None or capex is None:
        return _unavailable("fcf", keys, freshness, "capex is missing" if capex is None else "required inputs are missing")
    return _present("fcf", _compute(lambda: operating_cash_flow - abs(capex)), keys, freshness)


def _four_valid(values: Sequence[Decimal | None]) -> tuple[Decimal, ...] | None:
    leading = tuple(values[:4])
    if len(leading) < 4 or any(item is None for item in leading):
        return None
    return tuple(item for item in leading if item is not None)


def _ttm(
    metric_id: str,
    values: Sequence[Decimal | None],
    input_keys: Sequence[str],
    freshness: Mapping[str, FreshnessClass],
) -> DerivedMetric:
    valid = _four_valid(values)
    if valid is None:
        return _unavailable(metric_id, input_keys, freshness, "fewer than four valid quarters")
    return _present(metric_id, _compute(lambda: sum(valid, start=Decimal("0"))), input_keys, freshness)


def _ttm_free_cash_flow(
    quarterly_ocf: Sequence[Decimal | None],
    quarterly_capex: Sequence[Decimal | None],
    freshness: Mapping[str, FreshnessClass],
) -> DerivedMetric:
    keys = ("quarterly_operating_cash_flow", "quarterly_capex")
    ocf = _four_valid(quarterly_ocf)
    capex = _four_valid(quarterly_capex)
    if ocf is None or capex is None:
        return _unavailable("ttm_fcf", keys, freshness, "fewer than four valid quarters")
    quarterly = tuple(
        _compute(lambda ocf_value=ocf_value, capex_value=capex_value: ocf_value - abs(capex_value))
        for ocf_value, capex_value in zip(ocf, capex, strict=True)
    )
    return _present("ttm_fcf", _compute(lambda: sum(quarterly, start=Decimal("0"))), keys, freshness)


def _cash_conversion(
    ttm_ocf: DerivedMetric,
    ttm_net_income: DerivedMetric,
    freshness: Mapping[str, FreshnessClass],
) -> DerivedMetric:
    keys = ("quarterly_operating_cash_flow", "quarterly_net_income")
    ocf_value = ttm_ocf.value
    net_income_value = ttm_net_income.value
    if isinstance(ocf_value, MissingData) or isinstance(net_income_value, MissingData):
        return _unavailable("cash_conversion", keys, freshness, "fewer than four valid quarters")
    if net_income_value <= 0:
        return _missing(
            "cash_conversion",
            keys,
            freshness,
            MissingData(MissingDataReason.NOT_APPLICABLE, "ttm net income is not positive"),
        )
    return _present("cash_conversion", _compute(lambda: ocf_value / net_income_value), keys, freshness)


def _share_count_change(
    latest_shares: Decimal | None,
    shares_4q_ago: Decimal | None,
    freshness: Mapping[str, FreshnessClass],
) -> DerivedMetric:
    keys = ("latest_shares", "shares_4q_ago")
    if latest_shares is None or shares_4q_ago is None:
        return _unavailable("share_count_change", keys, freshness, "fewer than two share-count points")
    return _present("share_count_change", _compute(lambda: latest_shares - shares_4q_ago), keys, freshness)


def _market_cap(
    price: Decimal | None,
    shares: Decimal | None,
    share_keys: Sequence[str],
    freshness: Mapping[str, FreshnessClass],
) -> DerivedMetric:
    keys = ("price", *share_keys)
    if price is None or shares is None:
        return _unavailable("market_cap", keys, freshness, "required inputs are missing")
    return _present("market_cap", _compute(lambda: price * shares), keys, freshness)


def _enterprise_value(
    market_cap: DerivedMetric,
    net_debt: DerivedMetric,
    freshness: Mapping[str, FreshnessClass],
) -> DerivedMetric:
    keys = ("price", "statement_shares", "overview_shares", "total_debt", "cash")
    market_cap_value = market_cap.value
    net_debt_value = net_debt.value
    if isinstance(market_cap_value, MissingData) or isinstance(net_debt_value, MissingData):
        return _unavailable("enterprise_value", keys, freshness, "required inputs are missing")
    return _present("enterprise_value", _compute(lambda: market_cap_value + net_debt_value), keys, freshness)


def _fcf_yield(
    ttm_fcf: DerivedMetric,
    market_cap: DerivedMetric,
    freshness: Mapping[str, FreshnessClass],
) -> DerivedMetric:
    keys = ("quarterly_operating_cash_flow", "quarterly_capex", "price", "statement_shares", "overview_shares")
    ttm_fcf_value = ttm_fcf.value
    market_cap_value = market_cap.value
    if isinstance(ttm_fcf_value, MissingData) or isinstance(market_cap_value, MissingData):
        return _unavailable("fcf_yield", keys, freshness, "required inputs are missing")
    if market_cap_value <= 0:
        return _missing(
            "fcf_yield",
            keys,
            freshness,
            MissingData(MissingDataReason.NOT_AVAILABLE, "market cap is missing or not positive"),
        )
    return _present("fcf_yield", _compute(lambda: ttm_fcf_value / market_cap_value), keys, freshness)
