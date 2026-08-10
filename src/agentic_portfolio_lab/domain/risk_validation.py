"""Deterministic mechanical validation for verified Value Manager decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .portfolio import (
    SecurityIdentity,
    _canonical_upper_text,
    _require_aware_datetime,
    _require_finite_decimal,
    _require_non_empty_text,
)
from .portfolio_service import PortfolioService, TargetPurchaseCalculation
from .recommendations import RecommendationAction
from .research import MissingData, ResearchPacket
from .trades import TradeProposal, ValidatedTrade
from .valuation import PriceObservation
from .value_manager_workflow import ValueManagerDecisionResult


class RiskValidationStatus(StrEnum):
    """The deterministic outcome of one rule or complete validation run."""

    PASSED = "PASSED"
    FAILED = "FAILED"


def _require_audit_value(value: Decimal | str | None, *, field_name: str) -> Decimal | str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return _require_finite_decimal(value, field_name=field_name)
    return _require_non_empty_text(value, field_name=field_name).strip()


@dataclass(frozen=True, slots=True)
class RiskRuleResult:
    """An immutable, auditable result for one deterministic validation rule."""

    rule_id: str
    status: RiskValidationStatus
    reason: str
    actual_value: Decimal | str | None = None
    allowed_threshold: Decimal | str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _canonical_upper_text(self.rule_id, field_name="rule_id"))
        if not isinstance(self.status, RiskValidationStatus):
            raise TypeError("status must be a RiskValidationStatus")
        object.__setattr__(self, "reason", _require_non_empty_text(self.reason, field_name="reason").strip())
        object.__setattr__(self, "actual_value", _require_audit_value(self.actual_value, field_name="actual_value"))
        object.__setattr__(
            self,
            "allowed_threshold",
            _require_audit_value(self.allowed_threshold, field_name="allowed_threshold"),
        )

    @property
    def passed(self) -> bool:
        return self.status is RiskValidationStatus.PASSED


@dataclass(frozen=True, slots=True)
class RiskValidationResult:
    """One verified decision's deterministic validation outcome.

    A BUY produces a ``ValidatedTrade`` only after every mechanical rule passes.
    HOLD is a successful no-trade outcome. Failed outcomes retain their complete
    immutable rule audit without manufacturing an invalid trade proposal.
    """

    decision_result: ValueManagerDecisionResult
    validation_timestamp: datetime
    status: RiskValidationStatus
    rule_results: tuple[RiskRuleResult, ...] | list[RiskRuleResult]
    target_purchase: TargetPurchaseCalculation | None = None
    validated_trade: ValidatedTrade | None = None
    price_observation: PriceObservation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.decision_result, ValueManagerDecisionResult):
            raise TypeError("decision_result must be a ValueManagerDecisionResult")
        validation_timestamp = _require_aware_datetime(self.validation_timestamp, field_name="validation_timestamp")
        if validation_timestamp < self.decision_result.produced_at:
            raise ValueError("validation_timestamp must not precede decision_result produced_at")
        if not isinstance(self.status, RiskValidationStatus):
            raise TypeError("status must be a RiskValidationStatus")
        if not isinstance(self.rule_results, (tuple, list)):
            raise TypeError("rule_results must be a tuple or list of RiskRuleResult instances")
        rule_results = tuple(self.rule_results)
        if not rule_results:
            raise ValueError("rule_results must not be empty")
        if not all(isinstance(result, RiskRuleResult) for result in rule_results):
            raise TypeError("rule_results must contain RiskRuleResult instances")
        rule_ids = tuple(result.rule_id for result in rule_results)
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("rule_results must not contain duplicate rule_id values")
        expected_status = (
            RiskValidationStatus.PASSED
            if all(result.passed for result in rule_results)
            else RiskValidationStatus.FAILED
        )
        if self.status is not expected_status:
            raise ValueError("status must match the contained rule results")
        recommendation = self.decision_result.recommendation
        if self.price_observation is not None and not isinstance(self.price_observation, PriceObservation):
            raise TypeError("price_observation must be a PriceObservation or None")
        if recommendation.action is RecommendationAction.HOLD:
            if self.target_purchase is not None or self.validated_trade is not None or self.price_observation is not None:
                raise ValueError("HOLD validation must not create a target purchase, validated trade, or price observation")
        elif self.status is RiskValidationStatus.PASSED:
            _verify_passed_buy_result(
                decision_result=self.decision_result,
                validation_timestamp=validation_timestamp,
                rule_results=rule_results,
                target_purchase=self.target_purchase,
                validated_trade=self.validated_trade,
                price_observation=self.price_observation,
            )
        elif self.validated_trade is not None:
            raise ValueError("a failed validation must not create a validated_trade")
        object.__setattr__(self, "validation_timestamp", validation_timestamp)
        object.__setattr__(self, "rule_results", rule_results)

    @property
    def passed(self) -> bool:
        return self.status is RiskValidationStatus.PASSED

    @property
    def proposal(self) -> TradeProposal | None:
        """Return the proposal only when a BUY has passed mechanical validation."""
        return None if self.validated_trade is None else self.validated_trade.proposal


def _rule(
    rule_id: str,
    passed: bool,
    reason: str,
    *,
    actual_value: Decimal | str | None = None,
    allowed_threshold: Decimal | str | None = None,
) -> RiskRuleResult:
    return RiskRuleResult(
        rule_id=rule_id,
        status=RiskValidationStatus.PASSED if passed else RiskValidationStatus.FAILED,
        reason=reason,
        actual_value=actual_value,
        allowed_threshold=allowed_threshold,
    )


def _packet_for_buy(result: ValueManagerDecisionResult) -> ResearchPacket:
    """Return the packet already uniquely verified by the workflow boundary."""
    ticker = result.recommendation.ticker
    assert ticker is not None  # The recommendation schema enforces this for BUY.
    matching_packets = tuple(packet for packet in result.context.research_batch.packets if packet.ticker == ticker)
    if len(matching_packets) != 1:
        raise ValueError("verified BUY result must have exactly one matching ResearchPacket")
    return matching_packets[0]


def _security_matches_packet(security: SecurityIdentity, packet: ResearchPacket) -> bool:
    if security.ticker != packet.ticker or security.security_type != packet.security_type:
        return False
    for field_name in ("exchange", "currency"):
        packet_value = getattr(packet, field_name)
        if not isinstance(packet_value, MissingData) and getattr(security, field_name) != packet_value:
            return False
    return True


_PASSED_BUY_RULE_IDS = (
    "ACTION_SUPPORTED",
    "WORKFLOW_TICKER_ELIGIBILITY",
    "TARGET_WEIGHT_BOUNDS",
    "PROHIBITED_TRADE_MECHANICS",
    "SECURITY_IDENTITY_MATCH",
    "PORTFOLIO_CURRENCY_MATCH",
    "PRICE_OBSERVATION_TIMESTAMP_NOT_AFTER_VALIDATION",
    "PRICE_OBSERVATION_MARKET_DATE_NOT_AFTER_VALIDATION",
    "CASH_FEASIBILITY",
    "PURCHASABLE_QUANTITY",
)


def _verify_passed_buy_result(
    *,
    decision_result: ValueManagerDecisionResult,
    validation_timestamp: datetime,
    rule_results: tuple[RiskRuleResult, ...],
    target_purchase: TargetPurchaseCalculation | None,
    validated_trade: ValidatedTrade | None,
    price_observation: PriceObservation | None,
) -> None:
    """Enforce the composed BUY result's complete deterministic lineage."""
    if not isinstance(target_purchase, TargetPurchaseCalculation):
        raise ValueError("a passed BUY validation requires a target_purchase")
    if not isinstance(validated_trade, ValidatedTrade):
        raise ValueError("a passed BUY validation requires a validated_trade")
    if not isinstance(price_observation, PriceObservation):
        raise ValueError("a passed BUY validation requires a price_observation")

    missing_rule_ids = set(_PASSED_BUY_RULE_IDS) - {result.rule_id for result in rule_results}
    if missing_rule_ids:
        raise ValueError("a passed BUY validation must include every required rule result")
    if not all(result.passed for result in rule_results):
        raise ValueError("a passed BUY validation must not contain failed rule results")

    recommendation = decision_result.recommendation
    assert recommendation.ticker is not None
    assert recommendation.target_weight is not None
    packet = _packet_for_buy(decision_result)
    if not _security_matches_packet(price_observation.security, packet):
        raise ValueError("price_observation security must match the verified research candidate")
    if price_observation.currency != decision_result.context.portfolio.base_currency:
        raise ValueError("price_observation currency must match portfolio base_currency")
    if price_observation.security.currency != decision_result.context.portfolio.base_currency:
        raise ValueError("price_observation security currency must match portfolio base_currency")
    if price_observation.observed_at > validation_timestamp:
        raise ValueError("price_observation timestamp must not be after validation_timestamp")
    if price_observation.market_date > validation_timestamp.date():
        raise ValueError("price_observation market_date must not be after validation date")

    expected_target_purchase = PortfolioService.calculate_target_purchase(
        decision_result.context.portfolio,
        price_observation.security,
        recommendation.target_weight,
        price_observation.observed_price,
    )
    if target_purchase != expected_target_purchase:
        raise ValueError("target_purchase must match the verified recommendation and price_observation")
    if target_purchase.required_purchase_amount > target_purchase.available_cash:
        raise ValueError("a passed BUY validation requires a fully fundable target purchase")
    if target_purchase.purchasable_quantity.is_zero():
        raise ValueError("a passed BUY validation requires a positive purchasable quantity")

    proposal = validated_trade.proposal
    if validated_trade.validation_timestamp != validation_timestamp:
        raise ValueError("validated_trade validation_timestamp must match validation_timestamp")
    if validated_trade.decision_cycle_id != decision_result.decision_cycle_id:
        raise ValueError("validated_trade decision_cycle_id must match decision_result")
    if validated_trade.portfolio_id != decision_result.portfolio_id:
        raise ValueError("validated_trade portfolio_id must match decision_result")
    if proposal.action != "BUY":
        raise ValueError("validated_trade action must be BUY")
    if proposal.security != price_observation.security:
        raise ValueError("validated_trade security must match price_observation security")
    if proposal.security.ticker != recommendation.ticker:
        raise ValueError("validated_trade security ticker must match recommendation ticker")
    if proposal.target_weight != recommendation.target_weight:
        raise ValueError("validated_trade target_weight must match recommendation target_weight")
    if proposal.proposed_quantity != target_purchase.purchasable_quantity:
        raise ValueError("validated_trade quantity must match target_purchase purchasable_quantity")
    if proposal.proposed_notional_amount != target_purchase.cash_usage:
        raise ValueError("validated_trade notional amount must match target_purchase cash_usage")
    if proposal.price_source_timestamp != price_observation.observed_at:
        raise ValueError("validated_trade price_source_timestamp must match price_observation timestamp")
    expected_rule_ids = tuple(result.rule_id for result in rule_results)
    if validated_trade.validation_results != expected_rule_ids:
        raise ValueError("validated_trade validation_results must match successful rule identifiers")


@dataclass(frozen=True, slots=True)
class DeterministicRiskValidator:
    """Evaluate only settled mechanical rules before review and approval.

    Position-size and concentration thresholds are intentionally deferred until
    the constitution or risk policy supplies concrete numeric limits.
    """

    def validate(
        self,
        decision_result: ValueManagerDecisionResult,
        *,
        validation_timestamp: datetime,
        price_observation: PriceObservation | None = None,
    ) -> RiskValidationResult:
        if not isinstance(decision_result, ValueManagerDecisionResult):
            raise TypeError("decision_result must be a ValueManagerDecisionResult")
        validation_timestamp = _require_aware_datetime(validation_timestamp, field_name="validation_timestamp")
        if validation_timestamp < decision_result.produced_at:
            raise ValueError("validation_timestamp must not precede decision_result produced_at")

        recommendation = decision_result.recommendation
        rule_results = [
            _rule("ACTION_SUPPORTED", True, "The verified recommendation action is supported by the MVP."),
            _rule(
                "WORKFLOW_TICKER_ELIGIBILITY",
                True,
                "Ticker and evidence membership were verified by the workflow boundary.",
            ),
            _rule("TARGET_WEIGHT_BOUNDS", True, "The recommendation schema validated the target-weight bounds."),
            _rule(
                "PROHIBITED_TRADE_MECHANICS",
                True,
                "The buy-only MVP uses positive cash and long-only fractional-share mechanics.",
            ),
        ]
        if recommendation.action is RecommendationAction.HOLD:
            rule_results.append(_rule("HOLD_NO_TRADE", True, "HOLD is a valid no-trade outcome."))
            return RiskValidationResult(
                decision_result=decision_result,
                validation_timestamp=validation_timestamp,
                status=RiskValidationStatus.PASSED,
                rule_results=rule_results,
            )

        if price_observation is None:
            rule_results.append(
                _rule(
                    "PRICE_OBSERVATION_REQUIRED",
                    False,
                    "BUY validation requires a caller-supplied PriceObservation.",
                )
            )
            return self._failed_result(decision_result, validation_timestamp, rule_results)
        if not isinstance(price_observation, PriceObservation):
            raise TypeError("price_observation must be a PriceObservation or None")

        packet = _packet_for_buy(decision_result)
        security_matches = _security_matches_packet(price_observation.security, packet)
        rule_results.append(
            _rule(
                "SECURITY_IDENTITY_MATCH",
                security_matches,
                "The supplied price security must match the verified research candidate.",
                actual_value=price_observation.security.ticker,
                allowed_threshold=packet.ticker,
            )
        )
        currency_matches = (
            price_observation.currency == decision_result.context.portfolio.base_currency
            and price_observation.security.currency == decision_result.context.portfolio.base_currency
        )
        rule_results.append(
            _rule(
                "PORTFOLIO_CURRENCY_MATCH",
                currency_matches,
                "The supplied price and security currency must match the portfolio base currency.",
                actual_value=price_observation.currency,
                allowed_threshold=decision_result.context.portfolio.base_currency,
            )
        )
        rule_results.append(
            _rule(
                "PRICE_OBSERVATION_TIMESTAMP_NOT_AFTER_VALIDATION",
                price_observation.observed_at <= validation_timestamp,
                "The supplied price timestamp must not postdate deterministic validation.",
                actual_value=price_observation.observed_at.isoformat(),
                allowed_threshold=validation_timestamp.isoformat(),
            )
        )
        rule_results.append(
            _rule(
                "PRICE_OBSERVATION_MARKET_DATE_NOT_AFTER_VALIDATION",
                price_observation.market_date <= validation_timestamp.date(),
                "The supplied price market date must not be after the validation date.",
                actual_value=price_observation.market_date.isoformat(),
                allowed_threshold=validation_timestamp.date().isoformat(),
            )
        )
        if not all(result.passed for result in rule_results):
            return self._failed_result(
                decision_result,
                validation_timestamp,
                rule_results,
                price_observation=price_observation,
            )

        calculation = PortfolioService.calculate_target_purchase(
            decision_result.context.portfolio,
            price_observation.security,
            recommendation.target_weight,
            price_observation.observed_price,
        )
        full_target_is_fundable = calculation.required_purchase_amount <= calculation.available_cash
        rule_results.append(
            _rule(
                "CASH_FEASIBILITY",
                full_target_is_fundable,
                "The requested target allocation must be fully fundable from available cash.",
                actual_value=calculation.required_purchase_amount,
                allowed_threshold=calculation.available_cash,
            )
        )
        quantity_is_positive = not calculation.purchasable_quantity.is_zero()
        rule_results.append(
            _rule(
                "PURCHASABLE_QUANTITY",
                quantity_is_positive,
                "The approved BUY must produce a positive quantity at the supported fractional-share increment.",
                actual_value=calculation.purchasable_quantity,
                allowed_threshold=Decimal("0.00000001"),
            )
        )
        if not all(result.passed for result in rule_results):
            return self._failed_result(
                decision_result,
                validation_timestamp,
                rule_results,
                target_purchase=calculation,
                price_observation=price_observation,
            )

        proposal = TradeProposal(
            decision_cycle_id=decision_result.decision_cycle_id,
            portfolio_id=decision_result.portfolio_id,
            security=price_observation.security,
            action="BUY",
            target_weight=recommendation.target_weight,
            proposed_notional_amount=calculation.cash_usage,
            proposed_quantity=calculation.purchasable_quantity,
            price_source_timestamp=price_observation.observed_at,
            reason_reference=decision_result.research_batch_id,
        )
        validated_trade = ValidatedTrade(
            proposal=proposal,
            validation_timestamp=validation_timestamp,
            validation_results=tuple(result.rule_id for result in rule_results),
        )
        return RiskValidationResult(
            decision_result=decision_result,
            validation_timestamp=validation_timestamp,
            status=RiskValidationStatus.PASSED,
            rule_results=rule_results,
            target_purchase=calculation,
            validated_trade=validated_trade,
            price_observation=price_observation,
        )

    @staticmethod
    def _failed_result(
        decision_result: ValueManagerDecisionResult,
        validation_timestamp: datetime,
        rule_results: list[RiskRuleResult],
        *,
        target_purchase: TargetPurchaseCalculation | None = None,
        price_observation: PriceObservation | None = None,
    ) -> RiskValidationResult:
        return RiskValidationResult(
            decision_result=decision_result,
            validation_timestamp=validation_timestamp,
            status=RiskValidationStatus.FAILED,
            rule_results=rule_results,
            target_purchase=target_purchase,
            price_observation=price_observation,
        )
