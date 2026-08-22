"""Explicit application configuration for the Phase 3 market universe."""

from __future__ import annotations

from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.universe import CandidateUniverse


def _equity(ticker: str, exchange: str) -> SecurityIdentity:
    return SecurityIdentity(ticker=ticker, security_type="EQUITY", exchange=exchange, currency="USD")


CANDIDATE_UNIVERSE: tuple[SecurityIdentity, ...] = (
    _equity("MSFT", "NASDAQ"),
    _equity("AAPL", "NASDAQ"),
    _equity("GOOGL", "NASDAQ"),
    _equity("AMZN", "NASDAQ"),
    _equity("META", "NASDAQ"),
    _equity("NVDA", "NASDAQ"),
    _equity("AVGO", "NASDAQ"),
    _equity("ORCL", "NYSE"),
    _equity("CRM", "NYSE"),
    _equity("JPM", "NYSE"),
    _equity("V", "NYSE"),
    _equity("BAC", "NYSE"),
    _equity("GS", "NYSE"),
    _equity("BLK", "NYSE"),
    _equity("UNH", "NYSE"),
    _equity("JNJ", "NYSE"),
    _equity("ABBV", "NYSE"),
    _equity("TMO", "NYSE"),
    _equity("COST", "NASDAQ"),
    _equity("WMT", "NASDAQ"),
    _equity("HD", "NYSE"),
    _equity("PG", "NYSE"),
    _equity("KO", "NYSE"),
    _equity("CAT", "NYSE"),
    _equity("HON", "NASDAQ"),
    _equity("UNP", "NYSE"),
    _equity("XOM", "NYSE"),
    _equity("CVX", "NYSE"),
    _equity("NEE", "NYSE"),
    _equity("LIN", "NYSE"),
)
# Operator-approved managed-research universe for Research v2.
VALUE_US_EQUITIES_V1 = CandidateUniverse(
    universe_version="value-us-equities-v1",
    identities=CANDIDATE_UNIVERSE,
)
# v0.1 adapter-test slice used by Alpha Vantage adapter tests. Weekly
# BuildResearchService screens VALUE_US_EQUITIES_V1; it does not use this tuple
# as the live research universe.
RESEARCH_CANDIDATE_UNIVERSE: tuple[SecurityIdentity, ...] = tuple(
    security
    for security in CANDIDATE_UNIVERSE
    if security.ticker in {"MSFT", "AAPL", "GOOGL", "JPM", "COST"}
)
# Live price refresh covers the full managed universe plus SPY. Full-universe
# refresh may exceed the Twelve Data free-tier per-minute cap; the constant
# documents provider limits but does not block the approved design.
LIVE_PRICE_CANDIDATE_UNIVERSE: tuple[SecurityIdentity, ...] = CANDIDATE_UNIVERSE
TWELVE_DATA_FREE_TIER_REQUEST_LIMIT = 8
ALPHA_VANTAGE_DAILY_REQUEST_LIMIT = 25
SPY_BENCHMARK = SecurityIdentity(ticker="SPY", security_type="ETF", exchange="NYSE ARCA", currency="USD")
