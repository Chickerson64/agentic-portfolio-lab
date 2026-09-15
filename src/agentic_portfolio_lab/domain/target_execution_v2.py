"""Deterministic V2 target-to-batch paper-trading boundary.

This module is deliberately additive to the V1 BUY lifecycle.  A manager owns
an immutable allocation target; this code owns price-dependent quantities,
System Safety, approval binding, and simulated fills.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from enum import StrEnum
import hashlib
import json
from typing import Iterable
from uuid import UUID, uuid4

from .portfolio import CashBalance, Portfolio, Position, QUANTITY_PLACES, SecurityIdentity, _calculate_decimal, _require_aware_datetime, _require_positive_decimal
from .portfolio_decisions_v2 import ExistingHoldingDisposition, PortfolioTargetAllocation
from .valuation import PriceObservation

V2_BATCH_SCHEMA_VERSION = "target-batch-v2"
V2_QUANTITY_POLICY_VERSION = "v1-8dp-half-even"


class BatchTradeAction(StrEnum):
    BUY = "BUY"
    ADD = "ADD"
    TRIM = "TRIM"
    SELL = "SELL"       # Existing holding omitted by the complete target.
    EXIT = "EXIT"       # Explicit V2 REMOVE target.


def _canonical(value: object) -> object:
    if isinstance(value, Decimal): return {"decimal": format(value, "f")}
    if isinstance(value, UUID): return str(value)
    if isinstance(value, StrEnum): return value.value
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, date): return value.isoformat()
    if isinstance(value, SecurityIdentity): return [value.ticker, value.security_type, value.exchange, value.currency]
    if isinstance(value, tuple): return [_canonical(item) for item in value]
    if isinstance(value, list): return [_canonical(item) for item in value]
    if isinstance(value, dict): return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if is_dataclass(value): return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)}
    return value


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(_canonical(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _quantity(value: Decimal) -> Decimal:
    # This is the product's only no-op tolerance: tradeable fractional shares.
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        return value.quantize(QUANTITY_PLACES, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class V2PriceSnapshot:
    """A complete immutable price set used for one target and one plan."""
    observations: tuple[PriceObservation, ...] | list[PriceObservation]

    def __post_init__(self) -> None:
        observations = tuple(self.observations)
        # A snapshot has no cash instrument.  It is consequently empty only
        # for a truthful all-cash portfolio and all-cash target.  Coverage is
        # still checked by the target-diff derivation: every holding or target
        # security is resolved through ``price_for`` and fails closed if absent.
        if not all(isinstance(item, PriceObservation) for item in observations):
            raise ValueError("price snapshot requires PriceObservation values")
        keys = tuple(item.security for item in observations)
        if len(set(keys)) != len(keys): raise ValueError("price snapshot must not contain duplicate securities")
        object.__setattr__(self, "observations", tuple(sorted(observations, key=lambda item: (item.security.ticker, item.observed_at.isoformat()))))

    @property
    def identity(self) -> str:
        return _digest(tuple((item.security, item.observed_price, item.observed_at, item.market_date, item.source_provider_identity, item.price_convention) for item in self.observations))

    def price_for(self, security: SecurityIdentity) -> PriceObservation:
        matches = tuple(item for item in self.observations if item.security == security)
        if len(matches) != 1: raise ValueError(f"price snapshot is missing {security.ticker}")
        return matches[0]


@dataclass(frozen=True, slots=True)
class BatchTradeLeg:
    security: SecurityIdentity
    action: BatchTradeAction
    quantity: Decimal
    price: Decimal
    target_weight: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.security, SecurityIdentity): raise TypeError("security must be SecurityIdentity")
        if not isinstance(self.action, BatchTradeAction): raise TypeError("action must be BatchTradeAction")
        object.__setattr__(self, "quantity", _require_positive_decimal(self.quantity, field_name="quantity"))
        object.__setattr__(self, "price", _require_positive_decimal(self.price, field_name="price"))
        if self.quantity != _quantity(self.quantity): raise ValueError("quantity must have at most 8 decimal places")
        if self.target_weight < 0 or self.target_weight > 1: raise ValueError("target_weight must be between zero and one")

    @property
    def notional(self) -> Decimal: return _calculate_decimal(lambda: self.quantity * self.price)
    @property
    def is_sale(self) -> bool: return self.action in {BatchTradeAction.TRIM, BatchTradeAction.SELL, BatchTradeAction.EXIT}


@dataclass(frozen=True, slots=True)
class BatchTradePlan:
    """One exact, ordered, immutable V2 plan.  Sales always precede purchases."""
    target: PortfolioTargetAllocation
    original_portfolio: Portfolio
    price_snapshot: V2PriceSnapshot
    legs: tuple[BatchTradeLeg, ...] | list[BatchTradeLeg]
    created_at: datetime
    plan_id: UUID = field(default_factory=uuid4)
    schema_version: str = V2_BATCH_SCHEMA_VERSION
    quantity_policy_version: str = V2_QUANTITY_POLICY_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.target, PortfolioTargetAllocation) or not isinstance(self.original_portfolio, Portfolio) or not isinstance(self.price_snapshot, V2PriceSnapshot): raise TypeError("target, original_portfolio, and price_snapshot are required")
        if self.target.portfolio_id != self.original_portfolio.portfolio_id: raise ValueError("target portfolio must match original portfolio")
        _require_aware_datetime(self.created_at, field_name="created_at")
        legs = tuple(self.legs)
        if not all(isinstance(item, BatchTradeLeg) for item in legs): raise TypeError("legs must contain BatchTradeLeg")
        if len({item.security for item in legs}) != len(legs): raise ValueError("plan must not contain duplicate security legs")
        if tuple(sorted(legs, key=lambda item: (0 if item.is_sale else 1, item.security.ticker))) != legs: raise ValueError("legs must be ordered sales then purchases by ticker")
        if self.schema_version != V2_BATCH_SCHEMA_VERSION or self.quantity_policy_version != V2_QUANTITY_POLICY_VERSION: raise ValueError("unsupported batch plan version")
        object.__setattr__(self, "legs", legs)

    @property
    def target_identity(self) -> str: return _digest(self.target)
    @property
    def portfolio_identity(self) -> str: return _digest(self.original_portfolio)
    @property
    def identity(self) -> str: return _digest((self.target_identity, self.portfolio_identity, self.price_snapshot.identity, self.legs, self.quantity_policy_version))


def derive_batch_trade_plan(target: PortfolioTargetAllocation, portfolio: Portfolio, snapshot: V2PriceSnapshot, *, created_at: datetime) -> BatchTradePlan:
    """Derive exact 8dp legs without changing any manager-supplied weight."""
    plan = build_batch_trade_plan(target, portfolio, snapshot, created_at=created_at)
    validate_batch_plan(plan)
    return plan


def build_batch_trade_plan(target: PortfolioTargetAllocation, portfolio: Portfolio, snapshot: V2PriceSnapshot, *, created_at: datetime) -> BatchTradePlan:
    """Build the exact diff before the hard System Safety evaluation.

    This is intentionally public so a failed safety result can still retain
    the immutable target and candidate plan for operator audit.
    """
    if target.portfolio_id != portfolio.portfolio_id: raise ValueError("target portfolio must match portfolio")
    legs = _derive_legs(target, portfolio, snapshot)
    return BatchTradePlan(target, portfolio, snapshot, tuple(legs), created_at)


def _derive_legs(target: PortfolioTargetAllocation, portfolio: Portfolio, snapshot: V2PriceSnapshot) -> list[BatchTradeLeg]:
    targets = {item.security: item for item in target.positions}
    securities = set(targets) | {item.security for item in portfolio.positions}
    legs: list[BatchTradeLeg] = []
    by_security = {item.security: item for item in portfolio.positions}
    total = _calculate_decimal(lambda: portfolio.cash_balance.amount + sum((position.quantity * snapshot.price_for(position.security).observed_price for position in portfolio.positions), Decimal("0")))
    for security in sorted(securities, key=lambda item: item.ticker):
        target_position = targets.get(security)
        current = by_security.get(security)
        current_quantity = Decimal("0") if current is None else current.quantity
        weight = Decimal("0") if target_position is None else target_position.target_weight
        observation = snapshot.price_for(security)
        # Division must have a bounded deterministic working precision; the
        # domain-wide MAX_PREC context would attempt to materialize recurring
        # decimals before the documented eight-place trade rounding.
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
            desired = _quantity(total * weight / observation.observed_price)
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
            delta = _quantity(desired - current_quantity)
        if delta.is_zero(): continue
        if delta > 0:
            action = BatchTradeAction.BUY if current is None or current_quantity.is_zero() else BatchTradeAction.ADD
            legs.append(BatchTradeLeg(security, action, delta, observation.observed_price, weight))
        else:
            if target_position is None: action = BatchTradeAction.SELL
            elif target_position.existing_holding_disposition is ExistingHoldingDisposition.REMOVE: action = BatchTradeAction.EXIT
            else: action = BatchTradeAction.TRIM
            legs.append(BatchTradeLeg(security, action, -delta, observation.observed_price, weight))
    legs.sort(key=lambda item: (0 if item.is_sale else 1, item.security.ticker))
    return legs


def validate_batch_plan(plan: BatchTradePlan) -> None:
    """Exact System Safety: long-only, full price coverage, and no leverage."""
    # Accept neither hand-edited quantities nor a policy implementation that
    # silently rescales a target. The approved legs must be the exact output of
    # the single deterministic derivation function.
    if tuple(_derive_legs(plan.target, plan.original_portfolio, plan.price_snapshot)) != plan.legs:
        raise ValueError("System Safety rejects a plan that does not exactly match its target diff")
    positions = {item.security: item.quantity for item in plan.original_portfolio.positions}
    cash = plan.original_portfolio.cash_balance.amount
    for leg in plan.legs:
        observation = plan.price_snapshot.price_for(leg.security)
        if observation.observed_price != leg.price: raise ValueError("plan price must match price snapshot")
        if leg.is_sale:
            held = positions.get(leg.security, Decimal("0"))
            if leg.quantity > held: raise ValueError("System Safety rejects a sale exceeding the long position")
            positions[leg.security] = _quantity(held - leg.quantity)
            cash = _calculate_decimal(lambda: cash + leg.notional)
        else:
            cash = _calculate_decimal(lambda: cash - leg.notional)
            positions[leg.security] = _calculate_decimal(lambda: positions.get(leg.security, Decimal("0")) + leg.quantity)
    if cash < 0: raise ValueError("System Safety rejects insufficient cash or leverage")
    if any(quantity < 0 for quantity in positions.values()): raise ValueError("System Safety rejects short positions")


@dataclass(frozen=True, slots=True)
class BatchSystemSafetyResult:
    """Durable result from the actual V2 hard safety validator."""
    plan: BatchTradePlan
    evaluated_at: datetime
    passed: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.plan, BatchTradePlan):
            raise TypeError("plan must be BatchTradePlan")
        _require_aware_datetime(self.evaluated_at, field_name="evaluated_at")
        if self.passed and self.reason is not None:
            raise ValueError("a passed System Safety result has no failure reason")
        if not self.passed and (not isinstance(self.reason, str) or not self.reason.strip()):
            raise ValueError("a failed System Safety result requires a reason")

    @property
    def identity(self) -> str:
        return _digest((self.plan.identity, self.evaluated_at, self.passed, self.reason))


def evaluate_batch_plan_safety(plan: BatchTradePlan, *, evaluated_at: datetime) -> BatchSystemSafetyResult:
    """Run the authoritative V2 System Safety validator and retain its result."""
    try:
        validate_batch_plan(plan)
    except ValueError as error:
        return BatchSystemSafetyResult(plan, evaluated_at, False, str(error))
    return BatchSystemSafetyResult(plan, evaluated_at, True)


@dataclass(frozen=True, slots=True)
class BatchApproval:
    plan: BatchTradePlan
    decision_maker_id: str
    decided_at: datetime
    approval_id: UUID = field(default_factory=uuid4)
    binding: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.plan, BatchTradePlan): raise TypeError("plan must be BatchTradePlan")
        # A target can be complete and still round to no executable legs.  It
        # is a truthful no-action outcome, not a trade batch a human can
        # approve.  Keeping this at the domain boundary prevents every
        # application adapter from accidentally manufacturing a fake approval
        # or simulated execution for it.
        if not self.plan.legs: raise ValueError("an empty batch plan is a no-action outcome and cannot be approved")
        if not isinstance(self.decision_maker_id, str) or not self.decision_maker_id.strip(): raise ValueError("decision_maker_id must not be empty")
        _require_aware_datetime(self.decided_at, field_name="decided_at")
        if self.decided_at < self.plan.created_at: raise ValueError("approval must not precede plan")
        object.__setattr__(self, "binding", _digest((self.plan.target_identity, self.plan.identity, self.plan.portfolio_identity, self.plan.price_snapshot.identity)))


@dataclass(frozen=True, slots=True)
class BatchRejection:
    """An immutable human rejection of one exact V2 plan.

    Rejection deliberately binds the same plan identity as approval.  It is an
    audit fact, not a second cycle lifecycle state.
    """
    plan: BatchTradePlan
    decision_maker_id: str
    decided_at: datetime
    reason: str | None = None
    rejection_id: UUID = field(default_factory=uuid4)
    binding: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.plan, BatchTradePlan):
            raise TypeError("plan must be BatchTradePlan")
        if not self.plan.legs:
            raise ValueError("an empty batch plan is a no-action outcome and cannot be rejected")
        if not isinstance(self.decision_maker_id, str) or not self.decision_maker_id.strip():
            raise ValueError("decision_maker_id must not be empty")
        _require_aware_datetime(self.decided_at, field_name="decided_at")
        if self.decided_at < self.plan.created_at:
            raise ValueError("rejection must not precede plan")
        if self.reason is not None and (not isinstance(self.reason, str) or not self.reason.strip()):
            raise ValueError("reason must be nonblank when supplied")
        object.__setattr__(self, "binding", _digest((self.plan.target_identity, self.plan.identity, self.plan.portfolio_identity, self.plan.price_snapshot.identity)))


@dataclass(frozen=True, slots=True)
class SimulatedBatchExecution:
    approval: BatchApproval
    original_portfolio: Portfolio
    resulting_portfolio: Portfolio
    executed_at: datetime
    execution_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.original_portfolio != self.approval.plan.original_portfolio: raise ValueError("stale state: portfolio no longer matches approved plan")
        _require_aware_datetime(self.executed_at, field_name="executed_at")
        if self.executed_at < self.approval.decided_at: raise ValueError("execution must not precede approval")


def execute_approved_batch(approval: BatchApproval, portfolio: Portfolio, snapshot: V2PriceSnapshot, *, executed_at: datetime) -> SimulatedBatchExecution:
    """Atomically apply an approved plan, rejecting any stale state before mutation."""
    plan = approval.plan
    if not plan.legs: raise ValueError("an empty batch plan is a no-action outcome and cannot be executed")
    if portfolio != plan.original_portfolio: raise ValueError("stale state: portfolio no longer matches approved plan")
    if snapshot.identity != plan.price_snapshot.identity: raise ValueError("stale state: price snapshot no longer matches approved plan")
    validate_batch_plan(plan)
    positions = {item.security: item for item in portfolio.positions}
    cash = portfolio.cash_balance.amount
    for leg in plan.legs:
        old = positions.get(leg.security)
        if leg.is_sale:
            assert old is not None
            remaining = _quantity(old.quantity - leg.quantity)
            cash = _calculate_decimal(lambda: cash + leg.notional)
            if remaining.is_zero(): positions.pop(leg.security)
            else: positions[leg.security] = Position(leg.security, remaining, _calculate_decimal(lambda: old.total_cost_basis * remaining / old.quantity), leg.price)
        else:
            basis = Decimal("0") if old is None else old.total_cost_basis
            quantity = leg.quantity if old is None else _calculate_decimal(lambda: old.quantity + leg.quantity)
            positions[leg.security] = Position(leg.security, quantity, _calculate_decimal(lambda: basis + leg.notional), leg.price)
            cash = _calculate_decimal(lambda: cash - leg.notional)
    if cash < 0: raise ValueError("System Safety rejects insufficient cash or leverage")
    updated = Portfolio(portfolio.portfolio_id, portfolio.portfolio_name, portfolio.base_currency, portfolio.starting_capital, CashBalance(portfolio.base_currency, cash), portfolio.created_at, tuple(sorted(positions.values(), key=lambda item: item.security.ticker)), portfolio.status, portfolio.decision_cycle_id)
    return SimulatedBatchExecution(approval, portfolio, updated, executed_at)
