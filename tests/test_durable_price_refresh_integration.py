"""Wave 1 integration checks for durable market-price refreshes."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentic_portfolio_lab.api.app import create_app
from agentic_portfolio_lab.application.market_configuration import CANDIDATE_UNIVERSE, SPY_BENCHMARK
from agentic_portfolio_lab.application.refresh_prices import RefreshPricesService
from agentic_portfolio_lab.domain.market_prices import MarketPriceError
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore, SQLitePriceRefreshState


UTC = timezone.utc
INITIALIZED_AT = datetime(2026, 8, 13, 14, 30, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 8, 13, 20, 0, tzinfo=UTC)


class _FakeMarketPriceProvider:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error

    def get_observation(self, security: SecurityIdentity) -> PriceObservation:
        if self._error is not None:
            raise self._error
        return PriceObservation(
            security=security,
            observed_price=Decimal("101.25"),
            currency="USD",
            market_date=date(2026, 8, 13),
            observed_at=OBSERVED_AT,
            source_provider_identity="fake-market-provider",
            price_convention="fake-close",
        )


def _service(store: SQLiteLocalRunStore, provider: _FakeMarketPriceProvider) -> RefreshPricesService:
    return RefreshPricesService(
        provider=provider,
        state=SQLitePriceRefreshState(store),
        candidate_universe=CANDIDATE_UNIVERSE,
        spy_benchmark=SPY_BENCHMARK,
    )


def test_durable_refresh_api_persists_observations_across_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "local-run.sqlite"
    store = SQLiteLocalRunStore(database_path)
    store.initialize_run(initialized_at=INITIALIZED_AT)
    client = TestClient(create_app(database_path=str(database_path), refresh_service=_service(store, _FakeMarketPriceProvider())))

    response = client.post("/commands/refresh-prices")

    assert response.status_code == 200
    assert response.json()["provider_identity"] == "fake-market-provider"
    assert set(response.json()["refreshed_tickers"]) == {security.ticker for security in (*CANDIDATE_UNIVERSE, SPY_BENCHMARK)}
    assert client.get("/health").json() == {
        "status": "ok",
        "state_mode": "local-sqlite",
        "persisted": True,
        "synthetic": False,
    }
    assert client.get("/dashboard").status_code == 200

    reopened = SQLiteLocalRunStore(database_path).open_run()
    assert reopened is not None
    assert len(reopened.price_observations) == len((*CANDIDATE_UNIVERSE, SPY_BENCHMARK))
    assert all(observation.observed_price == Decimal("101.25") for observation in reopened.price_observations)
    assert all(observation.observed_at == OBSERVED_AT for observation in reopened.price_observations)


def test_provider_failure_leaves_durable_state_unchanged(tmp_path: Path) -> None:
    database_path = tmp_path / "local-run.sqlite"
    store = SQLiteLocalRunStore(database_path)
    initial = store.initialize_run(initialized_at=INITIALIZED_AT)
    client = TestClient(
        create_app(
            database_path=str(database_path),
            refresh_service=_service(store, _FakeMarketPriceProvider(error=MarketPriceError("provider unavailable"))),
        )
    )

    response = client.post("/commands/refresh-prices")

    assert response.status_code == 502
    assert SQLiteLocalRunStore(database_path).open_run() == initial


def test_conflicting_observation_identity_cannot_overwrite_durable_record(tmp_path: Path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "local-run.sqlite")
    store.initialize_run(initialized_at=INITIALIZED_AT)
    refresh_state = SQLitePriceRefreshState(store)
    security = CANDIDATE_UNIVERSE[0]
    original = _FakeMarketPriceProvider().get_observation(security)
    refresh_state.apply_price_refresh((original,))

    with pytest.raises(ValueError, match="price observations must not rewrite persisted artifact"):
        refresh_state.apply_price_refresh((
            PriceObservation(
                security=security,
                observed_price=Decimal("102"),
                currency="USD",
                market_date=original.market_date,
                observed_at=original.observed_at,
                source_provider_identity=original.source_provider_identity,
                price_convention=original.price_convention,
            ),
        ))

    reopened = store.open_run()
    assert reopened is not None
    assert reopened.price_observations == (original,)
