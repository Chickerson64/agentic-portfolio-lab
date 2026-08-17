"""Explicit application configuration for the Phase 3 market universe."""

from __future__ import annotations

from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.universe import CandidateUniverse


def _equity(ticker: str, exchange: str) -> SecurityIdentity:
    return SecurityIdentity(ticker=ticker, security_type="EQUITY", exchange=exchange, currency="USD")


CANDIDATE_UNIVERSE: tuple[SecurityIdentity, ...] = (
    _equity("MSFT", "NASDAQ"), _equity("AAPL", "NASDAQ"), _equity("GOOGL", "NASDAQ"), _equity("AMZN", "NASDAQ"),
    _equity("META", "NASDAQ"), _equity("JPM", "NYSE"), _equity("V", "NYSE"), _equity("COST", "NASDAQ"),
)
# Provisional managed-research universe for Research v2. The Lead will propose
# the final ~30-name operator list for approval; do not expand it here.
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
