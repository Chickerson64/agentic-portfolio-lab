"""Twelve Data adapter for the provider-neutral market-price boundary."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Mapping, cast
from urllib.parse import urlencode
from urllib.request import urlopen

from agentic_portfolio_lab.domain.market_prices import MarketPriceConfigurationError, MarketPriceError
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.valuation import PriceObservation

_QUOTE_URL = "https://api.twelvedata.com/quote"
_QUOTE_CLOSE_FIELD_CONVENTION = "twelve-data-quote-close-field"

JsonTransport = Callable[[str], Mapping[str, object]]


def _live_transport(url: str) -> Mapping[str, object]:
    try:
        with urlopen(url, timeout=10) as response:  # noqa: S310 -- fixed HTTPS provider URL
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MarketPriceError(f"Twelve Data request failed: {error}") from error
    if not isinstance(payload, dict):
        raise MarketPriceError("Twelve Data response must be a JSON object")
    return cast(Mapping[str, object], payload)


class TwelveDataMarketPriceProvider:
    """Maps Twelve Data's quote response into the existing domain observation.

    ``close`` is retained exactly as Twelve Data labels it.  It is deliberately
    not represented as an official regular-session close.
    """

    def __init__(self, *, api_key: str | None = None, transport: JsonTransport = _live_transport) -> None:
        self._api_key = api_key
        self._transport = transport

    def get_observation(self, security: SecurityIdentity) -> PriceObservation:
        api_key = self._api_key or os.environ.get("TWELVE_DATA_API_KEY")
        if not api_key or not api_key.strip():
            raise MarketPriceConfigurationError("TWELVE_DATA_API_KEY is required to refresh Twelve Data prices")

        query = urlencode({"symbol": security.ticker, "apikey": api_key})
        payload = self._transport(f"{_QUOTE_URL}?{query}")
        self._raise_if_provider_error(payload)
        self._require_matching_identity(payload, security)
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

    def _require_matching_identity(self, payload: Mapping[str, object], security: SecurityIdentity) -> None:
        if self._text(payload, "symbol").upper() != security.ticker:
            raise MarketPriceError(f"Twelve Data response symbol does not match requested {security.ticker}")
        if self._identity_text(self._text(payload, "exchange")) != self._identity_text(security.exchange):
            raise MarketPriceError(f"Twelve Data response exchange does not match requested {security.exchange}")
        response_type = self._security_type(self._text(payload, "type"))
        if response_type != security.security_type:
            raise MarketPriceError(
                f"Twelve Data response type {response_type} does not match requested {security.security_type}"
            )

    @staticmethod
    def _identity_text(value: str) -> str:
        """Compare provider display metadata without weakening identity checks."""
        return "".join(character for character in value.upper() if character.isalnum())

    @staticmethod
    def _security_type(value: str) -> str:
        """Map documented Twelve Data instrument labels to domain security types.

        This adapter verifies symbol, exchange, currency, and type. Unknown
        provider type labels fail instead of being guessed or attributed to the
        requested SecurityIdentity.
        """
        normalized = " ".join(value.upper().replace("-", " ").split())
        known_types = {"COMMON STOCK": "EQUITY", "ETF": "ETF"}
        try:
            return known_types[normalized]
        except KeyError as error:
            raise MarketPriceError(f"Twelve Data response type {value!r} cannot verify a SecurityIdentity") from error

    def _exchange_market_date(self, payload: Mapping[str, object]) -> date:
        # Twelve Data documents quote.datetime as exchange-local.  We retain
        # only that supplied calendar date and never use the machine clock.
        value = self._text(payload, "datetime")
        try:
            return date.fromisoformat(value[:10])
        except ValueError as error:
            raise MarketPriceError("Twelve Data datetime cannot establish an exchange market date") from error

    def _last_quote_timestamp(self, payload: Mapping[str, object]) -> datetime:
        # ``timestamp`` is Twelve Data's documented /quote Unix timestamp.
        value = payload.get("timestamp")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MarketPriceError("Twelve Data response lacks a usable quote timestamp")
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as error:
            raise MarketPriceError("Twelve Data quote timestamp is out of range") from error
