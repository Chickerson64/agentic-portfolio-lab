"""Explicit application configuration for the Phase 3 market universe."""

from __future__ import annotations

from agentic_portfolio_lab.domain.portfolio import SecurityIdentity


def _equity(ticker: str, exchange: str) -> SecurityIdentity:
    return SecurityIdentity(ticker=ticker, security_type="EQUITY", exchange=exchange, currency="USD")


CANDIDATE_UNIVERSE: tuple[SecurityIdentity, ...] = (
    _equity("MSFT", "NASDAQ"), _equity("AAPL", "NASDAQ"), _equity("GOOGL", "NASDAQ"), _equity("AMZN", "NASDAQ"),
    _equity("META", "NASDAQ"), _equity("JPM", "NYSE"), _equity("V", "NYSE"), _equity("COST", "NASDAQ"),
)
# Research-only first-week configuration: 3 calls per candidate stays at 15.
RESEARCH_CANDIDATE_UNIVERSE: tuple[SecurityIdentity, ...] = tuple(security for security in CANDIDATE_UNIVERSE if security.ticker in {"MSFT", "AAPL", "GOOGL", "JPM", "COST"})
SPY_BENCHMARK = SecurityIdentity(ticker="SPY", security_type="ETF", exchange="NYSE ARCA", currency="USD")
