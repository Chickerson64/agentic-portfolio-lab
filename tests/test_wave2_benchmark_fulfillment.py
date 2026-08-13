from datetime import datetime, timedelta, timezone
from dataclasses import fields, replace
from decimal import Decimal

from agentic_portfolio_lab.application.wave2_commands import BenchmarkFulfillmentService, CashEventService
from agentic_portfolio_lab.application.local_state_codec import decode_run_state, encode
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.domain.valuation import PortfolioValuation
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore, SQLitePriceRefreshState
import pytest


UTC = timezone.utc
START = datetime(2026, 8, 13, 14, 0, tzinfo=UTC)


def test_paired_funding_and_quote_attributed_spy_fulfillment_persist(tmp_path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    initial = store.initialize_run(initialized_at=START)
    funding_at = START + timedelta(minutes=1)
    funding = CashEventService(store).apply(amount=Decimal("1000"), currency="USD", source="weekly deposit", effective_at=funding_at)
    assert funding.funded_managed_portfolio.cash_balance.amount == Decimal("2000")
    assert funding.funded_benchmark_portfolio.portfolio.cash_balance.amount == Decimal("2000")

    observed_at = START + timedelta(minutes=2)
    spy = initial.benchmark_portfolio.benchmark_security
    observation = PriceObservation(spy, Decimal("500"), observed_at.date(), observed_at, "USD", "twelve-data", "twelve-data-quote-close-field")
    SQLitePriceRefreshState(store).apply_price_refresh((observation,))
    result = BenchmarkFulfillmentService(store).fulfill(fulfilled_at=observed_at)
    fulfillment = result.fulfillment

    assert fulfillment is not None
    assert fulfillment.intent.deployment_rule == "PROVIDER_ATTRIBUTED_PAPER_QUOTE"
    assert fulfillment.price_observation is observation or fulfillment.price_observation == observation
    assert fulfillment.price_observation.price_convention == "twelve-data-quote-close-field"
    reopened = store.open_run()
    assert reopened is not None
    assert len(reopened.funding_results) == 2
    assert len(reopened.benchmark_fulfillments) == 1
    assert reopened.benchmark_portfolio.portfolio.cash_balance.amount < Decimal("2000")
    assert reopened.benchmark_portfolio.portfolio.positions[0].security.ticker == "SPY"
    assert reopened.managed_history.snapshots[-1].timestamp == reopened.benchmark_history.snapshots[-1].timestamp == observed_at


def test_quote_before_relevant_funding_is_pending_and_does_not_mutate(tmp_path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    initial = store.initialize_run(initialized_at=START)
    quote_at = START + timedelta(minutes=1)
    observation = PriceObservation(initial.benchmark_portfolio.benchmark_security, Decimal("500"), quote_at.date(), quote_at, "USD", "twelve-data", "twelve-data-quote-close-field")
    SQLitePriceRefreshState(store).apply_price_refresh((observation,))
    CashEventService(store).apply(amount=Decimal("1000"), currency="USD", source="after quote", effective_at=START + timedelta(minutes=2))

    result = BenchmarkFulfillmentService(store).fulfill(fulfilled_at=START + timedelta(minutes=3))

    assert result.status.value == "PENDING_NO_ELIGIBLE_PRICE"
    assert store.open_run().benchmark_fulfillments == ()


def test_quote_at_funding_boundary_is_eligible(tmp_path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    initial = store.initialize_run(initialized_at=START)
    funding_at = START + timedelta(minutes=1)
    CashEventService(store).apply(amount=Decimal("1000"), currency="USD", source="weekly", effective_at=funding_at)
    observation = PriceObservation(initial.benchmark_portfolio.benchmark_security, Decimal("500"), funding_at.date(), funding_at, "USD", "twelve-data", "twelve-data-quote-close-field")
    SQLitePriceRefreshState(store).apply_price_refresh((observation,))

    result = BenchmarkFulfillmentService(store).fulfill(fulfilled_at=funding_at + timedelta(minutes=1))

    assert result.status.value == "FULFILLED"


def test_two_week_fulfillments_allow_intervening_paired_cash_event(tmp_path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    initial = store.initialize_run(initialized_at=START)
    week_one_quote = START + timedelta(minutes=1)
    spy = initial.benchmark_portfolio.benchmark_security
    SQLitePriceRefreshState(store).apply_price_refresh((PriceObservation(spy, Decimal("500"), week_one_quote.date(), week_one_quote, "USD", "twelve-data", "twelve-data-quote-close-field"),))
    assert BenchmarkFulfillmentService(store).fulfill(fulfilled_at=week_one_quote).status.value == "FULFILLED"

    week_two_funding = START + timedelta(days=7)
    CashEventService(store).apply(amount=Decimal("1000"), currency="USD", source="week two", effective_at=week_two_funding)
    week_two_quote = week_two_funding + timedelta(minutes=1)
    SQLitePriceRefreshState(store).apply_price_refresh((PriceObservation(spy, Decimal("500"), week_two_quote.date(), week_two_quote, "USD", "twelve-data", "twelve-data-quote-close-field"),))
    assert BenchmarkFulfillmentService(store).fulfill(fulfilled_at=week_two_quote).status.value == "FULFILLED"

    reopened = store.open_run()
    assert reopened is not None
    assert len(reopened.benchmark_fulfillments) == 2
    assert reopened.benchmark_fulfillment_status == "FULFILLED"


def test_new_cash_event_after_historical_fulfillment_is_currently_pending(tmp_path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    initial = store.initialize_run(initialized_at=START)
    quote_at = START + timedelta(minutes=1)
    spy = initial.benchmark_portfolio.benchmark_security
    SQLitePriceRefreshState(store).apply_price_refresh((PriceObservation(spy, Decimal("500"), quote_at.date(), quote_at, "USD", "twelve-data", "twelve-data-quote-close-field"),))
    BenchmarkFulfillmentService(store).fulfill(fulfilled_at=quote_at)
    CashEventService(store).apply(amount=Decimal("100"), currency="USD", source="new cash", effective_at=START + timedelta(days=1))

    assert store.open_run().benchmark_fulfillment_status == "PENDING_NO_ELIGIBLE_PRICE"


def test_pending_cannot_relabel_residual_cash_after_latest_fulfillment(tmp_path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    initial = store.initialize_run(initialized_at=START)
    quote_at = START + timedelta(minutes=1)
    spy = initial.benchmark_portfolio.benchmark_security
    SQLitePriceRefreshState(store).apply_price_refresh((PriceObservation(spy, Decimal("333"), quote_at.date(), quote_at, "USD", "twelve-data", "twelve-data-quote-close-field"),))
    BenchmarkFulfillmentService(store).fulfill(fulfilled_at=quote_at)
    fulfilled = store.open_run()

    with pytest.raises(ValueError, match="cannot relabel residual cash"):
        replace(fulfilled, benchmark_fulfillment_status="PENDING_NO_ELIGIBLE_PRICE")


def test_global_funding_transition_rejects_fabricated_cash_increase_before_first_fulfillment(tmp_path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    store.initialize_run(initialized_at=START)
    CashEventService(store).apply(amount=Decimal("100"), currency="USD", source="small", effective_at=START + timedelta(minutes=1))
    valid = store.open_run()
    latest = valid.benchmark_history.snapshots[-1]
    # Bypass constructors only to demonstrate that aggregate validation—not
    # incidental cash-event IDs—rejects a forged funding transition.
    forged_portfolio = replace(latest.portfolio, cash_balance=replace(latest.portfolio.cash_balance, amount=Decimal("2000")))
    forged_snapshot = object.__new__(type(latest))
    for field in fields(type(latest)):
        object.__setattr__(forged_snapshot, field.name, forged_portfolio if field.name == "portfolio" else getattr(latest, field.name))
    forged_history = object.__new__(type(valid.benchmark_history))
    for field in fields(type(valid.benchmark_history)):
        object.__setattr__(forged_history, field.name, (*valid.benchmark_history.snapshots[:-1], forged_snapshot) if field.name == "snapshots" else getattr(valid.benchmark_history, field.name))
    forged_state = _raw_replace(valid, benchmark_portfolio=replace(valid.benchmark_portfolio, portfolio=forged_portfolio), benchmark_history=forged_history)

    with pytest.raises(ValueError, match="funding transition must exactly match"):
        forged_state.validate()
    assert store.open_run() == valid


def test_prior_schema_document_without_fulfillments_reopens_compatibly(tmp_path) -> None:
    state = SQLiteLocalRunStore(tmp_path / "run.sqlite")._initial_state(START)
    document = encode(state)
    del document["fields"]["benchmark_fulfillments"]
    del document["fields"]["benchmark_fulfillment_status"]

    reopened = decode_run_state(document)

    assert reopened.benchmark_fulfillments == ()
    assert reopened.benchmark_fulfillment_status == "PENDING_NO_ELIGIBLE_PRICE"


def test_contradictory_statuses_are_rejected_at_construction(tmp_path) -> None:
    initial = SQLiteLocalRunStore(tmp_path / "run.sqlite")._initial_state(START)
    with pytest.raises(ValueError, match="FULFILLED status requires"):
        replace(initial, benchmark_fulfillment_status="FULFILLED")
    with pytest.raises(ValueError, match="NO_ACTION_ZERO_CASH requires"):
        replace(initial, benchmark_fulfillment_status="NO_ACTION_ZERO_CASH")
    with pytest.raises(ValueError, match="NO_ACTION_INSUFFICIENT_BUYING_POWER requires"):
        replace(initial, benchmark_fulfillment_status="NO_ACTION_INSUFFICIENT_BUYING_POWER")


def test_valuation_only_transition_with_unchanged_portfolios_is_accepted(tmp_path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    initial = store.initialize_run(initialized_at=START)
    quote_at = START + timedelta(minutes=1)
    spy = initial.benchmark_portfolio.benchmark_security
    quote = PriceObservation(spy, Decimal("500"), quote_at.date(), quote_at, "USD", "twelve-data", "twelve-data-quote-close-field")
    SQLitePriceRefreshState(store).apply_price_refresh((quote,))
    BenchmarkFulfillmentService(store).fulfill(fulfilled_at=quote_at)
    state = store.open_run()
    later = quote_at + timedelta(minutes=1)
    managed_value = PortfolioValuation.from_portfolio(state.managed_portfolio, (), as_of_timestamp=later, market_date=quote.market_date, source_price_timestamp=quote.observed_at, source_provider_identity=quote.source_provider_identity, price_convention=quote.price_convention)
    benchmark_value = PortfolioValuation.from_benchmark(state.benchmark_portfolio, (quote,), as_of_timestamp=later, market_date=quote.market_date, source_price_timestamp=quote.observed_at, source_provider_identity=quote.source_provider_identity, price_convention=quote.price_convention)

    store.save_transition(replace(state, managed_history=state.managed_history.append(state.managed_portfolio, managed_value), benchmark_history=state.benchmark_history.append(state.benchmark_portfolio, benchmark_value)))
    assert store.open_run().benchmark_history.snapshots[-1].portfolio == state.benchmark_portfolio.portfolio


def test_zero_cash_no_action_status_survives_restart_without_new_fulfillment(tmp_path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    initial = store.initialize_run(initialized_at=START)
    quote_at = START + timedelta(minutes=1)
    quote = PriceObservation(initial.benchmark_portfolio.benchmark_security, Decimal("500"), quote_at.date(), quote_at, "USD", "twelve-data", "twelve-data-quote-close-field")
    SQLitePriceRefreshState(store).apply_price_refresh((quote,))
    service = BenchmarkFulfillmentService(store)
    assert service.fulfill(fulfilled_at=quote_at).status.value == "FULFILLED"
    before_no_action = store.open_run()

    result = service.fulfill(fulfilled_at=quote_at + timedelta(minutes=1))
    reopened = SQLiteLocalRunStore(tmp_path / "run.sqlite").open_run()

    assert result.status.value == "NO_ACTION_ZERO_CASH"
    assert result.fulfillment is None
    assert reopened.benchmark_fulfillment_status == "NO_ACTION_ZERO_CASH"
    assert reopened.benchmark_portfolio.portfolio.cash_balance.amount == Decimal("0")
    assert len(reopened.benchmark_fulfillments) == len(before_no_action.benchmark_fulfillments) == 1


def test_insufficient_buying_power_no_action_status_survives_restart(tmp_path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    initial = store.initialize_run(initialized_at=START)
    quote_at = START + timedelta(minutes=1)
    quote = PriceObservation(initial.benchmark_portfolio.benchmark_security, Decimal("1000000000000"), quote_at.date(), quote_at, "USD", "twelve-data", "twelve-data-quote-close-field")
    SQLitePriceRefreshState(store).apply_price_refresh((quote,))

    result = BenchmarkFulfillmentService(store).fulfill(fulfilled_at=quote_at)
    reopened = SQLiteLocalRunStore(tmp_path / "run.sqlite").open_run()

    assert result.status.value == "NO_ACTION_INSUFFICIENT_BUYING_POWER"
    assert result.fulfillment is None
    assert reopened.benchmark_fulfillment_status == "NO_ACTION_INSUFFICIENT_BUYING_POWER"
    assert reopened.benchmark_fulfillments == ()
    assert reopened.benchmark_portfolio.portfolio.cash_balance.amount == Decimal("1000")
    assert reopened.price_observations[0] is not quote
    assert reopened.price_observations[0] == quote


def test_valuation_only_transition_rejects_unexplained_benchmark_cash_mutation(tmp_path) -> None:
    store = SQLiteLocalRunStore(tmp_path / "run.sqlite")
    persisted = store.initialize_run(initialized_at=START)
    later = START + timedelta(minutes=1)
    forged_portfolio = replace(
        persisted.benchmark_portfolio.portfolio,
        cash_balance=replace(persisted.benchmark_portfolio.portfolio.cash_balance, amount=Decimal("999")),
    )
    forged_benchmark = replace(persisted.benchmark_portfolio, portfolio=forged_portfolio)
    valuation = PortfolioValuation.from_benchmark(
        forged_benchmark, (), as_of_timestamp=later, market_date=later.date(), source_price_timestamp=later,
        source_provider_identity="valuation-only", price_convention="valuation-only",
    )
    forged_history = persisted.benchmark_history.append(forged_benchmark, valuation)
    invalid = _raw_replace(
        persisted,
        benchmark_portfolio=forged_benchmark,
        benchmark_history=forged_history,
    )

    with pytest.raises(ValueError, match="unexplained portfolio-state transition"):
        store.save_transition(invalid)
    assert store.open_run() == persisted


def _raw_replace(state, **changes):
    raw = object.__new__(type(state))
    for field in fields(type(state)):
        object.__setattr__(raw, field.name, changes.get(field.name, getattr(state, field.name)))
    return raw
