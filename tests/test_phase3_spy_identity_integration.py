"""Focused integration checks for canonical SPY identity and read retention."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agentic_portfolio_lab.application.market_configuration import SPY_BENCHMARK
from agentic_portfolio_lab.application.refresh_prices import RefreshPricesService
from agentic_portfolio_lab.application.wave2_commands import BenchmarkFulfillmentService, CashEventService
from agentic_portfolio_lab.domain.benchmark_fulfillment import fulfill_paper_intent
from agentic_portfolio_lab.domain.constitution import PassiveIndexConstitution
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore, SQLiteMvpReadState, SQLitePriceRefreshState


UTC = timezone.utc
START = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)


class _Provider:
    def get_observation(self, security: SecurityIdentity) -> PriceObservation:
        observed_at = START + timedelta(minutes=1)
        return PriceObservation(
            security=security,
            observed_price=Decimal("500"),
            currency="USD",
            market_date=observed_at.date(),
            observed_at=observed_at,
            source_provider_identity="fake-provider",
            price_convention="provider-quote",
        )


def test_canonical_spy_identity_refresh_fund_fulfill_and_read_snapshot(tmp_path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    initial = store.initialize_run(initialized_at=START)
    assert initial.benchmark_portfolio.benchmark_security is SPY_BENCHMARK

    RefreshPricesService(
        provider=_Provider(), state=SQLitePriceRefreshState(store), candidate_universe=(), spy_benchmark=SPY_BENCHMARK,
    ).refresh(())
    CashEventService(store).apply(amount=Decimal("1000"), currency="USD", source="weekly", effective_at=START + timedelta(minutes=1))
    result = BenchmarkFulfillmentService(store).fulfill(fulfilled_at=START + timedelta(minutes=2))

    assert result.status.value == "FULFILLED"
    reopened = SQLiteLocalRunStore(tmp_path / "run.sqlite").open_run()
    observation = next(item for item in reopened.price_observations if item.security == SPY_BENCHMARK)
    assert observation.security == reopened.benchmark_portfolio.benchmark_security == SPY_BENCHMARK
    assert reopened.benchmark_fulfillments[0].price_observation is observation

    snapshot = SQLiteMvpReadState(SQLiteLocalRunStore(tmp_path / "run.sqlite")).snapshot()
    assert len(snapshot.benchmark_fulfillments) == 1
    assert snapshot.benchmark_fulfillments == reopened.benchmark_fulfillments
    assert snapshot.benchmark_fulfillment_status == "FULFILLED"


def test_mismatched_spy_identity_remains_rejected_by_fulfillment(tmp_path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    store.initialize_run(initialized_at=START)
    wrong_spy = SecurityIdentity("SPY", "ETF", "NYSEARCA", "USD")
    CashEventService(store).apply(
        amount=Decimal("1000"), currency="USD", source="weekly", effective_at=START + timedelta(minutes=1)
    )
    observation = PriceObservation(
        wrong_spy, Decimal("500"), START.date(), START + timedelta(minutes=1), "USD", "fake", "quote"
    )
    state = store.open_run()
    assert state is not None
    intent = PassiveIndexConstitution.paper_simulation().evaluate(state.benchmark_portfolio)
    assert intent is not None

    with pytest.raises(ValueError, match="benchmark portfolio may only hold its benchmark security"):
        fulfill_paper_intent(intent, observation, fulfilled_at=START + timedelta(minutes=2))

    SQLitePriceRefreshState(store).apply_price_refresh((observation,))
    result = BenchmarkFulfillmentService(store).fulfill(fulfilled_at=START + timedelta(minutes=1))
    assert result.status.value == "PENDING_NO_ELIGIBLE_PRICE"
