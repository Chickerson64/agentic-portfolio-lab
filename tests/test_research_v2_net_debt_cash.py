"""Research v2 cash_for_net_debt mapping, provenance, and net-debt/EV formulas."""

from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from agentic_portfolio_lab.application.fundamental_inputs import fundamental_metric_inputs_from_records
from agentic_portfolio_lab.application.fundamental_metrics import FundamentalMetricInputs, derive_fundamental_metrics
from agentic_portfolio_lab.application.local_state_codec import decode, encode
from agentic_portfolio_lab.application.refresh_fundamentals import provider_fundamental_record_from_normalized
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.provider_fundamentals import ProviderEndpoint, ProviderFundamentalRecord
from agentic_portfolio_lab.domain.research import EvidenceItem, MissingData, ResearchPacket, ResearchSection
from agentic_portfolio_lab.domain.research_provider import NormalizedBalanceFacts, SourceResearchRecord
from agentic_portfolio_lab.infrastructure.alpha_vantage import AlphaVantageResearchProvider
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore


UTC = timezone.utc
AS_OF = datetime(2026, 8, 17, 16, tzinfo=UTC)
PERIOD = date(2026, 6, 30)

CCE = "20935000000"
STI = "55908000000"
CASH_FOR_NET_DEBT = "76843000000"
TOTAL_DEBT = "128808300000"
NET_DEBT = Decimal("51965300000")
PREFERRED_TOKEN = "cashAndShortTermInvestments"
CCE_PLUS_STI_TOKEN = "cashAndCashEquivalentsAtCarryingValue+shortTermInvestments"
CCE_TOKEN = "cashAndCashEquivalentsAtCarryingValue"
CURRENT_ASSETS = "207710000000"
CURRENT_LIABILITIES = "168825000000"


def _security() -> SecurityIdentity:
    return SecurityIdentity("ACME", "EQUITY", "NASDAQ", "USD")


def _provider(payload):
    return AlphaVantageResearchProvider(api_key="key", transport=lambda _: payload, sleep=lambda _: None)


def _balance_payload(*reports: dict[str, object]) -> dict[str, object]:
    return {"symbol": "ACME", "quarterlyReports": list(reports)}


def _report(**fields: object) -> dict[str, object]:
    values: dict[str, object] = {"fiscalDateEnding": "2026-06-30", "reportedCurrency": "USD"}
    values.update(fields)
    return values


def _fetch(*reports: dict[str, object]) -> NormalizedBalanceFacts:
    return _provider(_balance_payload(*reports)).fetch_balance_sheet(_security())


def _by_id(metrics):
    return {metric.metric_id: metric for metric in metrics}


def _source() -> SourceResearchRecord:
    return SourceResearchRecord("ALPHA_VANTAGE_BALANCE_SHEET", "Balance", PERIOD, (("cash", "50"),))


def test_preferred_cash_and_short_term_investments_wins_when_cce_and_sti_are_present():
    balance = _fetch(
        _report(
            cashAndShortTermInvestments="999",
            cashAndCashEquivalentsAtCarryingValue=CCE,
            shortTermInvestments=STI,
            shortLongTermDebtTotal=TOTAL_DEBT,
        )
    )

    assert balance.cash == "999"
    assert balance.cash_field == PREFERRED_TOKEN
    assert ("cash_field", PREFERRED_TOKEN) in balance.source.facts
    assert ("cash", "999") in balance.source.facts
    assert balance.cash != CASH_FOR_NET_DEBT


def test_cce_plus_sti_fallback_when_preferred_is_missing_and_both_addends_are_valid():
    balance = _fetch(
        _report(
            cashAndShortTermInvestments="N/A",
            cashAndCashEquivalentsAtCarryingValue=CCE,
            shortTermInvestments=STI,
            shortLongTermDebtTotal=TOTAL_DEBT,
        )
    )

    assert balance.cash == CASH_FOR_NET_DEBT
    assert balance.cash_field == CCE_PLUS_STI_TOKEN
    assert ("cash_field", CCE_PLUS_STI_TOKEN) in balance.source.facts
    assert ("cash", CASH_FOR_NET_DEBT) in balance.source.facts


def test_cce_plus_sti_is_not_used_when_only_one_addend_is_valid():
    sti_only = _fetch(_report(cashAndShortTermInvestments="N/A", shortTermInvestments=STI))
    assert sti_only.cash is None
    assert sti_only.cash_field is None
    assert all(key not in {"cash", "cash_field"} for key, _ in sti_only.source.facts)

    cce_only = _fetch(
        _report(
            cashAndCashEquivalentsAtCarryingValue=CCE,
            shortTermInvestments="N/A",
        )
    )
    assert cce_only.cash == CCE
    assert cce_only.cash_field == CCE_TOKEN


def test_cce_only_degraded_fallback_persists_cce_provenance():
    balance = _fetch(_report(cashAndCashEquivalentsAtCarryingValue="80"))

    assert balance.cash == "80"
    assert balance.cash_field == CCE_TOKEN
    assert ("cash_field", CCE_TOKEN) in balance.source.facts
    assert balance.periods[0].cash_field == CCE_TOKEN


def test_missing_cash_omits_cash_and_cash_field():
    balance = _fetch(_report(shortLongTermDebtTotal="10"))

    assert balance.cash is None
    assert balance.cash_field is None
    assert all(key not in {"cash", "cash_field"} for key, _ in balance.source.facts)


def test_cash_field_and_period_cash_field_survive_sqlite_reopen(tmp_path: Path):
    balance = _fetch(
        _report(
            cashAndShortTermInvestments=CASH_FOR_NET_DEBT,
            cashAndCashEquivalentsAtCarryingValue=CCE,
            shortTermInvestments=STI,
            shortLongTermDebtTotal=TOTAL_DEBT,
        ),
        _report(
            fiscalDateEnding="2026-03-31",
            cashAndCashEquivalentsAtCarryingValue="10",
        ),
    )
    record = provider_fundamental_record_from_normalized(
        _security(),
        ProviderEndpoint.BALANCE_SHEET,
        balance,
        AS_OF,
    )
    assert ("cash_field", PREFERRED_TOKEN) in record.facts
    assert ("period_0_cash_field", PREFERRED_TOKEN) in record.facts
    assert ("period_0_cash", CASH_FOR_NET_DEBT) in record.facts
    assert ("period_1_cash_field", CCE_TOKEN) in record.facts

    store = SQLiteLocalRunStore(tmp_path / "local-run.sqlite")
    initial = store.initialize_run(initialized_at=AS_OF)
    store.save_transition(replace(initial, fundamental_records=(record,)))
    reopened = store.open_run()

    assert reopened is not None
    persisted = reopened.fundamental_records[0]
    facts = dict(persisted.facts)
    assert facts["cash_field"] == PREFERRED_TOKEN
    assert facts["period_0_cash_field"] == PREFERRED_TOKEN
    assert facts["period_0_cash"] == CASH_FOR_NET_DEBT
    assert facts["period_1_cash_field"] == CCE_TOKEN
    assert facts["period_1_cash"] == "10"


def test_msft_smoke_fixture_is_generic_and_matches_locked_amounts():
    preferred = _fetch(
        _report(
            cashAndShortTermInvestments=CASH_FOR_NET_DEBT,
            cashAndCashEquivalentsAtCarryingValue=CCE,
            shortTermInvestments=STI,
            shortLongTermDebtTotal=TOTAL_DEBT,
        )
    )
    assert preferred.cash == CASH_FOR_NET_DEBT
    assert preferred.cash_field == PREFERRED_TOKEN
    assert preferred.debt == TOTAL_DEBT

    summed = _fetch(
        _report(
            cashAndCashEquivalentsAtCarryingValue=CCE,
            shortTermInvestments=STI,
            shortLongTermDebtTotal=TOTAL_DEBT,
        )
    )
    assert summed.cash == CASH_FOR_NET_DEBT
    assert summed.cash_field == CCE_PLUS_STI_TOKEN

    metrics = _by_id(
        derive_fundamental_metrics(
            FundamentalMetricInputs(
                cash=Decimal(CASH_FOR_NET_DEBT),
                total_debt=Decimal(TOTAL_DEBT),
            )
        )
    )
    assert metrics["net_debt"].value == NET_DEBT
    assert not isinstance(metrics["net_debt"].value, MissingData)


def test_negative_net_debt_remains_present():
    metrics = _by_id(
        derive_fundamental_metrics(
            FundamentalMetricInputs(cash=Decimal("40"), total_debt=Decimal("10"))
        )
    )

    assert metrics["net_debt"].value == Decimal("-30")
    assert not isinstance(metrics["net_debt"].value, MissingData)


def test_enterprise_value_uses_the_same_net_debt_including_negative():
    present = _by_id(
        derive_fundamental_metrics(
            FundamentalMetricInputs(
                cash=Decimal("40"),
                total_debt=Decimal("10"),
                price=Decimal("2"),
                statement_shares=Decimal("50"),
            )
        )
    )
    assert present["net_debt"].value == Decimal("-30")
    assert present["market_cap"].value == Decimal("100")
    assert present["enterprise_value"].value == Decimal("70")

    fixture = _by_id(
        derive_fundamental_metrics(
            FundamentalMetricInputs(
                cash=Decimal(CASH_FOR_NET_DEBT),
                total_debt=Decimal(TOTAL_DEBT),
                price=Decimal("2"),
                statement_shares=Decimal("50"),
            )
        )
    )
    assert fixture["enterprise_value"].value == Decimal("100") + NET_DEBT


def test_current_ratio_mapping_and_formula_are_unchanged():
    balance = _fetch(
        _report(
            cashAndShortTermInvestments=CASH_FOR_NET_DEBT,
            totalCurrentAssets=CURRENT_ASSETS,
            totalCurrentLiabilities=CURRENT_LIABILITIES,
        )
    )
    assert balance.current_assets == CURRENT_ASSETS
    assert balance.current_liabilities == CURRENT_LIABILITIES

    metrics = _by_id(
        derive_fundamental_metrics(
            FundamentalMetricInputs(
                current_assets=Decimal(CURRENT_ASSETS),
                current_liabilities=Decimal(CURRENT_LIABILITIES),
            )
        )
    )
    assert metrics["current_ratio"].value == Decimal(CURRENT_ASSETS) / Decimal(CURRENT_LIABILITIES)


def test_legacy_balance_facts_and_records_without_cash_field_remain_decodable():
    facts = NormalizedBalanceFacts(_source(), "2026-06-30", "USD", "80", "25", "120", "40", "1000")
    assert facts.cash_field is None
    assert facts.periods == ()

    document = encode(facts)
    document["fields"].pop("cash_field")
    decoded = decode(document)
    assert isinstance(decoded, NormalizedBalanceFacts)
    assert decoded.cash == "80"
    assert decoded.cash_field is None

    security = _security()
    record = ProviderFundamentalRecord(
        record_id="legacy-balance",
        security=security,
        provider_identity="alpha-vantage",
        endpoint=ProviderEndpoint.BALANCE_SHEET,
        fiscal_period=PERIOD,
        source_date=PERIOD,
        fetched_at=AS_OF,
        facts=(
            ("period_0_cash", "80"),
            ("period_0_debt", "25"),
            ("shortTermInvestments", "50"),
        ),
    )
    inputs = fundamental_metric_inputs_from_records((record,), price=None, security=security)
    assert inputs.cash == Decimal("80")
    assert inputs.total_debt == Decimal("25")

    packet_document = encode(
        ResearchPacket(
            packet_id="rp_acme",
            candidate_id="cand_acme",
            ticker="ACME",
            security_type="EQUITY",
            as_of_timestamp=AS_OF,
            evidence_items=(
                EvidenceItem("ev_01", "FILING", "Quarterly Report", PERIOD, "Revenue grew."),
            ),
            sections=(ResearchSection("business", "Summary", ("ev_01",)),),
        )
    )
    packet_document["fields"].pop("fundamentals", None)
    packet = decode(packet_document)
    assert isinstance(packet, ResearchPacket)
    assert packet.fundamentals is None


def test_mapper_uses_period_0_cash_as_cash_for_net_debt():
    security = _security()
    record = ProviderFundamentalRecord(
        record_id="mapped-balance",
        security=security,
        provider_identity="alpha-vantage",
        endpoint=ProviderEndpoint.BALANCE_SHEET,
        fiscal_period=PERIOD,
        source_date=PERIOD,
        fetched_at=AS_OF,
        facts=(
            ("cash", CASH_FOR_NET_DEBT),
            ("cash_field", PREFERRED_TOKEN),
            ("period_0_cash", CASH_FOR_NET_DEBT),
            ("period_0_cash_field", PREFERRED_TOKEN),
            ("period_0_debt", TOTAL_DEBT),
        ),
    )
    inputs = fundamental_metric_inputs_from_records((record,), price=None, security=security)
    assert inputs.cash == Decimal(CASH_FOR_NET_DEBT)
    metrics = _by_id(derive_fundamental_metrics(inputs))
    assert metrics["net_debt"].value == NET_DEBT


def test_cash_mapping_has_no_issuer_or_ticker_production_branches():
    cash_src = inspect.getsource(AlphaVantageResearchProvider._cash_from_report)
    balance_src = inspect.getsource(AlphaVantageResearchProvider._balance_from_report)
    combined = f"{cash_src}\n{balance_src}"
    for banned in ("MSFT", "CIK", "ticker ==", "security.ticker", "issuer"):
        assert banned not in combined
    generic = _fetch(
        _report(
            cashAndShortTermInvestments=CASH_FOR_NET_DEBT,
            cashAndCashEquivalentsAtCarryingValue=CCE,
            shortTermInvestments=STI,
            shortLongTermDebtTotal=TOTAL_DEBT,
        )
    )
    assert generic.cash == CASH_FOR_NET_DEBT
    assert generic.cash_field == PREFERRED_TOKEN
