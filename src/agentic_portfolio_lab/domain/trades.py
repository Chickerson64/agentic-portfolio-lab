"""Deterministic, buy-only trade lifecycle models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID, uuid4

from .portfolio import (
    QUANTITY_PLACES,
    SecurityIdentity,
    _calculate_decimal,
    _canonical_upper_text,
    _require_aware_datetime,
    _require_date,
    _require_finite_decimal,
    _require_max_decimal_places,
    _require_non_empty_text,
    _require_positive_decimal,
)

TARGET_WEIGHT_PLACES: Final = Decimal("0.000001")
BUY_ACTION: Final = "BUY"
PROPOSED_STATUS: Final = "PROPOSED"
VALIDATED_STATUS: Final = "VALIDATED"
REJECTED_STATUS: Final = "REJECTED"
SIMULATED_EXECUTION_SOURCE: Final = "SIMULATED"


def _require_buy_action(value: str) -> str:
    action = _canonical_upper_text(value, field_name="action")
    if action != BUY_ACTION:
        raise ValueError("action must be BUY for the MVP")
    return action


def _require_exact_status(value: str, *, expected: str, field_name: str) -> str:
    status = _canonical_upper_text(value, field_name=field_name)
    if status != expected:
        raise ValueError(f"{field_name} must be {expected}")
    return status


def _require_target_weight(value: Decimal) -> Decimal:
    value = _require_positive_decimal(value, field_name="target_weight")
    value = _require_max_decimal_places(value, TARGET_WEIGHT_PLACES, field_name="target_weight")
    if value > Decimal("1"):
        raise ValueError("target_weight must not exceed 1")
    return value


def _require_quantity(value: Decimal, *, field_name: str) -> Decimal:
    value = _require_positive_decimal(value, field_name=field_name)
    return _require_max_decimal_places(value, QUANTITY_PLACES, field_name=field_name)


def _require_validation_results(value: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError("validation_results must be a tuple or list of strings")
    results = tuple(value)
    for result in results:
        _require_non_empty_text(result, field_name="validation_results item")
    return results


def _require_audit_value(value: Decimal | str | None, *, field_name: str) -> Decimal | str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return _require_finite_decimal(value, field_name=field_name)
    return _require_non_empty_text(value, field_name=field_name)


@dataclass(frozen=True, slots=True)
class TradeProposal:
    """A deterministic buy candidate, before deterministic validation."""

    decision_cycle_id: UUID
    portfolio_id: UUID
    security: SecurityIdentity
    action: str
    target_weight: Decimal
    proposed_notional_amount: Decimal
    proposed_quantity: Decimal
    price_source_timestamp: datetime
    reason_reference: str
    status: str = PROPOSED_STATUS
    trade_proposal_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not isinstance(self.security, SecurityIdentity):
            raise TypeError("security must be a SecurityIdentity")
        object.__setattr__(self, "action", _require_buy_action(self.action))
        object.__setattr__(self, "target_weight", _require_target_weight(self.target_weight))
        object.__setattr__(
            self,
            "proposed_notional_amount",
            _require_positive_decimal(self.proposed_notional_amount, field_name="proposed_notional_amount"),
        )
        object.__setattr__(self, "proposed_quantity", _require_quantity(self.proposed_quantity, field_name="proposed_quantity"))
        _require_aware_datetime(self.price_source_timestamp, field_name="price_source_timestamp")
        object.__setattr__(self, "reason_reference", _require_non_empty_text(self.reason_reference, field_name="reason_reference"))
        object.__setattr__(
            self,
            "status",
            _require_exact_status(self.status, expected=PROPOSED_STATUS, field_name="status"),
        )


@dataclass(frozen=True, slots=True)
class ValidatedTrade:
    """A trade proposal that passed deterministic validation and awaits execution."""

    proposal: TradeProposal
    validation_timestamp: datetime
    validation_results: tuple[str, ...] | list[str] = field(default_factory=tuple)
    validation_status: str = VALIDATED_STATUS
    validated_trade_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, TradeProposal):
            raise TypeError("proposal must be a TradeProposal")
        _require_aware_datetime(self.validation_timestamp, field_name="validation_timestamp")
        object.__setattr__(self, "validation_results", _require_validation_results(self.validation_results))
        object.__setattr__(
            self,
            "validation_status",
            _require_exact_status(self.validation_status, expected=VALIDATED_STATUS, field_name="validation_status"),
        )

    @property
    def trade_proposal_id(self) -> UUID:
        return self.proposal.trade_proposal_id

    @property
    def decision_cycle_id(self) -> UUID:
        return self.proposal.decision_cycle_id

    @property
    def portfolio_id(self) -> UUID:
        return self.proposal.portfolio_id

    @property
    def security(self) -> SecurityIdentity:
        return self.proposal.security

    @property
    def action(self) -> str:
        return self.proposal.action

    @property
    def validated_notional_amount(self) -> Decimal:
        return self.proposal.proposed_notional_amount

    @property
    def validated_quantity(self) -> Decimal:
        return self.proposal.proposed_quantity


@dataclass(frozen=True, slots=True)
class RejectedProposalValidationRecord:
    """An immutable audit record for one failed deterministic validation rule.

    Validation/orchestration owns exclusive accepted-or-rejected outcomes across
    records; this value object preserves the rejected proposal's lineage.
    """

    proposal: TradeProposal
    rule_id: str
    reason: str
    validated_at: datetime
    actual_value: Decimal | str | None = None
    allowed_threshold: Decimal | str | None = None
    validation_status: str = REJECTED_STATUS

    def __post_init__(self) -> None:
        if not isinstance(self.proposal, TradeProposal):
            raise TypeError("proposal must be a TradeProposal")
        object.__setattr__(self, "rule_id", _require_non_empty_text(self.rule_id, field_name="rule_id"))
        object.__setattr__(self, "reason", _require_non_empty_text(self.reason, field_name="reason"))
        _require_aware_datetime(self.validated_at, field_name="validated_at")
        object.__setattr__(self, "actual_value", _require_audit_value(self.actual_value, field_name="actual_value"))
        object.__setattr__(
            self,
            "allowed_threshold",
            _require_audit_value(self.allowed_threshold, field_name="allowed_threshold"),
        )
        object.__setattr__(
            self,
            "validation_status",
            _require_exact_status(self.validation_status, expected=REJECTED_STATUS, field_name="validation_status"),
        )

    @property
    def proposal_id(self) -> UUID:
        return self.proposal.trade_proposal_id

    @property
    def decision_cycle_id(self) -> UUID:
        return self.proposal.decision_cycle_id


@dataclass(frozen=True, slots=True)
class ExecutedTrade:
    """A final simulated single-fill execution derived from a validated trade."""

    validated_trade: ValidatedTrade
    executed_quantity: Decimal
    execution_price: Decimal
    source_provider_identity: str
    market_date: date
    currency: str
    price_convention: str
    executed_at: datetime
    execution_source: str = SIMULATED_EXECUTION_SOURCE
    executed_trade_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not isinstance(self.validated_trade, ValidatedTrade):
            raise TypeError("validated_trade must be a ValidatedTrade")
        executed_quantity = _require_quantity(self.executed_quantity, field_name="executed_quantity")
        if executed_quantity != self.validated_trade.validated_quantity:
            raise ValueError("executed_quantity must equal validated_quantity; partial fills are deferred")
        execution_price = _require_positive_decimal(self.execution_price, field_name="execution_price")
        currency = _canonical_upper_text(self.currency, field_name="currency")
        if currency != self.validated_trade.security.currency:
            raise ValueError("currency must match the validated trade security currency")
        object.__setattr__(self, "executed_quantity", executed_quantity)
        object.__setattr__(self, "execution_price", execution_price)
        object.__setattr__(self, "source_provider_identity", _require_non_empty_text(self.source_provider_identity, field_name="source_provider_identity"))
        _require_date(self.market_date, field_name="market_date")
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "price_convention", _require_non_empty_text(self.price_convention, field_name="price_convention"))
        executed_at = _require_aware_datetime(self.executed_at, field_name="executed_at")
        if executed_at < self.validated_trade.validation_timestamp:
            raise ValueError("executed_at must not precede validation_timestamp")
        object.__setattr__(
            self,
            "execution_source",
            _require_exact_status(
                self.execution_source,
                expected=SIMULATED_EXECUTION_SOURCE,
                field_name="execution_source",
            ),
        )

    @property
    def validated_trade_id(self) -> UUID:
        return self.validated_trade.validated_trade_id

    @property
    def trade_proposal_id(self) -> UUID:
        return self.validated_trade.trade_proposal_id

    @property
    def decision_cycle_id(self) -> UUID:
        return self.validated_trade.decision_cycle_id

    @property
    def portfolio_id(self) -> UUID:
        return self.validated_trade.portfolio_id

    @property
    def security(self) -> SecurityIdentity:
        return self.validated_trade.security

    @property
    def action(self) -> str:
        return self.validated_trade.action

    @property
    def executed_notional(self) -> Decimal:
        return _calculate_decimal(lambda: self.executed_quantity * self.execution_price)
