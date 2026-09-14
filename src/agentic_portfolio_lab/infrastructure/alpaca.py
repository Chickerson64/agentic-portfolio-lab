"""Alpaca HTTP adapter; all Alpaca response details end at this boundary."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agentic_portfolio_lab.domain.market_data import CurrentQuote, DailyBar, MarketDataConfigurationError, MarketDataError, MarketDataProvider
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.universe_snapshots import EligibilityOutcome, UniverseEligibilityRules, UniverseSnapshot

ASSETS_URL = "https://paper-api.alpaca.markets/v2/assets"
DATA_URL = "https://data.alpaca.markets/v2/stocks"
# 100 daily symbols keeps a URL comfortably small even for twelve-character
# symbols, while a roughly three-month screening lookback normally fits below
# Alpaca's 10,000-bar page limit. Pagination remains mandatory and authoritative.
DAILY_BAR_SYMBOL_BATCH_SIZE = 100
HISTORICAL_FEED_ENVIRONMENT_VARIABLE = "ALPACA_HISTORICAL_FEED"
# These are the stock-historical-bars feeds documented by Alpaca.  Latest
# quote feeds are intentionally configured separately and remain unchanged.
SUPPORTED_HISTORICAL_BAR_FEEDS = frozenset({"iex", "sip", "boats", "otc"})
JsonTransport = Callable[[str, Mapping[str, str]], object]
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


@dataclass(frozen=True, slots=True)
class AlpacaAssetRecord:
    """The small provider payload needed to evaluate a listed U.S. asset."""

    asset_id: str
    symbol: str
    exchange: str
    asset_class: str
    status: str
    tradable: bool
    fractionable: bool

    def __post_init__(self) -> None:
        for field in ("asset_id", "symbol", "exchange", "asset_class", "status"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ValueError(f"{field} must be non-empty text")
        if not isinstance(self.tradable, bool) or not isinstance(self.fractionable, bool):
            raise TypeError("tradable and fractionable must be bool")


def _canonical_exchange(value: str) -> str:
    exchange = value.strip().upper().replace("_", " ")
    return {"ARCA": "NYSE ARCA", "NYSEARCA": "NYSE ARCA"}.get(exchange, exchange)


def _parse_timestamp(value: object) -> datetime:
    """Accept only the RFC 3339 representation this adapter supports."""
    if not isinstance(value, str) or _RFC3339.fullmatch(value) is None:
        raise ValueError("timestamp must be RFC 3339")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def evaluate_assets(assets: Sequence[AlpacaAssetRecord], rules: UniverseEligibilityRules) -> tuple[EligibilityOutcome, ...]:
    """Apply repository rules without claiming Alpaca knows stock versus ETF."""
    if not isinstance(rules, UniverseEligibilityRules):
        raise TypeError("rules must be UniverseEligibilityRules")
    if not all(isinstance(asset, AlpacaAssetRecord) for asset in assets):
        raise TypeError("assets must contain AlpacaAssetRecord")
    allowed_exchanges = set(rules.allowed_exchanges)
    outcomes: list[EligibilityOutcome] = []
    for asset in sorted(assets, key=lambda item: (item.symbol.strip().upper(), item.asset_id)):
        symbol = asset.symbol.strip().upper()
        reason: str | None = None
        if not symbol or len(symbol) > rules.max_symbol_length or not symbol.isascii() or not symbol.replace("-", "").replace(".", "").isalnum():
            reason = "invalid_symbol"
        elif asset.asset_class.strip().lower() != "us_equity":
            reason = "unsupported_asset_class"
        elif asset.status.strip().lower() != "active":
            reason = "inactive"
        elif _canonical_exchange(asset.exchange) not in allowed_exchanges:
            reason = "unsupported_exchange"
        elif rules.require_tradable and not asset.tradable:
            reason = "not_tradable"
        elif rules.require_fractionable and not asset.fractionable:
            reason = "not_fractionable"
        identity = None if reason else SecurityIdentity(symbol, "US_EQUITY", _canonical_exchange(asset.exchange), "USD")
        outcomes.append(EligibilityOutcome(symbol, reason is None, reason or "eligible", identity))
    return tuple(outcomes)


class AlpacaClient(MarketDataProvider):
    """Read-only Alpaca assets/daily-data client. It never places orders."""

    @property
    def provider_identity(self) -> str:
        return "alpaca"

    def __init__(self, *, transport: JsonTransport | None = None) -> None:
        self._transport = transport or self._request

    def _credentials(self) -> tuple[str, str]:
        key_id = os.environ.get("ALPACA_API_KEY_ID")
        secret = os.environ.get("ALPACA_API_SECRET_KEY")
        if not key_id or not key_id.strip() or not secret or not secret.strip():
            raise MarketDataConfigurationError("Alpaca credentials are required")
        return key_id, secret

    @staticmethod
    def _historical_feed() -> str:
        configured = os.environ.get(HISTORICAL_FEED_ENVIRONMENT_VARIABLE, "iex")
        if not isinstance(configured, str) or not configured.strip():
            raise MarketDataConfigurationError(f"{HISTORICAL_FEED_ENVIRONMENT_VARIABLE} must select a supported historical stock feed")
        feed = configured.strip().lower()
        if feed not in SUPPORTED_HISTORICAL_BAR_FEEDS:
            raise MarketDataConfigurationError(f"{HISTORICAL_FEED_ENVIRONMENT_VARIABLE} must be one of: {', '.join(sorted(SUPPORTED_HISTORICAL_BAR_FEEDS))}")
        return feed

    @staticmethod
    def _request(url: str, headers: Mapping[str, str]) -> object:
        try:
            with urlopen(Request(url, headers=dict(headers)), timeout=20) as response:  # noqa: S310 -- fixed provider HTTPS URLs
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            # Do not chain the underlying transport exception: it can include a URL or headers.
            raise MarketDataError("Alpaca request failed") from None

    def _get(self, url: str) -> object:
        key_id, secret = self._credentials()
        try:
            return self._transport(url, {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret})
        except Exception:
            raise MarketDataError("Alpaca request failed") from None

    def list_assets(self) -> tuple[AlpacaAssetRecord, ...]:
        raw = self._get(f"{ASSETS_URL}?{urlencode({'status': 'active', 'asset_class': 'us_equity'})}")
        if not isinstance(raw, list):
            raise MarketDataError("Alpaca assets response must be a list")
        try:
            records = tuple(AlpacaAssetRecord(item["id"], item["symbol"], item["exchange"], item["class"], item["status"], item["tradable"], item.get("fractionable", False)) for item in raw if isinstance(item, dict))
            if len(records) != len(raw):
                raise TypeError
            return records
        except (KeyError, TypeError, ValueError):
            raise MarketDataError("Alpaca assets response contains malformed data") from None

    def build_universe_snapshot(self, *, rules: UniverseEligibilityRules, retrieved_at: datetime) -> UniverseSnapshot:
        if not isinstance(rules, UniverseEligibilityRules):
            raise TypeError("rules must be UniverseEligibilityRules")
        if not isinstance(retrieved_at, datetime) or retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        refreshed_at = retrieved_at.astimezone(timezone.utc)
        return UniverseSnapshot(
            snapshot_id=refreshed_at.strftime("alpaca-%Y%m%dT%H%M%S%fZ"),
            provider_identity=self.provider_identity,
            retrieved_at=refreshed_at,
            as_of=refreshed_at,
            rules=rules,
            outcomes=evaluate_assets(self.list_assets(), rules),
            provenance=(("assets_endpoint", "v2/assets?status=active&asset_class=us_equity"), ("security_type", "US_EQUITY means Alpaca mixed us_equity; stock/ETF classification is not asserted")),
        )

    def get_daily_bars(self, security: SecurityIdentity, *, start: date, end: date) -> Sequence[DailyBar]:
        if not isinstance(security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        if isinstance(start, datetime) or isinstance(end, datetime) or not isinstance(start, date) or not isinstance(end, date) or start > end:
            raise ValueError("daily-bar date range is invalid")
        params: dict[str, str] = {"timeframe": "1Day", "start": start.isoformat(), "end": end.isoformat(), "feed": self._historical_feed()}
        raw_bars: list[object] = []
        seen_tokens: set[str] = set()
        while True:
            raw = self._get(f"{DATA_URL}/{security.ticker}/bars?{urlencode(params)}")
            if not isinstance(raw, dict) or any(field in raw for field in ("error", "code", "message")) or not isinstance(raw.get("bars"), list):
                raise MarketDataError("Alpaca bars response is malformed or reported an error")
            raw_bars.extend(raw["bars"])
            token = raw.get("next_page_token")
            if token is None:
                break
            if not isinstance(token, str) or not token.strip():
                raise MarketDataError("Alpaca bars pagination token is malformed")
            if token in seen_tokens:
                raise MarketDataError("Alpaca bars pagination token repeated")
            seen_tokens.add(token)
            params["page_token"] = token
        try:
            bars = tuple(DailyBar(security, _parse_timestamp(item["t"]).date(), *(Decimal(str(item[field])) for field in ("o", "h", "l", "c")), item["v"], self.provider_identity) for item in raw_bars if isinstance(item, dict))
            if len(bars) != len(raw_bars):
                raise TypeError
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise MarketDataError("Alpaca bars response contains malformed data") from None
        dates = tuple(bar.market_date for bar in bars)
        if any(value < start or value > end for value in dates) or dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
            raise MarketDataError("Alpaca bars response has invalid date ordering or range")
        return bars

    def get_daily_bars_batch(
        self, securities: Sequence[SecurityIdentity], *, start: date, end: date
    ) -> Mapping[str, Sequence[DailyBar]]:
        """Fetch historical daily bars in bounded multi-symbol Alpaca requests.

        Alpaca sorts multi-symbol pages by symbol then timestamp, and a page can
        therefore contain only part of one requested symbol.  Each symbol batch
        is exhausted before parsing and validating its complete histories.
        """
        if isinstance(start, datetime) or isinstance(end, datetime) or not isinstance(start, date) or not isinstance(end, date) or start > end:
            raise ValueError("daily-bar date range is invalid")
        requested = tuple(securities)
        if not requested or not all(isinstance(item, SecurityIdentity) for item in requested):
            raise ValueError("securities must be a non-empty sequence of SecurityIdentity")
        requested = tuple(sorted(requested, key=lambda item: item.ticker))
        by_ticker = {item.ticker: item for item in requested}
        if len(by_ticker) != len(requested):
            raise ValueError("daily-bar batch securities must have unique tickers")
        histories: dict[str, list[DailyBar]] = {ticker: [] for ticker in by_ticker}
        for offset in range(0, len(requested), DAILY_BAR_SYMBOL_BATCH_SIZE):
            batch = requested[offset:offset + DAILY_BAR_SYMBOL_BATCH_SIZE]
            params: dict[str, str] = {
                "symbols": ",".join(item.ticker for item in batch), "timeframe": "1Day",
                "start": start.isoformat(), "end": end.isoformat(), "feed": self._historical_feed(), "limit": "10000",
            }
            allowed = {item.ticker: item for item in batch}
            seen_tokens: set[str] = set()
            while True:
                raw = self._get(f"{DATA_URL}/bars?{urlencode(params)}")
                if not isinstance(raw, dict) or any(field in raw for field in ("error", "code", "message")) or not isinstance(raw.get("bars"), dict):
                    raise MarketDataError("Alpaca multi-symbol bars response is malformed or reported an error")
                raw_bars = raw["bars"]
                if any(not isinstance(ticker, str) or ticker not in allowed or not isinstance(values, list) for ticker, values in raw_bars.items()):
                    raise MarketDataError("Alpaca multi-symbol bars response contains an unexpected symbol or history")
                for ticker, values in raw_bars.items():
                    try:
                        parsed = [DailyBar(allowed[ticker], _parse_timestamp(item["t"]).date(), *(Decimal(str(item[field])) for field in ("o", "h", "l", "c")), item["v"], self.provider_identity) for item in values if isinstance(item, dict)]
                        if len(parsed) != len(values):
                            raise TypeError
                    except (KeyError, TypeError, ValueError, InvalidOperation):
                        raise MarketDataError("Alpaca multi-symbol bars response contains malformed data") from None
                    histories[ticker].extend(parsed)
                token = raw.get("next_page_token")
                if token is None:
                    break
                if not isinstance(token, str) or not token.strip():
                    raise MarketDataError("Alpaca bars pagination token is malformed")
                if token in seen_tokens:
                    raise MarketDataError("Alpaca bars pagination token repeated")
                seen_tokens.add(token)
                params["page_token"] = token
        result = {ticker: tuple(values) for ticker, values in histories.items()}
        for ticker, bars in result.items():
            dates = tuple(bar.market_date for bar in bars)
            if any(value < start or value > end for value in dates) or dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
                raise MarketDataError(f"Alpaca multi-symbol bars response has invalid history for {ticker}")
        return result

    def get_current_quote(self, security: SecurityIdentity) -> CurrentQuote:
        if not isinstance(security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        raw = self._get(f"{DATA_URL}/{security.ticker}/quotes/latest?feed=iex")
        if not isinstance(raw, dict) or any(field in raw for field in ("error", "code", "message")) or not isinstance(raw.get("quote"), dict):
            raise MarketDataError("Alpaca quote response is malformed or reported an error")
        quote = raw["quote"]
        try:
            return CurrentQuote(security, Decimal(str(quote["bp"])), Decimal(str(quote["ap"])), _parse_timestamp(quote["t"]), self.provider_identity)
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise MarketDataError("Alpaca quote response contains malformed data") from None
