"""Wave 1 integration checks for durable market-price refreshes."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentic_portfolio_lab.api.app import create_app
from agentic_portfolio_lab.application.market_configuration import CANDIDATE_UNIVERSE, SPY_BENCHMARK
from agentic_portfolio_lab.application.refresh_prices import PriceRefreshConflict, RefreshPricesService
from agentic_portfolio_lab.domain.market_prices import MarketPriceError
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore, SQLitePriceRefreshState


UTC = timezone.utc
INITIALIZED_AT = datetime(2026, 8, 13, 14, 30, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 8, 13, 20, 0, tzinfo=UTC)


class _FakeMarketPriceProvider:
    provider_identity = "fake-market-provider"
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


def test_provider_failure_persists_failed_operation_without_success_metadata(tmp_path: Path) -> None:
    database_path = tmp_path / "local-run.sqlite"
    store = SQLiteLocalRunStore(database_path)
    store.initialize_run(initialized_at=INITIALIZED_AT)
    client = TestClient(
        create_app(
            database_path=str(database_path),
            refresh_service=_service(store, _FakeMarketPriceProvider(error=MarketPriceError("provider unavailable"))),
        )
    )

    response = client.post("/commands/refresh-prices")

    assert response.status_code == 502
    recovered = SQLiteLocalRunStore(database_path).open_run()
    assert recovered is not None
    assert recovered.price_observations == ()
    operation = recovered.latest_price_refresh_operation
    assert operation is not None
    assert operation.status.value == "FAILED"
    assert operation.persisted_observation_count is None
    assert operation.latest_source_timestamp is None
    assert operation.failure_code == "market_price_unavailable"


def test_refresh_operation_is_durable_before_provider_work_and_completes(tmp_path: Path) -> None:
    database_path = tmp_path / "local-run.sqlite"
    store = SQLiteLocalRunStore(database_path)
    store.initialize_run(initialized_at=INITIALIZED_AT)

    class InspectingProvider(_FakeMarketPriceProvider):
        def get_observation(self, security: SecurityIdentity) -> PriceObservation:
            before = SQLiteLocalRunStore(database_path).open_run()
            assert before is not None and before.latest_price_refresh_operation is not None
            assert before.latest_price_refresh_operation.status.value == "IN_PROGRESS"
            return super().get_observation(security)

    client = TestClient(create_app(database_path=str(database_path), refresh_service=_service(store, InspectingProvider())))
    response = client.post("/commands/refresh-prices")
    assert response.status_code == 200
    status = client.get("/price-refresh/latest")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "COMPLETED"
    assert body["provider_identity"] == "fake-market-provider"
    assert body["expected_security_count"] == len((*CANDIDATE_UNIVERSE, SPY_BENCHMARK))
    assert body["persisted_observation_count"] == len((*CANDIDATE_UNIVERSE, SPY_BENCHMARK))
    assert body["latest_source_timestamp"] == OBSERVED_AT.isoformat()
    assert body["freshness_seconds"] >= 0
    reopened = SQLiteLocalRunStore(database_path).open_run()
    assert reopened is not None and reopened.latest_price_refresh_operation is not None
    assert reopened.latest_price_refresh_operation.status.value == "COMPLETED"


def test_duplicate_refresh_is_rejected_while_durable_operation_is_in_progress(tmp_path: Path) -> None:
    database_path = tmp_path / "local-run.sqlite"
    store = SQLiteLocalRunStore(database_path)
    store.initialize_run(initialized_at=INITIALIZED_AT)
    adapter = SQLitePriceRefreshState(store)
    from agentic_portfolio_lab.domain.price_refresh import PriceRefreshOperation, PriceRefreshOperationStatus
    from uuid import uuid4
    adapter.begin_price_refresh(PriceRefreshOperation(uuid4(), PriceRefreshOperationStatus.IN_PROGRESS, INITIALIZED_AT, "test", 1))
    with pytest.raises(PriceRefreshConflict, match="already in progress"):
        adapter.begin_price_refresh(PriceRefreshOperation(uuid4(), PriceRefreshOperationStatus.IN_PROGRESS, OBSERVED_AT, "test", 1))

    service = RefreshPricesService(provider=_FakeMarketPriceProvider(), state=adapter, candidate_universe=CANDIDATE_UNIVERSE, spy_benchmark=SPY_BENCHMARK)
    client = TestClient(create_app(database_path=str(database_path), refresh_service=service))
    response = client.post("/commands/refresh-prices")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "price_refresh_in_progress"


def test_completed_operation_allows_a_new_refresh_attempt(tmp_path: Path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "local-run.sqlite")
    store.initialize_run(initialized_at=INITIALIZED_AT)
    service = _service(store, _FakeMarketPriceProvider())
    service.refresh(())
    service.refresh(())
    state = store.open_run()
    assert state is not None and state.latest_price_refresh_operation is not None
    assert state.latest_price_refresh_operation.status.value == "COMPLETED"


def test_reopened_adapter_recovers_interrupted_operation_before_new_refresh(tmp_path: Path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "local-run.sqlite")
    store.initialize_run(initialized_at=INITIALIZED_AT)
    from agentic_portfolio_lab.domain.price_refresh import PriceRefreshOperation, PriceRefreshOperationStatus
    from uuid import uuid4
    original = PriceRefreshOperation(uuid4(), PriceRefreshOperationStatus.IN_PROGRESS, INITIALIZED_AT, "fake-market-provider", 1)
    SQLitePriceRefreshState(store).begin_price_refresh(original)
    reopened_adapter = SQLitePriceRefreshState(store)
    with pytest.raises(PriceRefreshConflict):
        reopened_adapter.begin_price_refresh(PriceRefreshOperation(uuid4(), PriceRefreshOperationStatus.IN_PROGRESS, OBSERVED_AT, "fake-market-provider", 1))
    reopened_adapter.recover_interrupted_price_refresh(original.operation_id, recovered_at=OBSERVED_AT)
    fresh = PriceRefreshOperation(uuid4(), PriceRefreshOperationStatus.IN_PROGRESS, OBSERVED_AT, "fake-market-provider", 1)
    reopened_adapter.begin_price_refresh(fresh)
    with pytest.raises(ValueError, match="no in-progress"):
        reopened_adapter.recover_interrupted_price_refresh(original.operation_id, recovered_at=OBSERVED_AT)
    recovered = store.open_run()
    assert recovered is not None and recovered.latest_price_refresh_operation == fresh


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
