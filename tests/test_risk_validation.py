from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.constitution import ConstitutionLoader
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio, Position, SecurityIdentity
from agentic_portfolio_lab.domain.portfolio_service import PortfolioService
from agentic_portfolio_lab.domain.recommendations import (
    PortfolioRecommendation,
    RecommendationEvidenceReference,
    ReviewTrigger,
)
from agentic_portfolio_lab.domain.research import EvidenceItem, ResearchBatch, ResearchPacket, ResearchSection
from agentic_portfolio_lab.domain.risk_validation import (
    DeterministicRiskValidator,
    RiskRuleResult,
    RiskValidationResult,
    RiskValidationStatus,
)
from agentic_portfolio_lab.domain.trades import ValidatedTrade
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.domain.value_manager import ValueManagerDecisionContext
from agentic_portfolio_lab.domain.value_manager_workflow import ValueManagerDecisionResult


UTC = timezone.utc
CREATED_AT = datetime(2026, 8, 10, 13, tzinfo=UTC)
VALIDATED_AT = datetime(2026, 8, 10, 14, tzinfo=UTC)


def _portfolio(*, cash: Decimal = Decimal("1000"), positions: tuple[Position, ...] = ()) -> Portfolio:
    return Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Value Portfolio",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance(currency="USD", amount=cash),
        created_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
        positions=positions,
    )


def _evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev_aapl_001",
        source_type="FILING",
        source_title="Quarterly Report",
        source_date=date(2026, 8, 9),
        claim_supported="Operating cash flow remained positive.",
    )


def _packet() -> ResearchPacket:
    evidence = _evidence()
    return ResearchPacket(
        packet_id="packet_aapl",
        candidate_id="candidate_aapl",
        ticker="AAPL",
        security_type="EQUITY",
        exchange="NASDAQ",
        currency="USD",
        as_of_timestamp=datetime(2026, 8, 10, 12, tzinfo=UTC),
        evidence_items=(evidence,),
        sections=(
            ResearchSection(
                section_id="BUSINESS_OVERVIEW",
                content="The company sells devices and services.",
                evidence_ids=(evidence.evidence_id,),
            ),
        ),
    )


def _result(portfolio: Portfolio, *, action: str = "BUY", target_weight: Decimal | None = None) -> ValueManagerDecisionResult:
    evidence = _evidence()
    packet = _packet()
    batch = ResearchBatch(
        batch_id="batch_001",
        decision_cycle_id=uuid4(),
        portfolio_id=portfolio.portfolio_id,
        manager_type="VALUE",
        created_at=CREATED_AT,
        as_of_timestamp=datetime(2026, 8, 10, 12, tzinfo=UTC),
        packets=(packet,),
    )
    context = ValueManagerDecisionContext(
        portfolio=portfolio,
        research_batch=batch,
        constitution=ConstitutionLoader.load_value_manager_constitution(),
    )
    recommendation = PortfolioRecommendation(
        action=action,
        ticker="AAPL" if action == "BUY" else None,
        target_weight=target_weight if target_weight is not None else (Decimal("0.10") if action == "BUY" else None),
        decision_rationale="The evidence supports a durable, attractive business.",
        investment_thesis="Cash generation can compound over time." if action == "BUY" else None,
        valuation="The valuation is reasonable relative to cash generation.",
        risks=("Demand could weaken.",),
        confidence_score=72,
        evidence=(
            RecommendationEvidenceReference(
                evidence_id=evidence.evidence_id,
                source_type=evidence.source_type,
                source_title=evidence.source_title,
                source_date=evidence.source_date,
                claim_supported="The filing supports positive operating cash flow.",
            ),
        ),
        why_not_spy="This evidence-backed opportunity is more compelling than incremental SPY exposure.",
        thesis_invalidation=("Cash generation deteriorates materially.",) if action == "BUY" else (),
        review_triggers=(ReviewTrigger("EVENT_BASED", "Review after a material earnings miss."),),
    )
    return ValueManagerDecisionResult(context=context, recommendation=recommendation, produced_at=CREATED_AT)


def _security(*, ticker: str = "AAPL", currency: str = "USD") -> SecurityIdentity:
    return SecurityIdentity(ticker=ticker, security_type="EQUITY", exchange="NASDAQ", currency=currency)


def _price_observation(*, security: SecurityIdentity | None = None, price: Decimal = Decimal("100"), **overrides: object) -> PriceObservation:
    fields: dict[str, object] = {
        "security": security or _security(),
        "observed_price": price,
        "market_date": VALIDATED_AT.date(),
        "observed_at": VALIDATED_AT,
        "currency": "USD",
        "source_provider_identity": "test-provider",
        "price_convention": "regular-session-close",
    }
    fields.update(overrides)
    return PriceObservation(**fields)  # type: ignore[arg-type]


def _rule(result: RiskValidationResult, rule_id: str) -> RiskRuleResult:
    return next(rule for rule in result.rule_results if rule.rule_id == rule_id)


def test_hold_passes_without_creating_trade_or_mutating_portfolio() -> None:
    portfolio = _portfolio()
    result = DeterministicRiskValidator().validate(_result(portfolio, action="HOLD"), validation_timestamp=VALIDATED_AT)

    assert result.passed
    assert result.validated_trade is None
    assert result.proposal is None
    assert _rule(result, "HOLD_NO_TRADE").passed
    assert portfolio.cash_balance.amount == Decimal("1000")
    assert portfolio.positions == ()


def test_valid_buy_creates_a_validated_trade_without_mutating_portfolio() -> None:
    portfolio = _portfolio()
    observation = _price_observation()
    result = DeterministicRiskValidator().validate(
        _result(portfolio), validation_timestamp=VALIDATED_AT, price_observation=observation
    )

    assert result.passed
    assert result.target_purchase is not None
    assert result.validated_trade is not None
    assert result.proposal is result.validated_trade.proposal
    assert result.proposal.proposed_quantity == Decimal("1.00000000")
    assert result.proposal.proposed_notional_amount == Decimal("100.00000000")
    assert result.validated_trade.decision_cycle_id == result.decision_result.decision_cycle_id
    assert result.price_observation is observation
    assert result.price_observation.source_provider_identity == "test-provider"
    assert result.price_observation.price_convention == "regular-session-close"
    assert result.validated_trade.validation_results == tuple(rule.rule_id for rule in result.rule_results)
    assert portfolio.cash_balance.amount == Decimal("1000")
    assert portfolio.positions == ()


def test_buy_fails_when_target_is_not_fully_fundable() -> None:
    result = DeterministicRiskValidator().validate(
        _result(
            _portfolio(
                cash=Decimal("50"),
                positions=(Position(_security(ticker="MSFT"), Decimal("1"), Decimal("950"), Decimal("950")),),
            ),
            target_weight=Decimal("0.10"),
        ),
        validation_timestamp=VALIDATED_AT,
        price_observation=_price_observation(),
    )

    assert not result.passed
    assert result.validated_trade is None
    assert result.target_purchase is not None
    assert not _rule(result, "CASH_FEASIBILITY").passed
    assert _rule(result, "CASH_FEASIBILITY").actual_value == Decimal("100.00")
    assert _rule(result, "CASH_FEASIBILITY").allowed_threshold == Decimal("50")


def test_buy_fails_when_no_supported_fractional_increment_is_affordable() -> None:
    result = DeterministicRiskValidator().validate(
        _result(_portfolio(cash=Decimal("0.000000001")), target_weight=Decimal("0.1")),
        validation_timestamp=VALIDATED_AT,
        price_observation=_price_observation(),
    )

    assert not result.passed
    assert not _rule(result, "PURCHASABLE_QUANTITY").passed


def test_buy_rejects_wrong_security_or_currency() -> None:
    validator = DeterministicRiskValidator()
    wrong_security = validator.validate(
        _result(_portfolio()),
        validation_timestamp=VALIDATED_AT,
        price_observation=_price_observation(security=_security(ticker="MSFT")),
    )
    wrong_currency = validator.validate(
        _result(_portfolio()),
        validation_timestamp=VALIDATED_AT,
        price_observation=_price_observation(security=_security(currency="EUR"), currency="EUR"),
    )

    assert not _rule(wrong_security, "SECURITY_IDENTITY_MATCH").passed
    assert not _rule(wrong_currency, "PORTFOLIO_CURRENCY_MATCH").passed


def test_buy_requires_caller_supplied_price_and_audits_lookahead_data() -> None:
    validator = DeterministicRiskValidator()
    no_price = validator.validate(_result(_portfolio()), validation_timestamp=VALIDATED_AT)
    future_price = validator.validate(
        _result(_portfolio()),
        validation_timestamp=VALIDATED_AT,
        price_observation=_price_observation(observed_at=VALIDATED_AT + timedelta(seconds=1)),
    )
    future_market_date = validator.validate(
        _result(_portfolio()),
        validation_timestamp=VALIDATED_AT,
        price_observation=_price_observation(market_date=VALIDATED_AT.date() + timedelta(days=1)),
    )

    assert not _rule(no_price, "PRICE_OBSERVATION_REQUIRED").passed
    timestamp_rule = _rule(future_price, "PRICE_OBSERVATION_TIMESTAMP_NOT_AFTER_VALIDATION")
    market_date_rule = _rule(future_market_date, "PRICE_OBSERVATION_MARKET_DATE_NOT_AFTER_VALIDATION")
    assert not timestamp_rule.passed
    assert timestamp_rule.actual_value == (VALIDATED_AT + timedelta(seconds=1)).isoformat()
    assert timestamp_rule.allowed_threshold == VALIDATED_AT.isoformat()
    assert not market_date_rule.passed
    assert market_date_rule.actual_value == (VALIDATED_AT.date() + timedelta(days=1)).isoformat()
    assert market_date_rule.allowed_threshold == VALIDATED_AT.date().isoformat()


def test_price_observation_time_cutoff_equalities_are_allowed() -> None:
    result = DeterministicRiskValidator().validate(
        _result(_portfolio()),
        validation_timestamp=VALIDATED_AT,
        price_observation=_price_observation(observed_at=VALIDATED_AT, market_date=VALIDATED_AT.date()),
    )

    assert result.passed
    assert _rule(result, "PRICE_OBSERVATION_TIMESTAMP_NOT_AFTER_VALIDATION").passed
    assert _rule(result, "PRICE_OBSERVATION_MARKET_DATE_NOT_AFTER_VALIDATION").passed


def test_validation_timestamp_requires_aware_datetime_and_cannot_precede_decision() -> None:
    validator = DeterministicRiskValidator()
    decision = _result(_portfolio())

    with pytest.raises(ValueError, match="timezone-aware"):
        validator.validate(decision, validation_timestamp=datetime(2026, 8, 10, 14), price_observation=_price_observation())
    with pytest.raises(ValueError, match="must not precede"):
        validator.validate(
            decision,
            validation_timestamp=CREATED_AT - timedelta(seconds=1),
            price_observation=_price_observation(),
        )


def test_validation_is_independent_of_ambient_decimal_context() -> None:
    portfolio = _portfolio(cash=Decimal("1234.56789"))
    decision = _result(portfolio, target_weight=Decimal("0.333333"))
    observation = _price_observation(price=Decimal("123.456789"))

    def validate_at_precision(precision: int) -> RiskValidationResult:
        with localcontext() as context:
            context.prec = precision
            return DeterministicRiskValidator().validate(
                decision, validation_timestamp=VALIDATED_AT, price_observation=observation
            )

    low_precision = validate_at_precision(6)
    high_precision = validate_at_precision(50)
    assert low_precision.status == high_precision.status
    assert low_precision.target_purchase == high_precision.target_purchase
    assert low_precision.proposal is not None and high_precision.proposal is not None
    assert low_precision.proposal.proposed_notional_amount == high_precision.proposal.proposed_notional_amount
    assert low_precision.proposal.proposed_quantity == high_precision.proposal.proposed_quantity


def test_exact_cash_exhaustion_is_valid() -> None:
    result = DeterministicRiskValidator().validate(
        _result(_portfolio(cash=Decimal("1000")), target_weight=Decimal("1")),
        validation_timestamp=VALIDATED_AT,
        price_observation=_price_observation(),
    )

    assert result.passed
    assert result.target_purchase is not None
    assert result.target_purchase.cash_usage == Decimal("1000.00000000")
    assert result.target_purchase.remaining_cash == Decimal("0.00000000")


def test_existing_position_at_target_does_not_create_a_zero_quantity_buy() -> None:
    portfolio = _portfolio(
        cash=Decimal("100"),
        positions=(Position(_security(), Decimal("1"), Decimal("100"), Decimal("100")),),
    )
    result = DeterministicRiskValidator().validate(
        _result(portfolio, target_weight=Decimal("0.5")),
        validation_timestamp=VALIDATED_AT,
        price_observation=_price_observation(),
    )

    assert not result.passed
    assert result.target_purchase is not None
    assert result.target_purchase.required_purchase_amount == Decimal("0.0")
    assert not _rule(result, "PURCHASABLE_QUANTITY").passed


def test_target_purchase_uses_supplied_price_instead_of_stored_position_price() -> None:
    portfolio = _portfolio(
        cash=Decimal("100"),
        positions=(Position(_security(), Decimal("1"), Decimal("1"), Decimal("1")),),
    )
    result = DeterministicRiskValidator().validate(
        _result(portfolio, target_weight=Decimal("0.75")),
        validation_timestamp=VALIDATED_AT,
        price_observation=_price_observation(price=Decimal("100")),
    )

    assert result.passed
    assert result.target_purchase is not None
    assert result.target_purchase.portfolio_value == Decimal("200")
    assert result.target_purchase.current_security_value == Decimal("100")
    assert result.target_purchase.required_purchase_amount == Decimal("50.00")


def test_passed_buy_result_rejects_direct_construction_mismatches() -> None:
    decision = _result(_portfolio())
    observation = _price_observation()
    valid = DeterministicRiskValidator().validate(
        decision,
        validation_timestamp=VALIDATED_AT,
        price_observation=observation,
    )
    assert valid.target_purchase is not None
    assert valid.validated_trade is not None

    wrong_security = _security(ticker="MSFT")
    wrong_security_purchase = PortfolioService.calculate_target_purchase(
        decision.context.portfolio,
        wrong_security,
        Decimal("0.1"),
        Decimal("100"),
    )
    wrong_security_proposal = replace(valid.validated_trade.proposal, security=wrong_security)
    wrong_security_trade = ValidatedTrade(
        proposal=wrong_security_proposal,
        validation_timestamp=VALIDATED_AT,
        validation_results=valid.validated_trade.validation_results,
    )
    with pytest.raises(ValueError, match="price_observation security"):
        RiskValidationResult(
            decision_result=decision,
            validation_timestamp=VALIDATED_AT,
            status=RiskValidationStatus.PASSED,
            rule_results=valid.rule_results,
            target_purchase=wrong_security_purchase,
            validated_trade=wrong_security_trade,
            price_observation=_price_observation(security=wrong_security),
        )

    wrong_weight_purchase = PortfolioService.calculate_target_purchase(
        decision.context.portfolio,
        observation.security,
        Decimal("0.2"),
        observation.observed_price,
    )
    wrong_weight_proposal = replace(valid.validated_trade.proposal, target_weight=Decimal("0.2"))
    wrong_weight_trade = ValidatedTrade(
        proposal=wrong_weight_proposal,
        validation_timestamp=VALIDATED_AT,
        validation_results=valid.validated_trade.validation_results,
    )
    with pytest.raises(ValueError, match="target_purchase"):
        RiskValidationResult(
            decision_result=decision,
            validation_timestamp=VALIDATED_AT,
            status=RiskValidationStatus.PASSED,
            rule_results=valid.rule_results,
            target_purchase=wrong_weight_purchase,
            validated_trade=wrong_weight_trade,
            price_observation=observation,
        )

    quantity_proposal = replace(valid.validated_trade.proposal, proposed_quantity=Decimal("2"))
    quantity_trade = ValidatedTrade(
        proposal=quantity_proposal,
        validation_timestamp=VALIDATED_AT,
        validation_results=valid.validated_trade.validation_results,
    )
    with pytest.raises(ValueError, match="quantity"):
        RiskValidationResult(
            decision_result=decision,
            validation_timestamp=VALIDATED_AT,
            status=RiskValidationStatus.PASSED,
            rule_results=valid.rule_results,
            target_purchase=valid.target_purchase,
            validated_trade=quantity_trade,
            price_observation=observation,
        )

    notional_proposal = replace(valid.validated_trade.proposal, proposed_notional_amount=Decimal("99"))
    notional_trade = ValidatedTrade(
        proposal=notional_proposal,
        validation_timestamp=VALIDATED_AT,
        validation_results=valid.validated_trade.validation_results,
    )
    with pytest.raises(ValueError, match="notional"):
        RiskValidationResult(
            decision_result=decision,
            validation_timestamp=VALIDATED_AT,
            status=RiskValidationStatus.PASSED,
            rule_results=valid.rule_results,
            target_purchase=valid.target_purchase,
            validated_trade=notional_trade,
            price_observation=observation,
        )

    missing_validation_result_trade = ValidatedTrade(
        proposal=valid.validated_trade.proposal,
        validation_timestamp=VALIDATED_AT,
        validation_results=valid.validated_trade.validation_results[:-1],
    )
    with pytest.raises(ValueError, match="validation_results"):
        RiskValidationResult(
            decision_result=decision,
            validation_timestamp=VALIDATED_AT,
            status=RiskValidationStatus.PASSED,
            rule_results=valid.rule_results,
            target_purchase=valid.target_purchase,
            validated_trade=missing_validation_result_trade,
            price_observation=observation,
        )


def test_risk_result_enforces_its_own_audit_and_lifecycle_invariants() -> None:
    decision = _result(_portfolio(), action="HOLD")
    passed_rule = RiskRuleResult("TEST", RiskValidationStatus.PASSED, "Passed.")

    with pytest.raises(ValueError, match="status must match"):
        RiskValidationResult(
            decision_result=decision,
            validation_timestamp=VALIDATED_AT,
            status=RiskValidationStatus.FAILED,
            rule_results=(passed_rule,),
        )
    with pytest.raises(ValueError, match="HOLD validation"):
        RiskValidationResult(
            decision_result=decision,
            validation_timestamp=VALIDATED_AT,
            status=RiskValidationStatus.PASSED,
            rule_results=(passed_rule,),
            target_purchase=object(),  # type: ignore[arg-type]
        )


def test_rule_results_are_immutable_and_reject_invalid_audit_values() -> None:
    rule = RiskRuleResult("cash feasibility", RiskValidationStatus.FAILED, "Insufficient cash.", actual_value=Decimal("1"))

    assert rule.rule_id == "CASH FEASIBILITY"
    with pytest.raises(AttributeError):
        rule.reason = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="finite"):
        RiskRuleResult("TEST", RiskValidationStatus.FAILED, "Bad value.", actual_value=Decimal("NaN"))
