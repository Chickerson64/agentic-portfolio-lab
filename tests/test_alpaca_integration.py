from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from agentic_portfolio_lab.application.refresh_universe import RefreshUniverseService, main
from agentic_portfolio_lab.domain.market_data import MarketDataConfigurationError, MarketDataError
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.universe_snapshots import UniverseEligibilityRules, UniverseSnapshot
from agentic_portfolio_lab.infrastructure.alpaca import DAILY_BAR_SYMBOL_BATCH_SIZE, AlpacaAssetRecord, AlpacaClient, evaluate_assets
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore

NOW = datetime(2026, 9, 12, 15, 0, tzinfo=timezone.utc)
SECURITY = SecurityIdentity("AAPL", "US_EQUITY", "NASDAQ", "USD")


def _assets() -> list[AlpacaAssetRecord]:
    return [
        AlpacaAssetRecord("id-aapl", "aapl", "NASDAQ", "us_equity", "active", True, True),
        AlpacaAssetRecord("id-spy", "SPY", "ARCA", "us_equity", "active", True, True),
        AlpacaAssetRecord("id-old", "OLD", "NYSE", "us_equity", "inactive", True, False),
        AlpacaAssetRecord("id-crypto", "BTCUSD", "CRYPTO", "crypto", "active", True, False),
        AlpacaAssetRecord("id-no", "NOPE", "NYSE", "us_equity", "active", False, False),
    ]


def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_API_KEY_ID", "test-id")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "test-secret")


def test_mixed_us_equity_snapshot_never_infers_etfs_from_symbols() -> None:
    outcomes = evaluate_assets(_assets(), UniverseEligibilityRules())
    by_symbol = {outcome.symbol: outcome for outcome in outcomes}
    assert by_symbol["AAPL"].identity == SECURITY
    assert by_symbol["SPY"].identity.security_type == "US_EQUITY"
    assert by_symbol["NOPE"].reason == "not_tradable"
    assert by_symbol["OLD"].reason == "inactive"
    assert by_symbol["BTCUSD"].reason == "unsupported_asset_class"
    assert not hasattr(UniverseEligibilityRules(), "etf_symbols")


def test_eligibility_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        UniverseEligibilityRules(allowed_exchanges=())
    with pytest.raises(ValueError):
        UniverseEligibilityRules(max_symbol_length=0)
    with pytest.raises(TypeError):
        UniverseEligibilityRules(require_tradable=1)  # type: ignore[arg-type]


def test_snapshot_is_utc_durable_and_reconstructable(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _credentials(monkeypatch)
    # Provider payloads are deliberately plain JSON-shaped dictionaries.
    client = AlpacaClient(transport=lambda _url, _headers: [{"id": item.asset_id, "symbol": item.symbol, "exchange": item.exchange, "class": item.asset_class, "status": item.status, "tradable": item.tradable, "fractionable": item.fractionable} for item in _assets()])
    store = SQLiteLocalRunStore(tmp_path / "state.sqlite")
    mountain_time = datetime(2026, 9, 12, 9, 0, tzinfo=timezone(timedelta(hours=-6)))
    first = RefreshUniverseService(provider=client, state=store, now=lambda: mountain_time).refresh()
    second = RefreshUniverseService(provider=client, state=store, now=lambda: mountain_time).refresh()
    assert first.retrieved_at == NOW and first.as_of == NOW
    assert first.snapshot_id.endswith("Z") and second.snapshot_id.endswith("-2")
    assert store.load_universe_snapshot(first.snapshot_id) == first
    assert store.load_universe_snapshot() == second
    assert "id-aapl" not in first.to_json()
    with pytest.raises(ValueError, match="UTC"):
        UniverseSnapshot("bad", "test", mountain_time, mountain_time, UniverseEligibilityRules(), (), ())
    with pytest.raises(ValueError, match="malformed"):
        UniverseSnapshot.from_json('{"snapshot_id":"missing-required-fields"}')
    with pytest.raises(ValueError, match="as_of"):
        UniverseSnapshot("bad-order", "test", NOW, NOW + timedelta(seconds=1), UniverseEligibilityRules(), (), ())


def test_transport_errors_and_configuration_never_expose_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(MarketDataConfigurationError) as missing:
        AlpacaClient(transport=lambda _url, _headers: []).list_assets()
    assert "ALPACA_API" not in str(missing.value)
    _credentials(monkeypatch)
    client = AlpacaClient(transport=lambda _url, _headers: (_ for _ in ()).throw(RuntimeError("test-secret leaked")))
    with pytest.raises(MarketDataError) as error:
        client.list_assets()
    assert "test-secret" not in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize("timestamp", ["2026-09-10", "2026-09-10T00:00:00", "2026-09-10 00:00:00Z", "2026-09-10T00:00:00Zjunk", "20260910T000000Z"])
def test_bars_reject_non_rfc3339_timestamps(monkeypatch: pytest.MonkeyPatch, timestamp: str) -> None:
    _credentials(monkeypatch)
    client = AlpacaClient(transport=lambda _url, _headers: {"bars": [{"t": timestamp, "o": "10", "h": "12", "l": "9", "c": "11", "v": 1}]})
    with pytest.raises(MarketDataError, match="malformed"):
        client.get_daily_bars(SECURITY, start=date(2026, 9, 1), end=date(2026, 9, 12))


def test_quotes_and_bars_validate_provider_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    _credentials(monkeypatch)
    bad_quote = AlpacaClient(transport=lambda _url, _headers: {"quote": {"bp": "12", "ap": "11", "t": "2026-09-10T00:00:00Z"}})
    with pytest.raises(MarketDataError, match="malformed"):
        bad_quote.get_current_quote(SECURITY)
    invalid_timestamp_quote = AlpacaClient(transport=lambda _url, _headers: {"quote": {"bp": "10", "ap": "11", "t": "2026-09-10 00:00:00Z"}})
    with pytest.raises(MarketDataError, match="malformed"):
        invalid_timestamp_quote.get_current_quote(SECURITY)
    nan_bar = AlpacaClient(transport=lambda _url, _headers: {"bars": [{"t": "2026-09-10T00:00:00Z", "o": "NaN", "h": "12", "l": "9", "c": "11", "v": True}]})
    with pytest.raises(MarketDataError, match="malformed"):
        nan_bar.get_daily_bars(SECURITY, start=date(2026, 9, 1), end=date(2026, 9, 12))


def test_bars_paginate_and_reject_cycles_or_malformed_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _credentials(monkeypatch)
    pages = iter((
        {"bars": [{"t": "2026-09-10T00:00:00Z", "o": "10", "h": "12", "l": "9", "c": "11", "v": 1}], "next_page_token": "next"},
        {"bars": [{"t": "2026-09-11T00:00:00Z", "o": "11", "h": "13", "l": "10", "c": "12", "v": 2}]},
    ))
    bars = AlpacaClient(transport=lambda _url, _headers: next(pages)).get_daily_bars(SECURITY, start=date(2026, 9, 1), end=date(2026, 9, 12))
    assert [bar.close for bar in bars] == [Decimal("11"), Decimal("12")]
    for token in ("repeat", 4, ""):
        client = AlpacaClient(transport=lambda _url, _headers, token=token: {"bars": [], "next_page_token": token})
        if token == "repeat":
            with pytest.raises(MarketDataError, match="repeated"):
                client.get_daily_bars(SECURITY, start=date(2026, 9, 1), end=date(2026, 9, 12))
        else:
            with pytest.raises(MarketDataError, match="token"):
                client.get_daily_bars(SECURITY, start=date(2026, 9, 1), end=date(2026, 9, 12))


def test_multi_symbol_daily_bars_batch_pages_bind_symbols_and_preserve_explicit_missing_histories(monkeypatch: pytest.MonkeyPatch) -> None:
    _credentials(monkeypatch)
    msft = SecurityIdentity("MSFT", "US_EQUITY", "NASDAQ", "USD")
    calls: list[dict[str, list[str]]] = []
    pages = iter((
        {"bars": {"AAPL": [{"t": "2026-09-10T00:00:00Z", "o": "10", "h": "12", "l": "9", "c": "11", "v": 1}]}, "next_page_token": "next"},
        {"bars": {"MSFT": [{"t": "2026-09-11T00:00:00Z", "o": "20", "h": "22", "l": "19", "c": "21", "v": 2}]}},
    ))
    def transport(url, _headers):
        calls.append(parse_qs(urlparse(url).query))
        return next(pages)

    histories = AlpacaClient(transport=transport).get_daily_bars_batch((msft, SECURITY), start=date(2026, 9, 1), end=date(2026, 9, 12))
    assert [call["symbols"] for call in calls] == [["AAPL,MSFT"], ["AAPL,MSFT"]]
    assert calls[0]["limit"] == ["10000"] and calls[1]["page_token"] == ["next"]
    assert histories["AAPL"][0].security is SECURITY
    assert histories["MSFT"][0].security is msft
    missing = SecurityIdentity("NONE", "US_EQUITY", "NASDAQ", "USD")
    empty = AlpacaClient(transport=lambda _url, _headers: {"bars": {}}).get_daily_bars_batch((SECURITY, missing), start=date(2026, 9, 1), end=date(2026, 9, 12))
    assert empty == {"AAPL": (), "NONE": ()}


def test_multi_symbol_daily_bars_use_bounded_calls_and_fail_closed_on_repeated_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    _credentials(monkeypatch)
    securities = tuple(SecurityIdentity(f"S{index:03d}", "US_EQUITY", "NASDAQ", "USD") for index in range(DAILY_BAR_SYMBOL_BATCH_SIZE + 1))
    calls: list[str] = []
    histories = AlpacaClient(transport=lambda url, _headers: calls.append(url) or {"bars": {}}).get_daily_bars_batch(securities, start=date(2026, 9, 1), end=date(2026, 9, 12))
    assert len(calls) == 2 < len(securities)
    assert set(histories) == {security.ticker for security in securities}
    repeated = AlpacaClient(transport=lambda _url, _headers: {"bars": {}, "next_page_token": "again"})
    with pytest.raises(MarketDataError, match="repeated"):
        repeated.get_daily_bars_batch((SECURITY,), start=date(2026, 9, 1), end=date(2026, 9, 12))


def test_configured_historical_feed_applies_to_single_and_batch_bars_and_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _credentials(monkeypatch)
    monkeypatch.setenv("ALPACA_HISTORICAL_FEED", "sip")
    requests: list[dict[str, list[str]]] = []
    def transport(url, _headers):
        query = parse_qs(urlparse(url).query)
        requests.append(query)
        return {"bars": {}} if "symbols" in query else {"bars": []}

    client = AlpacaClient(transport=transport)
    assert client.get_daily_bars(SECURITY, start=date(2026, 9, 1), end=date(2026, 9, 12)) == ()
    assert client.get_daily_bars_batch((SECURITY,), start=date(2026, 9, 1), end=date(2026, 9, 12)) == {"AAPL": ()}
    assert [query["feed"] for query in requests] == [["sip"], ["sip"]]
    monkeypatch.setenv("ALPACA_HISTORICAL_FEED", "delayed_sip")
    with pytest.raises(MarketDataConfigurationError, match="ALPACA_HISTORICAL_FEED"):
        client.get_daily_bars(SECURITY, start=date(2026, 9, 1), end=date(2026, 9, 12))
    with pytest.raises(MarketDataConfigurationError, match="ALPACA_HISTORICAL_FEED"):
        client.get_daily_bars_batch((SECURITY,), start=date(2026, 9, 1), end=date(2026, 9, 12))


def test_documented_refresh_command_is_executable_without_live_transport(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import agentic_portfolio_lab.infrastructure.alpaca as alpaca_module

    class FakeClient:
        provider_identity = "alpaca"

        def build_universe_snapshot(self, *, rules, retrieved_at):
            return UniverseSnapshot("documented-command", "alpaca", retrieved_at, retrieved_at, rules, (), (("fixture", "true"),))

    monkeypatch.setattr(alpaca_module, "AlpacaClient", FakeClient)
    assert main(["--database-path", str(tmp_path / "state.sqlite")]) == 0
    assert SQLiteLocalRunStore(tmp_path / "state.sqlite").load_universe_snapshot("documented-command") is not None
