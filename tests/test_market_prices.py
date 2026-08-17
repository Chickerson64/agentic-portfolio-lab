"""Tests for the provider adapter and atomic refresh application service."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError

import pytest

from agentic_portfolio_lab.application.market_configuration import (
    CANDIDATE_UNIVERSE,
    LIVE_PRICE_CANDIDATE_UNIVERSE,
    RESEARCH_CANDIDATE_UNIVERSE,
    SPY_BENCHMARK,
    TWELVE_DATA_FREE_TIER_REQUEST_LIMIT,
)
from agentic_portfolio_lab.application.refresh_prices import InMemoryPriceRefreshState, RefreshPricesService
from agentic_portfolio_lab.domain.market_prices import MarketPriceConfigurationError, MarketPriceError
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.infrastructure import twelve_data
from agentic_portfolio_lab.infrastructure.twelve_data import TwelveDataMarketPriceProvider


MSFT = SecurityIdentity("MSFT", "EQUITY", "NASDAQ", "USD")


def _quote(**overrides: object) -> dict[str, object]:
    return {
        # ``/quote`` documents no response-side ``type`` attribute.
        "symbol": "MSFT", "exchange": "NASDAQ", "currency": "USD",
        "datetime": "2026-08-13 15:59:00",
        "timestamp": 1786651140,
        "last_quote_at": 1786661940,
        "close": "523.123456789",
        **overrides,
    }


def test_twelve_data_quote_maps_direct_decimal_and_provider_truthful_metadata() -> None:
    provider = TwelveDataMarketPriceProvider(api_key="test-key", transport=lambda _: _quote())

    observation = provider.get_observation(MSFT)

    assert observation.security is MSFT
    assert observation.observed_price == Decimal("523.123456789")
    assert observation.currency == "USD"
    assert observation.market_date == date(2026, 8, 13)
    assert observation.observed_at == datetime.fromtimestamp(1786661940, tz=timezone.utc)
    assert observation.source_provider_identity == "twelve-data"
    assert observation.price_convention == "twelve-data-quote-close-field"


def test_twelve_data_quote_request_constrains_equity_type_and_exchange() -> None:
    requests: list[str] = []
    provider = TwelveDataMarketPriceProvider(api_key="test-key", transport=lambda url: requests.append(url) or _quote())

    provider.get_observation(MSFT)

    query = parse_qs(urlparse(requests[0]).query)
    assert query == {
        "symbol": ["MSFT"],
        "exchange": ["NASDAQ"],
        "type": ["Common Stock"],
        "apikey": ["test-key"],
    }


def test_twelve_data_http_error_diagnoses_exact_safe_request_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://api.twelvedata.com/quote?symbol=SPY&exchange=NYSE+ARCA&type=ETF&apikey=secret-key"

    def raise_not_found(request_url: str, *, timeout: int):
        raise HTTPError(request_url, 404, "Not Found", None, None)

    monkeypatch.setattr(twelve_data, "urlopen", raise_not_found)

    with pytest.raises(MarketPriceError) as error:
        twelve_data._live_transport(url)

    assert str(error.value) == "Twelve Data request failed: HTTP 404 for symbol=SPY exchange=NYSE ARCA type=ETF"
    assert "secret-key" not in str(error.value)


def test_twelve_data_spy_etf_request_and_real_style_quote_succeed() -> None:
    requests: list[str] = []
    provider = TwelveDataMarketPriceProvider(
        api_key="test-key",
        transport=lambda url: requests.append(url) or _quote(symbol="SPY", exchange="NYSE", mic_code="ARCX"),
    )

    observation = provider.get_observation(SPY_BENCHMARK)

    assert observation.security is SPY_BENCHMARK
    query = parse_qs(urlparse(requests[0]).query)
    assert query["symbol"] == ["SPY"]
    assert query["exchange"] == ["NYSE"]
    assert query["mic_code"] == ["ARCX"]
    assert query["type"] == ["ETF"]


@pytest.mark.parametrize(
    "payload",
    [
        _quote(symbol="SPY", exchange="NYSE", mic_code="XNYS"),
        _quote(symbol="SPY", exchange="NYSE ARCA", mic_code="ARCX"),
        _quote(symbol="SPY", exchange="NYSEARCA", mic_code="ARCX"),
    ],
)
def test_twelve_data_spy_mapping_rejects_wrong_or_untranslated_provider_exchange_identity(payload: dict[str, object]) -> None:
    provider = TwelveDataMarketPriceProvider(api_key="test-key", transport=lambda _: payload)

    with pytest.raises(MarketPriceError):
        provider.get_observation(SPY_BENCHMARK)


@pytest.mark.parametrize(
    "payload",
    [_quote(datetime="not-a-date"), _quote(last_quote_at=None), _quote(last_quote_at="1786661940"), _quote(last_quote_at=10**100), _quote(close="NaN")],
)
def test_twelve_data_malformed_response_fields_fail(payload: dict[str, object]) -> None:
    provider = TwelveDataMarketPriceProvider(api_key="test-key", transport=lambda _: payload)
    with pytest.raises(MarketPriceError):
        provider.get_observation(MSFT)


@pytest.mark.parametrize(
    "payload",
    [_quote(symbol="AAPL"), _quote(currency="CAD"), _quote(exchange="NYSE")],
)
def test_twelve_data_rejects_returned_symbol_exchange_or_currency_mismatch(payload: dict[str, object]) -> None:
    provider = TwelveDataMarketPriceProvider(api_key="test-key", transport=lambda _: payload)
    with pytest.raises(MarketPriceError):
        provider.get_observation(MSFT)


def test_twelve_data_rejects_unsupported_configured_security_type_before_request() -> None:
    provider = TwelveDataMarketPriceProvider(
        api_key="test-key",
        transport=lambda _: (_ for _ in ()).throw(AssertionError("unsupported security must not request provider")),
    )

    with pytest.raises(MarketPriceError, match="unsupported"):
        provider.get_observation(SecurityIdentity("MSFT", "MUTUAL_FUND", "NASDAQ", "USD"))


def test_twelve_data_last_quote_at_controls_observation_chronology_not_daily_bar_timestamp() -> None:
    daily_bar_open = 1786651140
    latest_minute_quote = 1786661940
    provider = TwelveDataMarketPriceProvider(
        api_key="test-key",
        transport=lambda _: _quote(timestamp=daily_bar_open, last_quote_at=latest_minute_quote),
    )

    observation = provider.get_observation(MSFT)

    assert observation.observed_at == datetime.fromtimestamp(latest_minute_quote, tz=timezone.utc)
    assert observation.observed_at != datetime.fromtimestamp(daily_bar_open, tz=timezone.utc)
    assert observation.market_date == date(2026, 8, 13)


def test_twelve_data_missing_last_quote_at_fails_clearly() -> None:
    provider = TwelveDataMarketPriceProvider(api_key="test-key", transport=lambda _: _quote(last_quote_at=None))
    with pytest.raises(MarketPriceError, match="last quote timestamp"):
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

    assert [security.ticker for security in provider.requested] == [
        "IBM",
        *[security.ticker for security in CANDIDATE_UNIVERSE],
        "SPY",
    ]
    assert state.latest_observations == result.observations
    assert result.provider_identity == "fake-provider"


def test_configured_live_refresh_uses_managed_universe_plus_spy() -> None:
    provider, state = FakeProvider(), InMemoryPriceRefreshState()
    service = RefreshPricesService(
        provider=provider,
        state=state,
        candidate_universe=LIVE_PRICE_CANDIDATE_UNIVERSE,
        spy_benchmark=SPY_BENCHMARK,
    )

    required = service.required_securities(())

    assert LIVE_PRICE_CANDIDATE_UNIVERSE == CANDIDATE_UNIVERSE
    assert len(RESEARCH_CANDIDATE_UNIVERSE) == 5
    assert len(required) == len(CANDIDATE_UNIVERSE) + 1
    assert len(required) > TWELVE_DATA_FREE_TIER_REQUEST_LIMIT
    assert len(set(required)) == len(required)
    assert required[-1] is SPY_BENCHMARK
    assert tuple(required[:-1]) == CANDIDATE_UNIVERSE


def test_refresh_provider_failure_does_not_partially_apply_state() -> None:
    existing = FakeProvider().get_observation(MSFT)
    state = InMemoryPriceRefreshState(); state.apply_price_refresh((existing,))
    provider = FakeProvider(failing_ticker="AAPL")
    service = RefreshPricesService(provider=provider, state=state, candidate_universe=CANDIDATE_UNIVERSE, spy_benchmark=SPY_BENCHMARK)

    with pytest.raises(MarketPriceError, match="AAPL"):
        service.refresh(())
    assert state.latest_observations == (existing,)
