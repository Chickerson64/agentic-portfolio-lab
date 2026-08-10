"""Tests for immutable human approval records over journaled decisions."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.approval import ApprovalDecision, DecisionApproval
from agentic_portfolio_lab.domain.journal import DecisionJournalEntry
from agentic_portfolio_lab.domain.portfolio import CashBalance, Portfolio, SecurityIdentity
from agentic_portfolio_lab.domain.recommendations import (
    PortfolioRecommendation,
    RecommendationEvidenceReference,
    ReviewTrigger,
)
from agentic_portfolio_lab.domain.research import EvidenceItem, ResearchBatch, ResearchPacket, ResearchSection
from agentic_portfolio_lab.domain.reviewer import AIReviewerReviewContext, ReviewDecision, ReviewFinding, ReviewerResult
from agentic_portfolio_lab.domain.risk_validation import DeterministicRiskValidator
from agentic_portfolio_lab.domain.valuation import PriceObservation
from agentic_portfolio_lab.domain.value_manager import ValueManagerDecisionContext
from agentic_portfolio_lab.domain.value_manager_workflow import ValueManagerDecisionResult
from agentic_portfolio_lab.domain.constitution import ConstitutionLoader


UTC = timezone.utc
CREATED_AT = datetime(2026, 8, 10, 13, tzinfo=UTC)
PRODUCED_AT = datetime(2026, 8, 10, 14, tzinfo=UTC)
VALIDATED_AT = datetime(2026, 8, 10, 15, tzinfo=UTC)
REVIEWED_AT = datetime(2026, 8, 10, 16, tzinfo=UTC)
JOURNALED_AT = datetime(2026, 8, 10, 17, tzinfo=UTC)
DECIDED_AT = datetime(2026, 8, 10, 18, tzinfo=UTC)


def _portfolio() -> Portfolio:
    return Portfolio(
        portfolio_id=uuid4(),
        portfolio_name="Value Portfolio",
        base_currency="USD",
        starting_capital=Decimal("1000"),
        cash_balance=CashBalance(currency="USD", amount=Decimal("1000")),
        created_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
    )


def _decision_result(*, action: str = "BUY") -> ValueManagerDecisionResult:
    portfolio = _portfolio()
    evidence = EvidenceItem(
        evidence_id="ev_aapl_001",
        source_type="FILING",
        source_title="Quarterly Report",
        source_date=CREATED_AT.date(),
        claim_supported="Operating cash flow remained positive.",
    )
    packet = ResearchPacket(
        packet_id="packet_aapl",
        candidate_id="candidate_aapl",
        ticker="AAPL",
        security_type="EQUITY",
        exchange="NASDAQ",
        currency="USD",
        as_of_timestamp=CREATED_AT,
        evidence_items=(evidence,),
        sections=(ResearchSection("BUSINESS_OVERVIEW", "A durable operating business.", (evidence.evidence_id,)),),
    )
    batch = ResearchBatch(
        batch_id="batch_001",
        decision_cycle_id=uuid4(),
        portfolio_id=portfolio.portfolio_id,
        manager_type="VALUE",
        created_at=CREATED_AT,
        as_of_timestamp=CREATED_AT,
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
        target_weight=Decimal("0.10") if action == "BUY" else None,
        decision_rationale="The supplied evidence supports this decision.",
        investment_thesis="Durable cash generation can compound." if action == "BUY" else None,
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
        why_not_spy="This opportunity is more compelling than incremental SPY exposure.",
        thesis_invalidation=("Cash generation deteriorates materially.",) if action == "BUY" else (),
        review_triggers=(ReviewTrigger("EVENT_BASED", "Review after a material earnings miss."),),
    )
    return ValueManagerDecisionResult(context=context, recommendation=recommendation, produced_at=PRODUCED_AT)


def _journal_entry(
    *,
    action: str = "BUY",
    passed: bool = True,
    reviewer_decision: ReviewDecision | None = None,
) -> DecisionJournalEntry:
    decision = _decision_result(action=action)
    validator = DeterministicRiskValidator()
    if action == "HOLD" or not passed:
        risk = validator.validate(decision, validation_timestamp=VALIDATED_AT)
    else:
        risk = validator.validate(
            decision,
            validation_timestamp=VALIDATED_AT,
            price_observation=PriceObservation(
                security=SecurityIdentity("AAPL", "EQUITY", "NASDAQ", "USD"),
                observed_price=Decimal("100"),
                market_date=VALIDATED_AT.date(),
                observed_at=VALIDATED_AT,
                currency="USD",
                source_provider_identity="test-provider",
                price_convention="regular-session-close",
            ),
        )
    reviewer_result = None
    if reviewer_decision is not None:
        review_context = AIReviewerReviewContext(
            decision_result=decision,
            risk_validation_result=risk,
            constitution=decision.context.constitution,
        )
        reviewer_result = ReviewerResult(
            context=review_context,
            decision=reviewer_decision,
            findings=(
                ()
                if reviewer_decision is ReviewDecision.APPROVE
                else (
                    ReviewFinding(
                        "WARNING", "EVIDENCE_USAGE", "Clarify the downside case.", ("ev_aapl_001",), "risks"
                    ),
                )
            ),
            reviewed_at=REVIEWED_AT,
        )
    return DecisionJournalEntry(
        decision_result=decision,
        risk_validation_result=risk,
        reviewer_result=reviewer_result,
        journaled_at=JOURNALED_AT,
    )


def test_approved_buy_and_hold_preserve_authoritative_journal_lineage() -> None:
    buy = DecisionApproval(_journal_entry(), " user-42 ", " approved ", DECIDED_AT, " Looks good. ")
    hold = DecisionApproval(_journal_entry(action="HOLD"), "user-42", "APPROVED", DECIDED_AT)

    assert buy.decision is ApprovalDecision.APPROVED
    assert buy.decision_maker_id == "user-42"
    assert buy.comment == "Looks good."
    assert buy.decision_cycle_id == buy.journal_entry.decision_cycle_id
    assert buy.portfolio_id == buy.journal_entry.portfolio_id
    assert hold.decision is ApprovalDecision.APPROVED


def test_rejected_and_expired_buy_are_valid_terminal_human_decisions() -> None:
    journal = _journal_entry()

    assert DecisionApproval(journal, "user-42", "REJECTED", DECIDED_AT).decision is ApprovalDecision.REJECTED
    assert DecisionApproval(journal, "user-42", "EXPIRED", DECIDED_AT).decision is ApprovalDecision.EXPIRED


def test_failed_deterministic_validation_cannot_be_approved_but_can_be_closed_otherwise() -> None:
    journal = _journal_entry(passed=False)

    with pytest.raises(ValueError, match="passed deterministic validation"):
        DecisionApproval(journal, "user-42", "APPROVED", DECIDED_AT)
    assert DecisionApproval(journal, "user-42", "REJECTED", DECIDED_AT).decision is ApprovalDecision.REJECTED
    assert DecisionApproval(journal, "user-42", "EXPIRED", DECIDED_AT).decision is ApprovalDecision.EXPIRED


def test_human_can_override_either_reviewer_recommendation() -> None:
    journal = _journal_entry(reviewer_decision=ReviewDecision.REQUEST_CHANGES)

    assert journal.reviewer_result is not None
    assert journal.reviewer_result.decision is ReviewDecision.REQUEST_CHANGES
    assert DecisionApproval(journal, "user-42", "APPROVED", DECIDED_AT).decision is ApprovalDecision.APPROVED
    approved_reviewer_journal = _journal_entry(reviewer_decision=ReviewDecision.APPROVE)
    assert approved_reviewer_journal.reviewer_result is not None
    assert approved_reviewer_journal.reviewer_result.decision is ReviewDecision.APPROVE
    assert (
        DecisionApproval(approved_reviewer_journal, "user-42", "REJECTED", DECIDED_AT).decision
        is ApprovalDecision.REJECTED
    )


def test_approval_requires_aware_timestamp_not_before_journaling() -> None:
    journal = _journal_entry()

    assert DecisionApproval(journal, "user-42", "APPROVED", JOURNALED_AT).decided_at == JOURNALED_AT
    with pytest.raises(ValueError, match="timezone-aware"):
        DecisionApproval(journal, "user-42", "APPROVED", DECIDED_AT.replace(tzinfo=None))
    with pytest.raises(ValueError, match="must not precede"):
        DecisionApproval(journal, "user-42", "APPROVED", JOURNALED_AT - timedelta(microseconds=1))


def test_direct_construction_rejects_malformed_or_impossible_approval_records() -> None:
    journal = _journal_entry()

    with pytest.raises(TypeError, match="journal_entry"):
        DecisionApproval("not-a-journal", "user-42", "APPROVED", DECIDED_AT)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="decision_maker_id"):
        DecisionApproval(journal, "  ", "APPROVED", DECIDED_AT)
    with pytest.raises(ValueError, match="comment"):
        DecisionApproval(journal, "user-42", "APPROVED", DECIDED_AT, "  ")
    with pytest.raises(ValueError, match="decision must be one of"):
        DecisionApproval(journal, "user-42", "PENDING", DECIDED_AT)


def test_approval_is_immutable_and_contains_no_execution_or_portfolio_mutation_fields() -> None:
    approval = DecisionApproval(_journal_entry(), "user-42", "APPROVED", DECIDED_AT)

    with pytest.raises(FrozenInstanceError):
        approval.decision = ApprovalDecision.REJECTED  # type: ignore[misc]
    assert {field.name for field in fields(DecisionApproval)} == {
        "journal_entry",
        "decision_maker_id",
        "decision",
        "decided_at",
        "comment",
    }
