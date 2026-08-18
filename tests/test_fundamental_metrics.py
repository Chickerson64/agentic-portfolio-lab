from __future__ import annotations

from decimal import Decimal

from agentic_portfolio_lab.application.fundamental_metrics import FundamentalMetricInputs, derive_fundamental_metrics
from agentic_portfolio_lab.domain.provider_fundamentals import FreshnessClass, ReliabilityClass
from agentic_portfolio_lab.domain.research import MissingData, MissingDataReason


def _by_id(metrics):
    return {metric.metric_id: metric for metric in metrics}


def test_present_formulas_use_locked_ids_and_decimal_math():
    metrics = _by_id(
        derive_fundamental_metrics(
            FundamentalMetricInputs(
                cash=Decimal("10"),
                total_debt=Decimal("40"),
                current_assets=Decimal("20"),
                current_liabilities=Decimal("10"),
                gross_profit=Decimal("4"),
                operating_income=Decimal("3"),
                net_income=Decimal("2"),
                revenue=Decimal("10"),
                operating_cash_flow=Decimal("5"),
                capex=Decimal("-2"),
                quarterly_revenue=(Decimal("10"), Decimal("9"), Decimal("8"), Decimal("7")),
                quarterly_net_income=(Decimal("2"), Decimal("2"), Decimal("1"), Decimal("1")),
                quarterly_operating_cash_flow=(Decimal("5"), Decimal("4"), Decimal("3"), Decimal("2")),
                quarterly_capex=(Decimal("-2"), Decimal("-1"), Decimal("-1"), Decimal("0")),
                latest_shares=Decimal("100"),
                shares_4q_ago=Decimal("90"),
                price=Decimal("2"),
                statement_shares=Decimal("50"),
                overview_shares=Decimal("999"),
            )
        )
    )

    assert set(metrics) == {
        "net_debt",
        "current_ratio",
        "gross_margin",
        "operating_margin",
        "net_margin",
        "fcf",
        "ttm_ocf",
        "ttm_capex",
        "ttm_fcf",
        "ttm_net_income",
        "ttm_revenue",
        "cash_conversion",
        "share_count_change",
        "market_cap",
        "enterprise_value",
        "fcf_yield",
    }
    assert "roic" not in metrics
    assert metrics["net_debt"].value == Decimal("30")
    assert metrics["current_ratio"].value == Decimal("2")
    assert metrics["gross_margin"].value == Decimal("0.4")
    assert metrics["operating_margin"].value == Decimal("0.3")
    assert metrics["net_margin"].value == Decimal("0.2")
    assert metrics["fcf"].value == Decimal("3")
    assert metrics["ttm_ocf"].value == Decimal("14")
    assert metrics["ttm_capex"].value == Decimal("-4")
    assert metrics["ttm_fcf"].value == Decimal("10")
    assert metrics["ttm_net_income"].value == Decimal("6")
    assert metrics["ttm_revenue"].value == Decimal("34")
    assert metrics["cash_conversion"].value == Decimal("14") / Decimal("6")
    assert metrics["share_count_change"].value == Decimal("10")
    assert metrics["market_cap"].value == Decimal("100")
    assert metrics["enterprise_value"].value == Decimal("130")
    assert metrics["fcf_yield"].value == Decimal("10") / Decimal("100")
    assert all(metric.formula_id == metric.metric_id for metric in metrics.values())
    assert all(metric.reliability is ReliabilityClass.DERIVED_DETERMINISTIC for metric in metrics.values())
    assert all(metric.freshness is FreshnessClass.FRESH for metric in metrics.values())


def test_fcf_treats_missing_capex_as_missing_and_does_not_assume_zero():
    metrics = _by_id(
        derive_fundamental_metrics(
            FundamentalMetricInputs(operating_cash_flow=Decimal("5"), capex=None)
        )
    )

    assert metrics["fcf"].value == MissingData(MissingDataReason.NOT_AVAILABLE, "capex is missing")


def test_current_ratio_and_margins_are_missing_when_denominator_is_not_positive():
    metrics = _by_id(
        derive_fundamental_metrics(
            FundamentalMetricInputs(
                current_assets=Decimal("10"),
                current_liabilities=Decimal("0"),
                gross_profit=Decimal("1"),
                revenue=Decimal("0"),
            )
        )
    )

    assert isinstance(metrics["current_ratio"].value, MissingData)
    assert metrics["current_ratio"].value.reason is MissingDataReason.NOT_APPLICABLE
    assert isinstance(metrics["gross_margin"].value, MissingData)
    assert metrics["gross_margin"].value.reason is MissingDataReason.NOT_AVAILABLE


def test_ttm_metrics_require_four_valid_quarters():
    metrics = _by_id(
        derive_fundamental_metrics(
            FundamentalMetricInputs(
                quarterly_revenue=(Decimal("10"), Decimal("9"), Decimal("8")),
                quarterly_net_income=(Decimal("2"), Decimal("2"), Decimal("1"), None),
                quarterly_operating_cash_flow=(Decimal("5"), Decimal("4"), Decimal("3"), Decimal("2")),
                quarterly_capex=(Decimal("-2"), Decimal("-1"), None, Decimal("0")),
            )
        )
    )

    for metric_id in ("ttm_revenue", "ttm_net_income", "ttm_fcf"):
        assert metrics[metric_id].value == MissingData(
            MissingDataReason.NOT_AVAILABLE,
            "fewer than four valid quarters",
        )
    assert metrics["ttm_ocf"].value == Decimal("14")


def test_cash_conversion_is_not_applicable_when_ttm_net_income_is_not_positive():
    metrics = _by_id(
        derive_fundamental_metrics(
            FundamentalMetricInputs(
                quarterly_net_income=(Decimal("-1"), Decimal("0"), Decimal("0"), Decimal("0")),
                quarterly_operating_cash_flow=(Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1")),
            )
        )
    )

    assert metrics["cash_conversion"].value == MissingData(
        MissingDataReason.NOT_APPLICABLE,
        "ttm net income is not positive",
    )


def test_share_count_change_and_ev_and_yield_are_explicitly_missing():
    metrics = _by_id(
        derive_fundamental_metrics(
            FundamentalMetricInputs(latest_shares=Decimal("10"), price=Decimal("2"), cash=Decimal("1"))
        )
    )

    assert metrics["share_count_change"].value == MissingData(
        MissingDataReason.NOT_AVAILABLE,
        "fewer than two share-count points",
    )
    assert isinstance(metrics["market_cap"].value, MissingData)
    assert isinstance(metrics["enterprise_value"].value, MissingData)
    assert isinstance(metrics["fcf_yield"].value, MissingData)


def test_negative_net_debt_stays_present_and_feeds_enterprise_value():
    metrics = _by_id(
        derive_fundamental_metrics(
            FundamentalMetricInputs(
                cash=Decimal("40"),
                total_debt=Decimal("10"),
                price=Decimal("2"),
                statement_shares=Decimal("50"),
            )
        )
    )

    assert metrics["net_debt"].value == Decimal("-30")
    assert not isinstance(metrics["net_debt"].value, MissingData)
    assert metrics["enterprise_value"].value == Decimal("70")


def test_freshness_inherits_the_worst_supplied_input():
    metrics = _by_id(
        derive_fundamental_metrics(
            FundamentalMetricInputs(
                cash=Decimal("10"),
                total_debt=Decimal("40"),
                input_freshness={"cash": FreshnessClass.FRESH, "total_debt": FreshnessClass.STALE},
            )
        )
    )

    assert metrics["net_debt"].freshness is FreshnessClass.STALE
    assert metrics["fcf"].freshness is FreshnessClass.FRESH
