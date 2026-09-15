from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from agentic_portfolio_lab.application.v2_prices import MarketDataV2PriceSnapshotProvider
from agentic_portfolio_lab.domain import CashBalance, CashClassification, CashTarget, Portfolio, PortfolioTargetAllocation


NOW = datetime(2026, 9, 15, 12, tzinfo=timezone.utc)


def test_provider_returns_empty_snapshot_for_all_cash_portfolio_and_target() -> None:
    portfolio = Portfolio(uuid4(), "all cash", "USD", Decimal("100"), CashBalance("USD", Decimal("100")), NOW, ())
    target = PortfolioTargetAllocation(
        portfolio.portfolio_id, "cash", "risk", "concentration", "SPY", 
        CashTarget(Decimal("1"), CashClassification.STRATEGIC, "intentional"), (),
    )

    class NoQuotesExpected:
        def get_current_quote(self, security):
            raise AssertionError(f"unexpected quote request for {security}")

    snapshot = MarketDataV2PriceSnapshotProvider(NoQuotesExpected()).snapshot(portfolio, target)

    assert snapshot.observations == ()
