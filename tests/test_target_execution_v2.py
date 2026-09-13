from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain import CashBalance, CashClassification, CashTarget, ExistingHoldingDisposition, Portfolio, PortfolioTargetAllocation, PortfolioTargetPosition, Position, RecommendationEvidenceReference, SecurityIdentity, V2PriceSnapshot, BatchApproval, BatchTradeAction, derive_batch_trade_plan, execute_approved_batch
from agentic_portfolio_lab.domain.recommendations import ReviewTrigger
from agentic_portfolio_lab.domain.valuation import PriceObservation

NOW = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
def sec(ticker): return SecurityIdentity(ticker, "EQUITY", "NASDAQ", "USD")
def pos(ticker, qty, price=10): return Position(sec(ticker), Decimal(qty), Decimal(qty) * Decimal(price), Decimal(price))
def quote(ticker, price=10): return PriceObservation(sec(ticker), Decimal(price), date(2026, 9, 13), NOW, "USD", "test", "close")
def target(portfolio, rows, cash):
    positions = tuple(PortfolioTargetPosition(sec(ticker), Decimal(weight), "role", "thesis", 80, (RecommendationEvidenceReference(ticker, "filing", "evidence", date(2026, 1, 1), "supports"),), (), (ReviewTrigger("scheduled", "quarterly"),), disposition) for ticker, weight, disposition in rows)
    return PortfolioTargetAllocation(portfolio.portfolio_id, "rationale", "risk", "concentration", "active risk", CashTarget(Decimal(cash), CashClassification.STRATEGIC, "reserve"), positions)
def portfolio(cash, *positions): return Portfolio(uuid4(), "p", "USD", Decimal("100"), CashBalance("USD", Decimal(cash)), NOW, positions)

def test_buy_only_and_no_op_are_derived_at_exact_8dp_precision():
    p = portfolio("100")
    plan = derive_batch_trade_plan(target(p, [("AAPL", ".5", "INITIATE")], ".5"), p, V2PriceSnapshot((quote("AAPL", 10),)), created_at=NOW)
    assert [(x.action, x.quantity) for x in plan.legs] == [(BatchTradeAction.BUY, Decimal("5.00000000"))]
    tiny = derive_batch_trade_plan(target(p, [("AAPL", ".000001", "INITIATE")], ".999999"), p, V2PriceSnapshot((quote("AAPL", 1000000),)), created_at=NOW)
    assert tiny.legs == ()
    with pytest.raises(ValueError, match="no-action"):
        BatchApproval(tiny, "human", NOW)

def test_sell_trim_and_explicit_exit_semantics():
    p = portfolio("0", pos("AAPL", "5"), pos("MSFT", "5"), pos("IBM", "5"))
    t = target(p, [("AAPL", ".25", "REDUCE"), ("MSFT", "0", "REMOVE")], ".75")
    plan = derive_batch_trade_plan(t, p, V2PriceSnapshot((quote("AAPL"), quote("MSFT"), quote("IBM"))), created_at=NOW)
    assert [x.action for x in plan.legs] == [BatchTradeAction.TRIM, BatchTradeAction.SELL, BatchTradeAction.EXIT]

def test_mixed_rebalance_sales_fund_add_and_execution_is_atomic():
    p = portfolio("0", pos("AAPL", "10"), pos("MSFT", "10"))
    t = target(p, [("AAPL", ".25", "REDUCE"), ("MSFT", ".75", "INCREASE")], "0")
    snapshot = V2PriceSnapshot((quote("AAPL"), quote("MSFT")))
    plan = derive_batch_trade_plan(t, p, snapshot, created_at=NOW)
    assert [x.action for x in plan.legs] == [BatchTradeAction.TRIM, BatchTradeAction.ADD]
    result = execute_approved_batch(BatchApproval(plan, "human", NOW), p, snapshot, executed_at=NOW)
    assert result.resulting_portfolio.cash_balance.amount == 0
    assert {x.security.ticker: x.quantity for x in result.resulting_portfolio.positions} == {"AAPL": Decimal("5.00000000"), "MSFT": Decimal("15.00000000")}

def test_insufficient_cash_rejected_without_silent_target_resize():
    p = portfolio("1")
    t = target(p, [("AAPL", "1", "INITIATE")], "0")
    # Eight-place half-even rounding requires 0.16666667 shares at $6, which
    # costs $1.00000002. Safety rejects it rather than resizing the target.
    with pytest.raises(ValueError, match="insufficient cash"):
        derive_batch_trade_plan(t, p, V2PriceSnapshot((quote("AAPL", 6),)), created_at=NOW)

def test_stale_state_and_approval_binding_reject_changes():
    p = portfolio("100")
    snapshot = V2PriceSnapshot((quote("AAPL"),))
    plan = derive_batch_trade_plan(target(p, [("AAPL", ".5", "INITIATE")], ".5"), p, snapshot, created_at=NOW)
    approval = BatchApproval(plan, "human", NOW)
    assert approval.binding == BatchApproval(plan, "human", NOW).binding
    with pytest.raises(ValueError, match="stale state"):
        execute_approved_batch(approval, portfolio("99"), snapshot, executed_at=NOW)
    with pytest.raises(ValueError, match="stale state"):
        execute_approved_batch(approval, p, V2PriceSnapshot((quote("AAPL", 11),)), executed_at=NOW)

def test_decimal_determinism_ignores_ambient_context():
    p = portfolio("100")
    t = target(p, [("AAPL", ".333333", "INITIATE")], ".666667")
    snapshot = V2PriceSnapshot((quote("AAPL", "3"),))
    with localcontext() as ctx:
        ctx.prec = 2
        low = derive_batch_trade_plan(t, p, snapshot, created_at=NOW)
    assert low.legs[0].quantity == Decimal("11.11110000")

def test_restart_persistence_preserves_immutable_audit_lineage(tmp_path):
    from agentic_portfolio_lab.infrastructure.v2_batch_store import SQLiteV2BatchAuditStore, V2BatchAuditTrail
    p = portfolio("100")
    snapshot = V2PriceSnapshot((quote("AAPL"),))
    plan = derive_batch_trade_plan(target(p, [("AAPL", ".5", "INITIATE")], ".5"), p, snapshot, created_at=NOW)
    approval = BatchApproval(plan, "human", NOW)
    execution = execute_approved_batch(approval, p, snapshot, executed_at=NOW)
    store = SQLiteV2BatchAuditStore(tmp_path / "state.sqlite")
    store.save(V2BatchAuditTrail(plan.target, plan))
    store.save(V2BatchAuditTrail(plan.target, plan, approval, execution))
    assert SQLiteV2BatchAuditStore(tmp_path / "state.sqlite").load(plan.plan_id) == V2BatchAuditTrail(plan.target, plan, approval, execution)
