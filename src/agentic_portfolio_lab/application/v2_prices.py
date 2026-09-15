"""Build an attributable V2 target price snapshot from the configured market-data source."""
from __future__ import annotations
from agentic_portfolio_lab.domain.target_execution_v2 import V2PriceSnapshot
from agentic_portfolio_lab.domain.valuation import PriceObservation

class MarketDataV2PriceSnapshotProvider:
    def __init__(self, market_data) -> None: self._market_data = market_data
    def snapshot(self, portfolio, target) -> V2PriceSnapshot:
        securities = {position.security for position in portfolio.positions} | {position.security for position in target.positions}
        observations = []
        for security in sorted(securities, key=lambda item: item.ticker):
            quote = self._market_data.get_current_quote(security)
            price = quote.ask or quote.bid
            observations.append(PriceObservation(security, price, quote.quote_at.date(), quote.quote_at, security.currency, quote.source_provider_identity, "quote"))
        return V2PriceSnapshot(tuple(observations))
