"""Tests for deterministic research screening."""

from __future__ import annotations

from dataclasses import fields
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agentic_portfolio_lab.application.market_configuration import (
    CANDIDATE_UNIVERSE,
    VALUE_US_EQUITIES_V1,
)
from agentic_portfolio_lab.application.screen_research import ScreeningService, screen_research
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.provider_fundamentals import ProviderEndpoint, ProviderFundamentalRecord
from agentic_portfolio_lab.domain.recommendations import PortfolioRecommendation
from agentic_portfolio_lab.domain.screening import ResearchSlotRole
from agentic_portfolio_lab.domain.valuation import PriceObservation

UTC = timezone.utc
AS_OF = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _equity(ticker: str, exchange: str = "NASDAQ") -> SecurityIdentity:
    return SecurityIdentity(ticker=ticker, security_type="EQUITY", exchange=exchange, currency="USD")


GOOGL = _equity("GOOGL")
MSFT = _equity("MSFT")
AAPL = _equity("AAPL")
AMZN = _equity("AMZN")
META = _equity("META")
JPM = _equity("JPM", "NYSE")
V = _equity("V", "NYSE")
COST = _equity("COST")


def _price(security: SecurityIdentity, amount: str, *, observed_at: datetime = AS_OF) -> PriceObservation:
    return PriceObservation(
        security=security,
        observed_price=Decimal(amount),
        market_date=date(2026, 8, 17),
        observed_at=observed_at,
        currency="USD",
        source_provider_identity="fake-provider",
        price_convention="fake-source-price",
    )


def _overview(
    security: SecurityIdentity,
    *,
    record_id: str,
    latest_quarter: str = "2026-06-30",
    fifty_two_week_high: str | None = "200",
    pe_ratio: str | None = "20",
    fetched_at: datetime = datetime(2026, 8, 10, tzinfo=UTC),
) -> ProviderFundamentalRecord:
    facts: list[tuple[str, str]] = [("latest_quarter", latest_quarter)]
    if fifty_two_week_high is not None:
        facts.append(("fifty_two_week_high", fifty_two_week_high))
    if pe_ratio is not None:
        facts.append(("pe_ratio", pe_ratio))
    return ProviderFundamentalRecord(
        record_id=record_id,
        security=security,
        provider_identity="alpha-vantage",
        endpoint=ProviderEndpoint.OVERVIEW,
        fiscal_period=date.fromisoformat(latest_quarter),
        source_date=date.fromisoformat(latest_quarter),
        fetched_at=fetched_at,
        facts=facts,
    )


def _statement(
    security: SecurityIdentity,
    endpoint: ProviderEndpoint,
    *,
    record_id: str,
    fetched_at: datetime,
    source_date: date | None = None,
) -> ProviderFundamentalRecord:
    resolved_source = source_date or fetched_at.date()
    return ProviderFundamentalRecord(
        record_id=record_id,
        security=security,
        provider_identity="alpha-vantage",
        endpoint=endpoint,
        fiscal_period=date(2026, 6, 30),
        source_date=resolved_source,
        fetched_at=fetched_at,
        facts=(("total_revenue", "100"),),
    )


def _mini_universe(*identities: SecurityIdentity):
    from agentic_portfolio_lab.domain.universe import CandidateUniverse

    return CandidateUniverse(universe_version="test-universe", identities=identities)


def _results_by_security(run):
    return {result.security: result for result in run.results}


def _ranked_selected(run) -> tuple[SecurityIdentity, ...]:
    by_security = _results_by_security(run)
    return tuple(
        security
        for security in run.selected
        if by_security[security].slot_role is ResearchSlotRole.RANKED
    )


def _selected_with_role(run, role: ResearchSlotRole) -> SecurityIdentity:
    by_security = _results_by_security(run)
    return next(security for security in run.selected if by_security[security].slot_role is role)


def test_value_us_equities_v1_uses_operator_approved_managed_universe() -> None:
    assert VALUE_US_EQUITIES_V1.universe_version == "value-us-equities-v1"
    assert VALUE_US_EQUITIES_V1.identities == CANDIDATE_UNIVERSE
    assert len(CANDIDATE_UNIVERSE) == 30


def test_ranked_order_prefers_more_discounted_52w_position_over_higher_pe() -> None:
    universe = _mini_universe(GOOGL, MSFT)
    prices = (
        _price(GOOGL, "100"),
        _price(MSFT, "400"),
    )
    records = (
        _overview(
            GOOGL,
            record_id="goog-overview",
            fifty_two_week_high="200",
            pe_ratio="22.1",
        ),
        _overview(
            MSFT,
            record_id="msft-overview",
            fifty_two_week_high="500",
            pe_ratio="35.5",
        ),
    )

    run = screen_research(
        universe=universe,
        price_observations=prices,
        fundamental_records=records,
        screening_run_id=uuid4(),
        as_of=AS_OF,
    )

    ranked = _ranked_selected(run)
    assert ranked[0] is GOOGL
    assert GOOGL in ranked
    assert ranked.index(GOOGL) < ranked.index(MSFT)
    goog_result = _results_by_security(run)[GOOGL]
    assert goog_result.rank_key[0] == "0"
    assert goog_result.rank_key[1] == "000000.500000"
    assert goog_result.rank_key[2] == "000022.100000"
    assert "52-week high of 200" in goog_result.rank_reason


def test_lower_pe_ranks_before_higher_pe_when_52w_position_equal() -> None:
    universe = _mini_universe(GOOGL, MSFT)
    prices = (
        _price(GOOGL, "100"),
        _price(MSFT, "100"),
    )
    records = (
        _overview(
            GOOGL,
            record_id="goog-overview",
            fifty_two_week_high="200",
            pe_ratio="8",
        ),
        _overview(
            MSFT,
            record_id="msft-overview",
            fifty_two_week_high="200",
            pe_ratio="25",
        ),
    )

    run = screen_research(
        universe=universe,
        price_observations=prices,
        fundamental_records=records,
        screening_run_id=uuid4(),
        as_of=AS_OF,
    )

    ranked = _ranked_selected(run)
    assert ranked == (GOOGL, MSFT)
    goog_result = _results_by_security(run)[GOOGL]
    msft_result = _results_by_security(run)[MSFT]
    assert goog_result.rank_key[1] == msft_result.rank_key[1]
    assert goog_result.rank_key[2] == "000008.000000"
    assert msft_result.rank_key[2] == "000025.000000"


def test_missing_current_price_is_ineligible_and_never_selected() -> None:
    universe = _mini_universe(MSFT, AAPL)
    prices = (_price(MSFT, "400"),)
    records = (
        _overview(MSFT, record_id="msft-overview"),
        _overview(AAPL, record_id="aapl-overview"),
    )

    run = screen_research(
        universe=universe,
        price_observations=prices,
        fundamental_records=records,
        screening_run_id=uuid4(),
        as_of=AS_OF,
    )

    aapl_result = next(result for result in run.results if result.security is AAPL)
    assert not aapl_result.eligible
    assert aapl_result.slot_role is None
    assert AAPL not in run.selected
    assert run.selected == (MSFT,)


def test_fewer_than_five_priced_names_selects_only_priced_without_padding() -> None:
    universe = _mini_universe(MSFT, AAPL, GOOGL)
    prices = (_price(MSFT, "400"), _price(AAPL, "150"))
    records = (
        _overview(MSFT, record_id="msft-overview"),
        _overview(AAPL, record_id="aapl-overview"),
        _overview(GOOGL, record_id="goog-overview"),
    )

    run = screen_research(
        universe=universe,
        price_observations=prices,
        fundamental_records=records,
        screening_run_id=uuid4(),
        as_of=AS_OF,
    )

    assert len(run.selected) == 2
    assert GOOGL not in run.selected


def test_coverage_slot_prefers_never_researched_over_recent_statement_fetch() -> None:
    universe = _mini_universe(MSFT, AAPL, GOOGL, AMZN, META, JPM)
    prices = tuple(_price(security, "100") for security in universe.identities)
    records: list[ProviderFundamentalRecord] = []
    for index, security in enumerate(universe.identities):
        records.append(_overview(security, record_id=f"{security.ticker.lower()}-overview"))
    records.append(
        _statement(
            JPM,
            ProviderEndpoint.INCOME_STATEMENT,
            record_id="jpm-income",
            fetched_at=datetime(2026, 8, 16, tzinfo=UTC),
        )
    )
    records.append(
        _statement(
            META,
            ProviderEndpoint.BALANCE_SHEET,
            record_id="meta-balance",
            fetched_at=datetime(2026, 8, 15, tzinfo=UTC),
        )
    )

    run = screen_research(
        universe=universe,
        price_observations=prices,
        fundamental_records=records,
        screening_run_id=uuid4(),
        as_of=AS_OF,
    )

    coverage = _selected_with_role(run, ResearchSlotRole.COVERAGE)
    assert coverage.ticker not in {"JPM", "META"}


def test_reporting_cycle_slot_prefers_oldest_latest_quarter() -> None:
    universe = _mini_universe(MSFT, AAPL, GOOGL, AMZN, META, JPM)
    prices = tuple(_price(security, "100") for security in universe.identities)
    quarter_by_ticker = {
        "MSFT": "2026-06-30",
        "AAPL": "2026-03-31",
        "GOOGL": "2025-12-31",
        "AMZN": "2026-06-30",
        "META": "2026-06-30",
        "JPM": "2026-06-30",
    }
    records: list[ProviderFundamentalRecord] = []
    for security in universe.identities:
        records.append(
            _overview(
                security,
                record_id=f"{security.ticker.lower()}-overview",
                latest_quarter=quarter_by_ticker[security.ticker],
                fifty_two_week_high="100" if security is GOOGL else "200",
                pe_ratio="20",
            )
        )
    records.append(
        _statement(
            GOOGL,
            ProviderEndpoint.INCOME_STATEMENT,
            record_id="goog-income",
            fetched_at=datetime(2026, 8, 16, tzinfo=UTC),
            source_date=date(2026, 6, 30),
        )
    )

    run = screen_research(
        universe=universe,
        price_observations=prices,
        fundamental_records=records,
        screening_run_id=uuid4(),
        as_of=AS_OF,
    )

    reporting = _selected_with_role(run, ResearchSlotRole.REPORTING_CYCLE)
    assert reporting is GOOGL


def test_collision_keeps_ranked_role_and_moves_coverage_to_next_name() -> None:
    universe = _mini_universe(GOOGL, MSFT, AAPL, AMZN, META, JPM)
    prices = tuple(_price(security, "100") for security in universe.identities)
    records: list[ProviderFundamentalRecord] = [
        _overview(
            GOOGL,
            record_id="goog-overview",
            fifty_two_week_high="400",
            pe_ratio="18",
        ),
        _overview(MSFT, record_id="msft-overview", fifty_two_week_high="100", pe_ratio="30"),
        _overview(AAPL, record_id="aapl-overview", fifty_two_week_high="250", pe_ratio="25"),
        _overview(AMZN, record_id="amzn-overview", fifty_two_week_high="200", pe_ratio="22"),
        _overview(META, record_id="meta-overview", fifty_two_week_high="200", pe_ratio="21"),
        _overview(JPM, record_id="jpm-overview", fifty_two_week_high="200", pe_ratio="20"),
    ]
    for security, record_id, fetched_at in (
        (MSFT, "msft-income-old", datetime(2026, 8, 1, tzinfo=UTC)),
        (AAPL, "aapl-income-old", datetime(2026, 8, 2, tzinfo=UTC)),
        (AMZN, "amzn-income-old", datetime(2026, 8, 5, tzinfo=UTC)),
        (META, "meta-income-old", datetime(2026, 8, 3, tzinfo=UTC)),
        (JPM, "jpm-income-old", datetime(2026, 8, 4, tzinfo=UTC)),
    ):
        records.append(
            _statement(
                security,
                ProviderEndpoint.INCOME_STATEMENT,
                record_id=record_id,
                fetched_at=fetched_at,
                source_date=date(2026, 6, 30),
            )
        )

    run = screen_research(
        universe=universe,
        price_observations=prices,
        fundamental_records=records,
        screening_run_id=uuid4(),
        as_of=AS_OF,
    )

    by_security = _results_by_security(run)
    assert by_security[GOOGL].slot_role is ResearchSlotRole.RANKED
    assert _ranked_selected(run)[0] is GOOGL
    coverage = _selected_with_role(run, ResearchSlotRole.COVERAGE)
    assert coverage is MSFT


def test_missing_overview_stays_eligible_and_can_take_coverage_not_ranked() -> None:
    universe = _mini_universe(GOOGL, MSFT, AAPL, AMZN, META)
    prices = tuple(_price(security, "100") for security in universe.identities)
    records = tuple(
        _overview(
            security,
            record_id=f"{security.ticker.lower()}-overview",
            fifty_two_week_high="200",
            pe_ratio="20",
        )
        for security in (MSFT, AAPL, AMZN, META)
    )

    run = screen_research(
        universe=universe,
        price_observations=prices,
        fundamental_records=records,
        screening_run_id=uuid4(),
        as_of=AS_OF,
    )

    goog_result = _results_by_security(run)[GOOGL]
    assert goog_result.eligible
    assert goog_result.slot_role is ResearchSlotRole.COVERAGE
    assert GOOGL in run.selected
    assert GOOGL not in _ranked_selected(run)


def test_reporting_cycle_ignores_missing_latest_quarter_when_known_quarters_exist() -> None:
    universe = _mini_universe(MSFT, AAPL, GOOGL, AMZN, META, JPM, V)
    prices = tuple(_price(security, "100") for security in universe.identities)
    quarter_by_ticker = {
        "MSFT": "2026-06-30",
        "AAPL": "2026-03-31",
        "GOOGL": "2025-12-31",
        "AMZN": "2026-06-30",
        "META": "2026-06-30",
        "JPM": "2026-06-30",
    }
    records: list[ProviderFundamentalRecord] = []
    for security in universe.identities:
        if security is V:
            records.append(
                ProviderFundamentalRecord(
                    record_id="v-overview-no-quarter",
                    security=V,
                    provider_identity="alpha-vantage",
                    endpoint=ProviderEndpoint.OVERVIEW,
                    fiscal_period=None,
                    source_date=date(2026, 6, 30),
                    fetched_at=datetime(2026, 8, 10, tzinfo=UTC),
                    facts=(("fifty_two_week_high", "200"), ("pe_ratio", "20")),
                )
            )
            continue
        records.append(
            _overview(
                security,
                record_id=f"{security.ticker.lower()}-overview",
                latest_quarter=quarter_by_ticker[security.ticker],
                fifty_two_week_high="100" if security is GOOGL else "200",
                pe_ratio="20",
            )
        )
    records.append(
        _statement(
            GOOGL,
            ProviderEndpoint.INCOME_STATEMENT,
            record_id="goog-income",
            fetched_at=datetime(2026, 8, 16, tzinfo=UTC),
            source_date=date(2026, 6, 30),
        )
    )

    run = screen_research(
        universe=universe,
        price_observations=prices,
        fundamental_records=tuple(records),
        screening_run_id=uuid4(),
        as_of=AS_OF,
    )

    reporting = _selected_with_role(run, ResearchSlotRole.REPORTING_CYCLE)
    assert reporting is GOOGL
    v_result = _results_by_security(run)[V]
    assert v_result.eligible
    assert v_result.slot_role is not ResearchSlotRole.REPORTING_CYCLE


def test_portfolio_recommendation_has_no_rank_or_slot_fields() -> None:
    field_names = {field.name for field in fields(PortfolioRecommendation)}
    assert "rank_key" not in field_names
    assert "slot_role" not in field_names
    assert "rank" not in field_names


def test_ambiguous_cycle_prices_fail_closed() -> None:
    universe = _mini_universe(MSFT)
    same_time = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    prices = (_price(MSFT, "400", observed_at=same_time), _price(MSFT, "401", observed_at=same_time))

    with pytest.raises(ValueError, match="ambiguous"):
        screen_research(
            universe=universe,
            price_observations=prices,
            fundamental_records=(_overview(MSFT, record_id="msft-overview"),),
            screening_run_id=uuid4(),
            as_of=AS_OF,
        )


def test_screening_service_delegates_to_screen_research() -> None:
    universe = _mini_universe(MSFT)
    run = ScreeningService().screen(
        universe=universe,
        price_observations=(_price(MSFT, "400"),),
        fundamental_records=(_overview(MSFT, record_id="msft-overview"),),
        screening_run_id=uuid4(),
        as_of=AS_OF,
    )
    assert len(run.selected) == 1
