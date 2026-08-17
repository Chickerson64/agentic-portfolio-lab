"""Deterministic research screening for managed universe capacity allocation.

The screener allocates up to five deep-research slots (at most three RANKED,
one COVERAGE, one REPORTING_CYCLE). It is not a portfolio manager; rank and
slot role stay on ``ScreeningRun`` audit records only.

Rank key (lexicographic, lower sorts earlier among RANKED candidates with a
usable cached OVERVIEW ``latest_quarter`` fact or ``fiscal_period``):

1. ``"0"`` when a positive fifty-two-week high yields
   ``current_price / fifty_two_week_high``; ``"1"`` when the ratio is unusable
   (missing or non-positive high sorts after usable ratios).
2. Fixed-width zero-padded ratio string (six integer digits, six fractional
   digits), or ``"999999.999999"`` when component 1 is ``"1"``.
3. Fixed-width zero-padded trailing PE when present and positive;
   ``"999999.999999"`` when PE is missing or non-positive (sorts after usable
   PE values).
4. Canonical uppercase ticker tie-break.

``rank_reason`` cites the price, high, ratio, and PE values used when present.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Sequence
from uuid import UUID

from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.provider_fundamentals import (
    ProviderEndpoint,
    ProviderFundamentalRecord,
)
from agentic_portfolio_lab.domain.screening import (
    ResearchSlotRole,
    ScreeningCandidateResult,
    ScreeningRun,
)
from agentic_portfolio_lab.domain.universe import CandidateUniverse
from agentic_portfolio_lab.domain.valuation import PriceObservation

_DEEP_STATEMENT_ENDPOINTS = frozenset(
    {
        ProviderEndpoint.INCOME_STATEMENT,
        ProviderEndpoint.BALANCE_SHEET,
        ProviderEndpoint.CASH_FLOW,
    }
)
_MISSING_RANK_COMPONENT = "999999.999999"
_MAX_RANKED = 3
_RANK_DECIMAL_QUANTUM = Decimal("0.000001")


def _encode_rank_decimal(value: Decimal) -> str:
    """Encode a positive decimal for lexicographic sort that matches numeric order."""
    quantized = value.quantize(_RANK_DECIMAL_QUANTUM)
    integer_part = int(quantized)
    fractional_part = int((quantized - Decimal(integer_part)) / _RANK_DECIMAL_QUANTUM)
    return f"{integer_part:06d}.{fractional_part:06d}"


def _parse_positive_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation:
        return None
    if parsed <= 0:
        return None
    return parsed


def _parse_quarter_date(value: str) -> date | None:
    text = value.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _fact_map(record: ProviderFundamentalRecord) -> dict[str, str]:
    return dict(record.facts)


def _latest_overview(
    records: Sequence[ProviderFundamentalRecord],
    security: SecurityIdentity,
) -> ProviderFundamentalRecord | None:
    overviews = [
        record
        for record in records
        if record.security == security and record.endpoint is ProviderEndpoint.OVERVIEW
    ]
    if not overviews:
        return None
    return max(overviews, key=lambda record: (record.fetched_at, record.source_date))


def _overview_latest_quarter(record: ProviderFundamentalRecord | None) -> date | None:
    if record is None:
        return None
    facts = _fact_map(record)
    latest_quarter = facts.get("latest_quarter")
    if latest_quarter is not None:
        parsed = _parse_quarter_date(latest_quarter)
        if parsed is not None:
            return parsed
    return record.fiscal_period


def _has_usable_overview(record: ProviderFundamentalRecord | None) -> bool:
    return _overview_latest_quarter(record) is not None


def _resolve_cycle_prices(
    observations: Sequence[PriceObservation],
) -> dict[SecurityIdentity, PriceObservation]:
    resolved: dict[SecurityIdentity, PriceObservation] = {}
    for observation in observations:
        security = observation.security
        existing = resolved.get(security)
        if existing is None:
            resolved[security] = observation
            continue
        if observation.observed_at > existing.observed_at:
            resolved[security] = observation
            continue
        if observation.observed_at == existing.observed_at:
            raise ValueError(
                f"ambiguous this-cycle price observations for {security.ticker}"
            )
    return resolved


def _rank_components(
    *,
    security: SecurityIdentity,
    price: Decimal | None,
    overview: ProviderFundamentalRecord | None,
) -> tuple[tuple[str, ...], str]:
    ticker = security.ticker
    if price is None or overview is None:
        return (
            ("9", _MISSING_RANK_COMPONENT, _MISSING_RANK_COMPONENT, ticker),
            f"{ticker} has no usable rank inputs for this cycle.",
        )

    facts = _fact_map(overview)
    fifty_two_week_high = _parse_positive_decimal(facts.get("fifty_two_week_high"))
    pe_ratio = _parse_positive_decimal(facts.get("pe_ratio"))

    if fifty_two_week_high is not None:
        position = price / fifty_two_week_high
        position_flag = "0"
        position_text = _encode_rank_decimal(position)
        position_display = f"{position:.6f}"
    else:
        position = None
        position_flag = "1"
        position_text = _MISSING_RANK_COMPONENT
        position_display = None

    if pe_ratio is not None:
        pe_text = _encode_rank_decimal(pe_ratio)
        pe_display = f"{pe_ratio:.6f}"
    else:
        pe_text = _MISSING_RANK_COMPONENT
        pe_display = None

    rank_key = (position_flag, position_text, pe_text, ticker)

    parts: list[str] = [f"{ticker} rank uses price {price}"]
    if position is not None and fifty_two_week_high is not None and position_display is not None:
        parts.append(
            f"a 52-week high of {fifty_two_week_high} "
            f"(position {position_display})"
        )
    else:
        parts.append("no usable 52-week high")
    if pe_ratio is not None and pe_display is not None:
        parts.append(f"trailing PE {pe_display}")
    else:
        parts.append("no usable trailing PE")
    rank_reason = ", ".join(parts) + "."

    return rank_key, rank_reason


def _latest_statement_fetch(
    records: Sequence[ProviderFundamentalRecord],
    security: SecurityIdentity,
) -> datetime | None:
    fetches = [
        record.fetched_at
        for record in records
        if record.security == security and record.endpoint in _DEEP_STATEMENT_ENDPOINTS
    ]
    if not fetches:
        return None
    return max(fetches)


def _coverage_sort_key(
    records: Sequence[ProviderFundamentalRecord],
    security: SecurityIdentity,
) -> tuple[int, datetime, str]:
    latest_fetch = _latest_statement_fetch(records, security)
    if latest_fetch is None:
        return (0, datetime.min.replace(tzinfo=timezone.utc), security.ticker)
    return (1, latest_fetch, security.ticker)


def _reporting_sort_key(
    overview: ProviderFundamentalRecord | None,
    security: SecurityIdentity,
) -> tuple[int, date, str]:
    latest_quarter = _overview_latest_quarter(overview)
    if latest_quarter is None:
        return (1, date.max, security.ticker)
    return (0, latest_quarter, security.ticker)


def _allocate_slots(
    *,
    eligible: Sequence[SecurityIdentity],
    rank_keys: dict[SecurityIdentity, tuple[str, ...]],
    usable_overview: dict[SecurityIdentity, bool],
    records: Sequence[ProviderFundamentalRecord],
) -> dict[SecurityIdentity, ResearchSlotRole]:
    assigned: dict[SecurityIdentity, ResearchSlotRole] = {}

    ranked_candidates = sorted(
        (security for security in eligible if usable_overview.get(security, False)),
        key=lambda security: rank_keys[security],
    )
    for security in ranked_candidates[:_MAX_RANKED]:
        assigned[security] = ResearchSlotRole.RANKED

    remaining = [security for security in eligible if security not in assigned]

    if remaining:
        coverage_winner = min(
            remaining,
            key=lambda security: _coverage_sort_key(records, security),
        )
        assigned[coverage_winner] = ResearchSlotRole.COVERAGE
        remaining = [security for security in remaining if security != coverage_winner]

    if remaining:
        reporting_winner = min(
            remaining,
            key=lambda security: _reporting_sort_key(
                _latest_overview(records, security),
                security,
            ),
        )
        assigned[reporting_winner] = ResearchSlotRole.REPORTING_CYCLE

    return assigned


def _selected_order(
    assigned: dict[SecurityIdentity, ResearchSlotRole],
    rank_keys: dict[SecurityIdentity, tuple[str, ...]],
) -> tuple[SecurityIdentity, ...]:
    ranked = sorted(
        (security for security, role in assigned.items() if role is ResearchSlotRole.RANKED),
        key=lambda security: rank_keys[security],
    )
    coverage = tuple(
        security for security, role in assigned.items() if role is ResearchSlotRole.COVERAGE
    )
    reporting = tuple(
        security
        for security, role in assigned.items()
        if role is ResearchSlotRole.REPORTING_CYCLE
    )
    return (*ranked, *coverage, *reporting)


class ScreeningService:
    """Allocate deep-research slots from universe, prices, and cached fundamentals."""

    def screen(
        self,
        *,
        universe: CandidateUniverse,
        price_observations: Sequence[PriceObservation],
        fundamental_records: Sequence[ProviderFundamentalRecord],
        screening_run_id: UUID,
        as_of: datetime,
    ) -> ScreeningRun:
        return screen_research(
            universe=universe,
            price_observations=price_observations,
            fundamental_records=fundamental_records,
            screening_run_id=screening_run_id,
            as_of=as_of,
        )


def screen_research(
    *,
    universe: CandidateUniverse,
    price_observations: Sequence[PriceObservation],
    fundamental_records: Sequence[ProviderFundamentalRecord],
    screening_run_id: UUID,
    as_of: datetime,
) -> ScreeningRun:
    """Build one immutable ``ScreeningRun`` for the supplied cycle inputs."""
    cycle_prices = _resolve_cycle_prices(price_observations)
    records = tuple(fundamental_records)

    eligible: list[SecurityIdentity] = []
    rank_keys: dict[SecurityIdentity, tuple[str, ...]] = {}
    rank_reasons: dict[SecurityIdentity, str] = {}
    usable_overview: dict[SecurityIdentity, bool] = {}

    for security in universe.identities:
        overview = _latest_overview(records, security)
        has_overview = _has_usable_overview(overview)
        usable_overview[security] = has_overview
        price_observation = cycle_prices.get(security)
        rank_key, rank_reason = _rank_components(
            security=security,
            price=price_observation.observed_price if price_observation is not None else None,
            overview=overview if has_overview else None,
        )
        rank_keys[security] = rank_key
        rank_reasons[security] = rank_reason
        if price_observation is not None:
            eligible.append(security)

    assigned = _allocate_slots(
        eligible=eligible,
        rank_keys=rank_keys,
        usable_overview=usable_overview,
        records=records,
    )

    results: list[ScreeningCandidateResult] = []
    for security in universe.identities:
        if security in eligible:
            results.append(
                ScreeningCandidateResult(
                    security=security,
                    eligible=True,
                    ineligibility_reason=None,
                    rank_key=rank_keys[security],
                    rank_reason=rank_reasons[security],
                    slot_role=assigned.get(security),
                )
            )
            continue
        results.append(
            ScreeningCandidateResult(
                security=security,
                eligible=False,
                ineligibility_reason="Missing this-cycle price observation for exact security identity.",
                rank_key=rank_keys[security],
                rank_reason=rank_reasons[security],
                slot_role=None,
            )
        )

    return ScreeningRun(
        screening_run_id=screening_run_id,
        universe_version=universe.universe_version,
        universe_identities=universe.identities,
        as_of=as_of,
        results=results,
        selected=_selected_order(assigned, rank_keys),
    )
