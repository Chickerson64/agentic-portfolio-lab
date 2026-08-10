"""Deterministic post-approval simulated BUY execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .approval import ApprovalDecision, DecisionApproval
from .portfolio import Portfolio, _require_aware_datetime
from .portfolio_service import PortfolioService, TargetPurchaseCalculation
from .recommendations import RecommendationAction
from .trades import ExecutedTrade, ValidatedTrade
from .valuation import PriceObservation


@dataclass(frozen=True, slots=True)
class SimulatedExecutionResult:
    """Auditable immutable result of one approved, recalculated simulated fill."""

    approval: DecisionApproval
    original_portfolio: Portfolio
    execution_observation: PriceObservation
    execution_target_purchase: TargetPurchaseCalculation
    executed_trade: ExecutedTrade
    updated_portfolio: Portfolio

    def __post_init__(self) -> None:
        if not isinstance(self.approval, DecisionApproval):
            raise TypeError("approval must be a DecisionApproval")
        if self.approval.decision is not ApprovalDecision.APPROVED:
            raise ValueError("simulated execution requires APPROVED human decision")
        if not isinstance(self.original_portfolio, Portfolio) or not isinstance(self.updated_portfolio, Portfolio):
            raise TypeError("portfolio states must be Portfolio instances")
        if not isinstance(self.execution_observation, PriceObservation):
            raise TypeError("execution_observation must be a PriceObservation")
        if not isinstance(self.execution_target_purchase, TargetPurchaseCalculation):
            raise TypeError("execution_target_purchase must be a TargetPurchaseCalculation")
        if not isinstance(self.executed_trade, ExecutedTrade):
            raise TypeError("executed_trade must be an ExecutedTrade")
        validation = self.approval.journal_entry.risk_validation_result
        recommendation = self.approval.journal_entry.decision_result.recommendation
        if not validation.passed or recommendation.action is not RecommendationAction.BUY:
            raise ValueError("simulated execution requires passed BUY validation")
        if validation.validated_trade is None or self.executed_trade.validated_trade != validation.validated_trade:
            raise ValueError("executed_trade must retain the approved validated_trade")
        if self.original_portfolio.portfolio_id != self.approval.portfolio_id:
            raise ValueError("original portfolio must match approval")
        if self.executed_trade.portfolio_id != self.approval.portfolio_id:
            raise ValueError("executed_trade portfolio must match approval")
        if self.executed_trade.decision_cycle_id != self.approval.decision_cycle_id:
            raise ValueError("executed_trade decision cycle must match approval")
        if self.execution_observation.security != self.executed_trade.security:
            raise ValueError("execution observation security must match executed trade")
        if self.execution_observation.currency != self.original_portfolio.base_currency:
            raise ValueError("execution observation currency must match portfolio")
        if self.execution_observation.observed_at > self.executed_trade.executed_at:
            raise ValueError("executed_at must not precede execution observation")
        if self.execution_observation.observed_at < self.approval.decided_at:
            raise ValueError("execution observation must not precede approval")
        if self.executed_trade.executed_at < self.approval.decided_at:
            raise ValueError("executed_at must not precede approval")
        if self.execution_observation.market_date > self.executed_trade.executed_at.date():
            raise ValueError("execution observation market_date must not be after executed_at date")
        expected = PortfolioService.calculate_target_purchase(
            self.original_portfolio,
            self.execution_observation.security,
            recommendation.target_weight,
            self.execution_observation.observed_price,
        )
        if self.execution_target_purchase != expected:
            raise ValueError("execution target purchase must match current portfolio and execution observation")
        if expected.required_purchase_amount > expected.available_cash or expected.purchasable_quantity.is_zero():
            raise ValueError("execution target purchase must be fully cash-feasible and positive")
        if self.executed_trade.executed_quantity != expected.purchasable_quantity:
            raise ValueError("executed quantity must match execution-time target purchase")
        if self.executed_trade.execution_price != self.execution_observation.observed_price:
            raise ValueError("execution price must match execution observation")
        if self.executed_trade.currency != self.execution_observation.currency:
            raise ValueError("executed trade currency must match execution observation")
        if self.executed_trade.source_provider_identity != self.execution_observation.source_provider_identity:
            raise ValueError("executed trade provider must match execution observation")
        if self.executed_trade.market_date != self.execution_observation.market_date:
            raise ValueError("executed trade market_date must match execution observation")
        if self.executed_trade.price_convention != self.execution_observation.price_convention:
            raise ValueError("executed trade price_convention must match execution observation")
        if self.updated_portfolio != PortfolioService.execute_validated_trade(self.original_portfolio, self.executed_trade):
            raise ValueError("updated portfolio must exactly reflect executed trade")

    @property
    def decision_cycle_id(self):
        return self.approval.decision_cycle_id


class SimulatedExecutionWorkflow:
    """Apply only an approved, passed BUY using caller-supplied execution data."""

    @staticmethod
    def execute(
        approval: DecisionApproval,
        portfolio: Portfolio,
        execution_observation: PriceObservation,
        *,
        executed_at: datetime,
    ) -> SimulatedExecutionResult:
        if not isinstance(approval, DecisionApproval):
            raise TypeError("approval must be a DecisionApproval")
        if not isinstance(portfolio, Portfolio):
            raise TypeError("portfolio must be a Portfolio")
        if not isinstance(execution_observation, PriceObservation):
            raise TypeError("execution_observation must be a PriceObservation")
        executed_at = _require_aware_datetime(executed_at, field_name="executed_at")
        if approval.decision is not ApprovalDecision.APPROVED:
            raise ValueError("simulated execution requires APPROVED human decision")
        validation = approval.journal_entry.risk_validation_result
        recommendation = approval.journal_entry.decision_result.recommendation
        if not validation.passed or recommendation.action is not RecommendationAction.BUY or validation.validated_trade is None:
            raise ValueError("simulated execution requires passed BUY validation with ValidatedTrade")
        if portfolio.portfolio_id != approval.portfolio_id:
            raise ValueError("portfolio must match approval")
        if execution_observation.security != validation.validated_trade.security:
            raise ValueError("execution observation security must match validated trade")
        if execution_observation.currency != portfolio.base_currency:
            raise ValueError("execution observation currency must match portfolio")
        if execution_observation.observed_at < approval.decided_at:
            raise ValueError("execution observation must not precede approval")
        if executed_at < approval.decided_at or executed_at < execution_observation.observed_at:
            raise ValueError("executed_at must not precede approval or execution observation")
        if execution_observation.market_date > executed_at.date():
            raise ValueError("execution observation market_date must not be after executed_at date")
        calculation = PortfolioService.calculate_target_purchase(
            portfolio, execution_observation.security, recommendation.target_weight, execution_observation.observed_price
        )
        if calculation.required_purchase_amount > calculation.available_cash:
            raise ValueError("execution target purchase is not fully cash-feasible")
        if calculation.purchasable_quantity.is_zero():
            raise ValueError("execution target purchase quantity must be positive")
        trade = ExecutedTrade(
            validated_trade=validation.validated_trade,
            executed_quantity=calculation.purchasable_quantity,
            execution_price=execution_observation.observed_price,
            source_provider_identity=execution_observation.source_provider_identity,
            market_date=execution_observation.market_date,
            currency=execution_observation.currency,
            price_convention=execution_observation.price_convention,
            executed_at=executed_at,
        )
        updated = PortfolioService.execute_validated_trade(portfolio, trade)
        return SimulatedExecutionResult(approval, portfolio, execution_observation, calculation, trade, updated)
