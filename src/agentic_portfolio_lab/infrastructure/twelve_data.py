"""Twelve Data adapter for the provider-neutral market-price boundary."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, cast
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

from agentic_portfolio_lab.domain.market_prices import MarketPriceConfigurationError, MarketPriceError
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.valuation import PriceObservation

_QUOTE_URL = "https://api.twelvedata.com/quote"
_QUOTE_CLOSE_FIELD_CONVENTION = "twelve-data-quote-close-field"

JsonTransport = Callable[[str], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class _ProviderIdentity:
    """The documented Twelve Data reference identity for one domain security."""

    exchange: str
    instrument_type: str
    mic_code: str | None = None


# This is deliberately an exact provider translation, not display-name
# normalization.  The canonical domain benchmark remains ``NYSE ARCA``.
_EXCHANGE_MAPPINGS: dict[str, tuple[str, str]] = {
    "NYSE ARCA": ("NYSE", "ARCX"),
}


def _live_transport(url: str) -> Mapping[str, object]:
    try:
        with urlopen(url, timeout=10) as response:  # noqa: S310 -- fixed HTTPS provider URL
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise MarketPriceError(
            f"Twelve Data request failed: HTTP {error.code} for {_request_identity(url)}"
        ) from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MarketPriceError(f"Twelve Data request failed: {error}") from error
    if not isinstance(payload, dict):
        raise MarketPriceError("Twelve Data response must be a JSON object")
    return cast(Mapping[str, object], payload)


def _request_identity(url: str) -> str:
    """Return safe provider request context without ever exposing ``apikey``."""
    query = parse_qs(urlparse(url).query)
    return " ".join(
        f"{field}={query.get(field, ['<missing>'])[0]}"
        for field in ("symbol", "exchange", "type")
    )


class TwelveDataMarketPriceProvider:
    """Maps Twelve Data's quote response into the existing domain observation.

    ``close`` is retained exactly as Twelve Data labels it.  It is deliberately
    not represented as an official regular-session close.

    The documented ``/quote`` response identifies symbol, exchange, and
    currency, but does not reliably return an instrument ``type``.  This
    adapter therefore constrains the supported domain security type with the
    documented request ``type`` filter and never infers it from a response.
    """

    def __init__(self, *, api_key: str | None = None, transport: JsonTransport = _live_transport) -> None:
        self._api_key = api_key
        self._transport = transport

    def get_observation(self, security: SecurityIdentity) -> PriceObservation:
        api_key = self._api_key or os.environ.get("TWELVE_DATA_API_KEY")
        if not api_key or not api_key.strip():
            raise MarketPriceConfigurationError("TWELVE_DATA_API_KEY is required to refresh Twelve Data prices")

        provider_identity = self._provider_identity(security)
        parameters = {
            "symbol": security.ticker,
            "exchange": provider_identity.exchange,
            "type": provider_identity.instrument_type,
            "apikey": api_key,
        }
        if provider_identity.mic_code is not None:
            parameters["mic_code"] = provider_identity.mic_code
        query = urlencode(
            parameters
        )
        payload = self._transport(f"{_QUOTE_URL}?{query}")
        self._raise_if_provider_error(payload)
        self._require_matching_identity(payload, security, provider_identity)
        price = self._decimal(payload, "close")
        currency = self._text(payload, "currency").upper()
        if currency != security.currency:
            raise MarketPriceError(
                f"Twelve Data currency {currency} does not match configured {security.currency} for {security.ticker}"
            )
        market_date = self._exchange_market_date(payload)
        observed_at = self._last_quote_timestamp(payload)
        return PriceObservation(
            security=security,
            observed_price=price,
            currency=currency,
            market_date=market_date,
            observed_at=observed_at,
            source_provider_identity="twelve-data",
            price_convention=_QUOTE_CLOSE_FIELD_CONVENTION,
        )

    @staticmethod
    def _raise_if_provider_error(payload: Mapping[str, object]) -> None:
        if payload.get("status") == "error" or "code" in payload and "message" in payload:
            message = payload.get("message", "unknown provider error")
            raise MarketPriceError(f"Twelve Data provider error: {message}")

    @staticmethod
    def _text(payload: Mapping[str, object], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise MarketPriceError(f"Twelve Data response lacks a usable {field}")
        return value.strip()

    def _decimal(self, payload: Mapping[str, object], field: str) -> Decimal:
        try:
            value = Decimal(self._text(payload, field))
        except InvalidOperation as error:
            raise MarketPriceError(f"Twelve Data {field} must be a decimal string") from error
        if not value.is_finite() or value <= 0:
            raise MarketPriceError(f"Twelve Data {field} must be a positive finite decimal")
        return value

    def _require_matching_identity(
        self,
        payload: Mapping[str, object],
        security: SecurityIdentity,
        provider_identity: _ProviderIdentity,
    ) -> None:
        if self._text(payload, "symbol").upper() != security.ticker:
            raise MarketPriceError(f"Twelve Data response symbol does not match requested {security.ticker}")
        if self._text(payload, "exchange").upper() != provider_identity.exchange:
            raise MarketPriceError(
                f"Twelve Data response exchange does not match requested provider exchange {provider_identity.exchange}"
            )
        if provider_identity.mic_code is not None and self._text(payload, "mic_code").upper() != provider_identity.mic_code:
            raise MarketPriceError(
                f"Twelve Data response MIC does not match requested provider MIC {provider_identity.mic_code}"
            )

    @staticmethod
    def _provider_identity(security: SecurityIdentity) -> _ProviderIdentity:
        instrument_type = {"EQUITY": "Common Stock", "ETF": "ETF"}.get(security.security_type)
        if instrument_type is None:
            raise MarketPriceError(
                f"Security type {security.security_type!r} is unsupported by Twelve Data quote filtering"
            )
        mapped = _EXCHANGE_MAPPINGS.get(security.exchange)
        if mapped is None:
            return _ProviderIdentity(exchange=security.exchange, instrument_type=instrument_type)
        exchange, mic_code = mapped
        return _ProviderIdentity(exchange=exchange, mic_code=mic_code, instrument_type=instrument_type)

    def _exchange_market_date(self, payload: Mapping[str, object]) -> date:
        # ``datetime`` is the opening datetime of the selected interval.  It
        # supplies the exchange-local market date, not observation chronology.
        value = self._text(payload, "datetime")
        try:
            return date.fromisoformat(value[:10])
        except ValueError as error:
            raise MarketPriceError("Twelve Data datetime cannot establish an exchange market date") from error

    def _last_quote_timestamp(self, payload: Mapping[str, object]) -> datetime:
        # ``timestamp`` is the opening time of the selected interval (daily by
        # default), so it is deliberately never treated as the quote time.
        # Twelve Data documents ``last_quote_at`` as the last minute candle.
        value = payload.get("last_quote_at")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MarketPriceError("Twelve Data response lacks a usable last quote timestamp")
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as error:
            raise MarketPriceError("Twelve Data last quote timestamp is out of range") from error
