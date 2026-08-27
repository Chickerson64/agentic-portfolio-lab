"""Deterministic paired portfolio revaluation from persisted price observations."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Iterable

from agentic_portfolio_lab.application.local_state import PersistedRunState
from agentic_portfolio_lab.domain.valuation import PortfolioValuation, PriceObservation


class MarkToMarketService:
    """Build one append-only managed/benchmark valuation pair without providers."""

    @staticmethod
    def propose(state: PersistedRunState, observations: Iterable[PriceObservation]) -> PersistedRunState:
        if not isinstance(state, PersistedRunState):
            raise TypeError("state must be a PersistedRunState")
        supplied = tuple(observations)
        if not supplied or not all(isinstance(item, PriceObservation) for item in supplied):
            raise ValueError("mark-to-market requires non-empty PriceObservation artifacts")
        if not MarkToMarketService.required_securities(state):
            return state
        selected = MarkToMarketService._selected_observations(state, supplied)
        metadata = MarkToMarketService._metadata(selected)
        as_of = metadata["source_price_timestamp"]
        if (
            state.managed_history.snapshots
            and as_of <= state.managed_history.snapshots[-1].timestamp
        ) or (
            state.benchmark_history.snapshots
            and as_of <= state.benchmark_history.snapshots[-1].timestamp
        ):
            return state
        managed_securities = {position.security for position in state.managed_portfolio.positions}
        benchmark_securities = {position.security for position in state.benchmark_portfolio.portfolio.positions}
        managed = PortfolioValuation.from_portfolio_mark_to_market(
            state.managed_portfolio,
            tuple(item for item in selected if item.security in managed_securities),
            as_of_timestamp=as_of,
            **metadata,
        )
        benchmark = PortfolioValuation.from_benchmark_mark_to_market(
            state.benchmark_portfolio,
            tuple(item for item in selected if item.security in benchmark_securities),
            as_of_timestamp=as_of,
            **metadata,
        )
        return replace(
            state,
            managed_history=state.managed_history.append(state.managed_portfolio, managed),
            benchmark_history=state.benchmark_history.append(state.benchmark_portfolio, benchmark),
        )

    @staticmethod
    def _selected_observations(state: PersistedRunState, supplied: tuple[PriceObservation, ...]) -> tuple[PriceObservation, ...]:
        required = MarkToMarketService.required_securities(state)
        by_security: dict = {}
        for observation in supplied:
            if observation.security not in required:
                continue
            if observation.security in by_security:
                raise ValueError("mark-to-market observations must contain one exact price per held security")
            by_security[observation.security] = observation
        if set(by_security) != required:
            raise ValueError("mark-to-market observations are missing prices for one or more held securities")
        return tuple(by_security[security] for security in required)

    @staticmethod
    def required_securities(state: PersistedRunState) -> set:
        return {
            *(position.security for position in state.managed_portfolio.positions),
            *(position.security for position in state.benchmark_portfolio.portfolio.positions),
        }

    @staticmethod
    def _metadata(observations: tuple[PriceObservation, ...]) -> dict:
        reference = observations[0]
        if any(
            item.currency != reference.currency
            or item.market_date != reference.market_date
            or item.source_provider_identity != reference.source_provider_identity
            or item.price_convention != reference.price_convention
            for item in observations
        ):
            raise ValueError("mark-to-market observations must share currency, market date, provider, and price convention")
        return {
            "market_date": reference.market_date,
            "source_price_timestamp": max(item.observed_at for item in observations),
            "source_provider_identity": reference.source_provider_identity,
            "price_convention": reference.price_convention,
        }
