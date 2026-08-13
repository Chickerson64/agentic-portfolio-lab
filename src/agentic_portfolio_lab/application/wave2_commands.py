"""Narrow durable commands for paired funding and passive benchmark paper fills."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum

from agentic_portfolio_lab.domain.benchmark_fulfillment import PassiveIndexFulfillment, fulfill_paper_intent
from agentic_portfolio_lab.domain.cash_events import CashEvent, CashEventFundingWorkflow, CashEventFundingResult
from agentic_portfolio_lab.domain.constitution import PassiveIndexConstitution
from agentic_portfolio_lab.domain.performance import BenchmarkPerformanceHistory, PortfolioPerformanceHistory
from agentic_portfolio_lab.domain.valuation import PortfolioValuation, PriceObservation

from .local_state import PersistedRunState


class CashEventService:
    def __init__(self, store) -> None:
        self._store = store

    def apply(self, *, amount: Decimal, currency: str, source: str, effective_at: datetime) -> CashEventFundingResult:
        state = _require_state(self._store)
        event = CashEvent(amount, currency, effective_at, source)
        funding = CashEventFundingWorkflow.apply(event, state.managed_portfolio, state.benchmark_portfolio)
        managed_valuation, benchmark_valuation = _paired_valuations(
            funding.funded_managed_portfolio, funding.funded_benchmark_portfolio, state, as_of=effective_at
        )
        proposed = replace(
            state,
            managed_portfolio=funding.funded_managed_portfolio,
            benchmark_portfolio=funding.funded_benchmark_portfolio,
            managed_history=state.managed_history.append(funding.funded_managed_portfolio, managed_valuation, cash_events=(event,)),
            benchmark_history=state.benchmark_history.append(funding.funded_benchmark_portfolio, benchmark_valuation, cash_events=(event,)),
            funding_results=(*state.funding_results, funding),
            benchmark_fulfillment_status="PENDING_NO_ELIGIBLE_PRICE",
        )
        self._store.save_transition(proposed)
        return funding


class BenchmarkFulfillmentService:
    def __init__(self, store) -> None:
        self._store = store
        self._constitution = PassiveIndexConstitution.paper_simulation()

    def fulfill(self, *, fulfilled_at: datetime) -> "BenchmarkFulfillmentResult":
        state = _require_state(self._store)
        intent = self._constitution.evaluate(state.benchmark_portfolio)
        if intent is None:
            return self._record_no_action(state, BenchmarkFulfillmentStatus.NO_ACTION_ZERO_CASH)
        observation = _latest_spy_observation(state, before=fulfilled_at)
        if observation is None:
            return self._record_no_action(state, BenchmarkFulfillmentStatus.PENDING_NO_ELIGIBLE_PRICE)
        try:
            fulfillment = fulfill_paper_intent(intent, observation, fulfilled_at=fulfilled_at)
        except ValueError as error:
            if "positive feasible quantity" in str(error):
                return self._record_no_action(state, BenchmarkFulfillmentStatus.NO_ACTION_INSUFFICIENT_BUYING_POWER)
            raise
        managed_valuation = _managed_valuation_at_quote(state.managed_portfolio, state, observation, as_of=fulfilled_at)
        benchmark_valuation = PortfolioValuation.from_benchmark(
            fulfillment.fulfilled_benchmark_portfolio, (observation,), as_of_timestamp=fulfilled_at,
            market_date=observation.market_date, source_price_timestamp=observation.observed_at,
            source_provider_identity=observation.source_provider_identity, price_convention=observation.price_convention,
        )
        proposed = replace(
            state,
            benchmark_portfolio=fulfillment.fulfilled_benchmark_portfolio,
            managed_history=state.managed_history.append(state.managed_portfolio, managed_valuation),
            benchmark_history=state.benchmark_history.append(fulfillment.fulfilled_benchmark_portfolio, benchmark_valuation),
            benchmark_fulfillments=(*state.benchmark_fulfillments, fulfillment),
            benchmark_fulfillment_status=BenchmarkFulfillmentStatus.FULFILLED.value,
        )
        self._store.save_transition(proposed)
        return BenchmarkFulfillmentResult(BenchmarkFulfillmentStatus.FULFILLED, fulfillment)

    def _record_no_action(self, state: PersistedRunState, status: "BenchmarkFulfillmentStatus") -> "BenchmarkFulfillmentResult":
        if state.benchmark_fulfillment_status != status.value:
            self._store.save_transition(replace(state, benchmark_fulfillment_status=status.value))
        return BenchmarkFulfillmentResult(status)


class BenchmarkFulfillmentStatus(str, Enum):
    FULFILLED = "FULFILLED"
    NO_ACTION_ZERO_CASH = "NO_ACTION_ZERO_CASH"
    NO_ACTION_INSUFFICIENT_BUYING_POWER = "NO_ACTION_INSUFFICIENT_BUYING_POWER"
    PENDING_NO_ELIGIBLE_PRICE = "PENDING_NO_ELIGIBLE_PRICE"


@dataclass(frozen=True, slots=True)
class BenchmarkFulfillmentResult:
    status: BenchmarkFulfillmentStatus
    fulfillment: PassiveIndexFulfillment | None = None

    def __post_init__(self) -> None:
        if self.status is BenchmarkFulfillmentStatus.FULFILLED and self.fulfillment is None:
            raise ValueError("FULFILLED requires a fulfillment artifact")
        if self.status is not BenchmarkFulfillmentStatus.FULFILLED and self.fulfillment is not None:
            raise ValueError("no-action benchmark status must not contain a fulfillment artifact")


def _require_state(store) -> PersistedRunState:
    state = store.open_run()
    if state is None:
        raise ValueError("local SQLite run has not been initialized")
    return state


def _latest_spy_observation(state: PersistedRunState, *, before: datetime) -> PriceObservation | None:
    funding_boundary = max(result.cash_event.effective_at for result in state.funding_results)
    candidates = tuple(
        observation for observation in state.price_observations
        if observation.security == state.benchmark_portfolio.benchmark_security
        and funding_boundary <= observation.observed_at <= before
    )
    return max(candidates, key=lambda observation: observation.observed_at) if candidates else None


def _paired_valuations(managed, benchmark, state: PersistedRunState, *, as_of: datetime) -> tuple[PortfolioValuation, PortfolioValuation]:
    # Cash-only funding needs no market observation. Once the benchmark holds
    # SPY, retain the latest eligible exact quote for both aligned valuations.
    if benchmark.portfolio.positions:
        observation = _latest_spy_observation(state, before=as_of)
        if observation is None:
            raise ValueError("no persisted eligible SPY PriceObservation is available for synchronized valuation")
        metadata = dict(market_date=observation.market_date, source_price_timestamp=observation.observed_at, source_provider_identity=observation.source_provider_identity, price_convention=observation.price_convention)
        return (
            _managed_valuation_at_quote(managed, state, observation, as_of=as_of),
            PortfolioValuation.from_benchmark(benchmark, (observation,), as_of_timestamp=as_of, **metadata),
        )
    metadata = dict(market_date=as_of.date(), source_price_timestamp=as_of, source_provider_identity="cash-event", price_convention="cash-event")
    return (
        PortfolioValuation.from_portfolio(managed, (), as_of_timestamp=as_of, **metadata),
        PortfolioValuation.from_benchmark(benchmark, (), as_of_timestamp=as_of, **metadata),
    )


def _managed_valuation_at_quote(managed, state: PersistedRunState, observation: PriceObservation, *, as_of: datetime) -> PortfolioValuation:
    metadata = dict(market_date=observation.market_date, source_price_timestamp=observation.observed_at, source_provider_identity=observation.source_provider_identity, price_convention=observation.price_convention)
    observations = tuple(
        item for item in state.price_observations
        if item.security in {position.security for position in managed.positions}
        and item.market_date == observation.market_date
        and item.observed_at == observation.observed_at
        and item.source_provider_identity == observation.source_provider_identity
        and item.price_convention == observation.price_convention
    )
    return PortfolioValuation.from_portfolio(managed, observations, as_of_timestamp=as_of, **metadata)
