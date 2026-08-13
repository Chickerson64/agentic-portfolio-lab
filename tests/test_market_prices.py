"""Tests for the provider adapter and atomic refresh application service."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import subprocess
import sys
from pathlib import Path

import pytest

from agentic_portfolio_lab.application.market_configuration import CANDIDATE_UNIVERSE, SPY_BENCHMARK
from agentic_portfolio_lab.application.refresh_prices import InMemoryPriceRefreshState, RefreshPricesService
from agentic_portfolio_lab.domain.market_prices import MarketPriceConfigurationError, MarketPriceError
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.infrastructure.twelve_data import TwelveDataMarketPriceProvider


MSFT = SecurityIdentity("MSFT", "EQUITY", "NASDAQ", "USD")


def _quote(**overrides: object) -> dict[str, object]:
    return {
        "symbol": "MSFT", "exchange": "NASDAQ", "type": "Common Stock", "currency": "USD",
        "datetime": "2026-08-13 15:59:00", "timestamp": 1786651140, "close": "523.123456789", **overrides,
    }


def test_twelve_data_quote_maps_direct_decimal_and_provider_truthful_metadata() -> None:
    provider = TwelveDataMarketPriceProvider(api_key="test-key", transport=lambda _: _quote())

    observation = provider.get_observation(MSFT)

    assert observation.security is MSFT
    assert observation.observed_price == Decimal("523.123456789")
    assert observation.currency == "USD"
    assert observation.market_date == date(2026, 8, 13)
    assert observation.observed_at == datetime.fromtimestamp(1786651140, tz=timezone.utc)
    assert observation.source_provider_identity == "twelve-data"
    assert observation.price_convention == "twelve-data-quote-close-field"


@pytest.mark.parametrize(
    "payload",
    [_quote(datetime="not-a-date"), _quote(timestamp=None), _quote(timestamp="1786651140"), _quote(timestamp=10**100), _quote(close="NaN")],
)
def test_twelve_data_malformed_or_identity_mismatched_responses_fail(payload: dict[str, object]) -> None:
    provider = TwelveDataMarketPriceProvider(api_key="test-key", transport=lambda _: payload)
    with pytest.raises(MarketPriceError):
        provider.get_observation(MSFT)


@pytest.mark.parametrize(
    "payload",
    [_quote(symbol="AAPL"), _quote(currency="CAD"), _quote(exchange="NYSE"), _quote(type="ETF")],
)
def test_twelve_data_rejects_any_full_security_identity_mismatch(payload: dict[str, object]) -> None:
    provider = TwelveDataMarketPriceProvider(api_key="test-key", transport=lambda _: payload)
    with pytest.raises(MarketPriceError):
        provider.get_observation(MSFT)


def test_twelve_data_missing_timestamp_fails_clearly() -> None:
    provider = TwelveDataMarketPriceProvider(api_key="test-key", transport=lambda _: _quote(timestamp=None))
    with pytest.raises(MarketPriceError, match="quote timestamp"):
        provider.get_observation(MSFT)


def test_twelve_data_provider_error_and_missing_key_fail_without_demo_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    with pytest.raises(MarketPriceConfigurationError, match="TWELVE_DATA_API_KEY"):
        TwelveDataMarketPriceProvider(transport=lambda _: _quote()).get_observation(MSFT)
    with pytest.raises(MarketPriceError, match="provider error"):
        TwelveDataMarketPriceProvider(api_key="test-key", transport=lambda _: {"status": "error", "message": "credit limit"}).get_observation(MSFT)


def test_provider_contract_does_not_import_or_expose_twelve_data_adapter() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import agentic_portfolio_lab.domain.market_prices; assert 'agentic_portfolio_lab.infrastructure.twelve_data' not in sys.modules"],
        env={"PYTHONPATH": str(root / "src")}, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


class FakeProvider:
    def __init__(self, *, failing_ticker: str | None = None) -> None:
        self.requested: list[SecurityIdentity] = []
        self.failing_ticker = failing_ticker

    def get_observation(self, security: SecurityIdentity) -> PriceObservation:
        self.requested.append(security)
        if security.ticker == self.failing_ticker:
            raise MarketPriceError(f"no price for {security.ticker}")
        return PriceObservation(
            security=security, observed_price=Decimal("100.0001"), currency="USD", market_date=date(2026, 8, 13),
            observed_at=datetime(2026, 8, 13, 20, 0, tzinfo=timezone.utc), source_provider_identity="fake-provider",
            price_convention="fake-source-price",
        )


def test_refresh_selects_held_candidates_and_spy_then_applies_one_complete_set() -> None:
    held = SecurityIdentity("IBM", "EQUITY", "NYSE", "USD")
    provider, state = FakeProvider(), InMemoryPriceRefreshState()
    service = RefreshPricesService(provider=provider, state=state, candidate_universe=CANDIDATE_UNIVERSE, spy_benchmark=SPY_BENCHMARK)

    result = service.refresh((held, CANDIDATE_UNIVERSE[0]))

    assert [security.ticker for security in provider.requested] == ["IBM", "MSFT", "AAPL", "GOOGL", "AMZN", "META", "JPM", "V", "COST", "SPY"]
    assert state.latest_observations == result.observations
    assert result.provider_identity == "fake-provider"


def test_refresh_provider_failure_does_not_partially_apply_state() -> None:
    existing = FakeProvider().get_observation(MSFT)
    state = InMemoryPriceRefreshState(); state.apply_price_refresh((existing,))
    provider = FakeProvider(failing_ticker="AAPL")
    service = RefreshPricesService(provider=provider, state=state, candidate_universe=CANDIDATE_UNIVERSE, spy_benchmark=SPY_BENCHMARK)

    with pytest.raises(MarketPriceError, match="AAPL"):
        service.refresh(())
    assert state.latest_observations == (existing,)
