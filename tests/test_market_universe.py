from __future__ import annotations

import pytest

from agentic_portfolio_lab.application.market_configuration import (
    CANDIDATE_UNIVERSE,
    LIVE_PRICE_CANDIDATE_UNIVERSE,
    RESEARCH_CANDIDATE_UNIVERSE,
    SPY_BENCHMARK,
    VALUE_US_EQUITIES_V1,
)
from agentic_portfolio_lab.application.refresh_prices import RefreshPricesService
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.universe import CandidateUniverse


def _equity(ticker: str, exchange: str) -> SecurityIdentity:
    return SecurityIdentity(ticker=ticker, security_type="EQUITY", exchange=exchange, currency="USD")


APPROVED_VALUE_US_EQUITIES_V1: tuple[tuple[str, str], ...] = (
    ("MSFT", "NASDAQ"),
    ("AAPL", "NASDAQ"),
    ("GOOGL", "NASDAQ"),
    ("AMZN", "NASDAQ"),
    ("META", "NASDAQ"),
    ("NVDA", "NASDAQ"),
    ("AVGO", "NASDAQ"),
    ("ORCL", "NYSE"),
    ("CRM", "NYSE"),
    ("JPM", "NYSE"),
    ("V", "NYSE"),
    ("BAC", "NYSE"),
    ("GS", "NYSE"),
    ("BLK", "NYSE"),
    ("UNH", "NYSE"),
    ("JNJ", "NYSE"),
    ("ABBV", "NYSE"),
    ("TMO", "NYSE"),
    ("COST", "NASDAQ"),
    ("WMT", "NASDAQ"),
    ("HD", "NYSE"),
    ("PG", "NYSE"),
    ("KO", "NYSE"),
    ("CAT", "NYSE"),
    ("HON", "NASDAQ"),
    ("UNP", "NYSE"),
    ("XOM", "NYSE"),
    ("CVX", "NYSE"),
    ("NEE", "NYSE"),
    ("LIN", "NASDAQ"),
)


def test_value_us_equities_v1_matches_operator_approved_snapshot() -> None:
    expected = tuple(_equity(ticker, exchange) for ticker, exchange in APPROVED_VALUE_US_EQUITIES_V1)

    assert VALUE_US_EQUITIES_V1.universe_version == "value-us-equities-v1"
    assert CANDIDATE_UNIVERSE == expected
    assert VALUE_US_EQUITIES_V1.identities == CANDIDATE_UNIVERSE
    assert len(CANDIDATE_UNIVERSE) == 30


def test_managed_universe_identities_are_equity_usd_without_spy_or_etf() -> None:
    assert SPY_BENCHMARK not in CANDIDATE_UNIVERSE
    assert all(identity.security_type == "EQUITY" for identity in CANDIDATE_UNIVERSE)
    assert all(identity.currency == "USD" for identity in CANDIDATE_UNIVERSE)
    assert all(identity.security_type != "ETF" for identity in CANDIDATE_UNIVERSE)


def test_managed_universe_tickers_and_identities_are_unique() -> None:
    tickers = tuple(identity.ticker for identity in CANDIDATE_UNIVERSE)
    assert len(set(tickers)) == len(tickers)
    assert len(set(CANDIDATE_UNIVERSE)) == len(CANDIDATE_UNIVERSE)


def test_live_price_refresh_required_list_is_managed_universe_plus_spy() -> None:
    class _Provider:
        def get_observation(self, security: SecurityIdentity):
            raise AssertionError("live provider calls are forbidden in universe tests")

    service = RefreshPricesService(
        provider=_Provider(),
        state=object(),
        candidate_universe=LIVE_PRICE_CANDIDATE_UNIVERSE,
        spy_benchmark=SPY_BENCHMARK,
    )

    required = service.required_securities(())

    assert LIVE_PRICE_CANDIDATE_UNIVERSE is CANDIDATE_UNIVERSE
    assert len(required) == 31
    assert tuple(required[:-1]) == CANDIDATE_UNIVERSE
    assert required[-1] is SPY_BENCHMARK
    assert SPY_BENCHMARK not in CANDIDATE_UNIVERSE


def test_research_candidate_universe_remains_v01_adapter_slice() -> None:
    assert len(RESEARCH_CANDIDATE_UNIVERSE) == 5
    assert tuple(identity.ticker for identity in RESEARCH_CANDIDATE_UNIVERSE) == (
        "MSFT",
        "AAPL",
        "GOOGL",
        "JPM",
        "COST",
    )
    assert all(identity in CANDIDATE_UNIVERSE for identity in RESEARCH_CANDIDATE_UNIVERSE)


@pytest.mark.parametrize(
    "identity",
    (
        SecurityIdentity("SPY", "ETF", "NYSE ARCA", "USD"),
        SecurityIdentity("QQQ", "ETF", "NASDAQ", "USD"),
    ),
)
def test_candidate_universe_rejects_spy_and_etf(identity: SecurityIdentity) -> None:
    with pytest.raises(ValueError, match="SPY or ETF"):
        CandidateUniverse("value-us-equities-v1", (_equity("AAPL", "NASDAQ"), identity))
