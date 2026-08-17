from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.recommendations import PortfolioRecommendation
from agentic_portfolio_lab.domain.screening import ResearchSlotRole, ScreeningCandidateResult, ScreeningRun
from agentic_portfolio_lab.domain.universe import CandidateUniverse
from agentic_portfolio_lab.domain.value_manager import ValueManagerDecisionContext


UTC = timezone.utc
AS_OF = datetime(2026, 8, 17, 15, tzinfo=UTC)


def _equity(ticker: str, *, exchange: str = "NASDAQ") -> SecurityIdentity:
    return SecurityIdentity(ticker, "EQUITY", exchange, "USD")


def _result(
    security: SecurityIdentity,
    *,
    eligible: bool = True,
    ineligibility_reason: str | None = None,
    rank_key: tuple[str, ...] = ("1",),
    rank_reason: str = "eligible on current-cycle price",
    slot_role: ResearchSlotRole | None = None,
) -> ScreeningCandidateResult:
    if not eligible and ineligibility_reason is None:
        ineligibility_reason = "ineligible: missing current-cycle price"
        rank_key = ()
        rank_reason = ineligibility_reason
    return ScreeningCandidateResult(
        security=security,
        eligible=eligible,
        ineligibility_reason=ineligibility_reason,
        rank_key=rank_key,
        rank_reason=rank_reason,
        slot_role=slot_role,
    )


def test_candidate_universe_accepts_unique_equity_usd_identities() -> None:
    aapl = _equity("AAPL")
    msft = _equity("MSFT")

    universe = CandidateUniverse(" value-us-equities-v1 ", (aapl, msft))

    assert universe.universe_version == "value-us-equities-v1"
    assert universe.identities == (aapl, msft)


@pytest.mark.parametrize(
    "identity",
    (
        SecurityIdentity("SPY", "ETF", "NYSE ARCA", "USD"),
        SecurityIdentity("SPY", "EQUITY", "NYSE ARCA", "USD"),
        SecurityIdentity("QQQ", "ETF", "NASDAQ", "USD"),
    ),
)
def test_candidate_universe_rejects_spy_and_etf(identity: SecurityIdentity) -> None:
    with pytest.raises(ValueError, match="SPY or ETF"):
        CandidateUniverse("value-us-equities-v1", (_equity("AAPL"), identity))


def test_candidate_universe_rejects_non_usd_and_duplicate_identities() -> None:
    with pytest.raises(ValueError, match="USD"):
        CandidateUniverse("value-us-equities-v1", (SecurityIdentity("AAPL", "EQUITY", "NASDAQ", "CAD"),))
    with pytest.raises(ValueError, match="duplicate or ambiguous"):
        CandidateUniverse("value-us-equities-v1", (_equity("AAPL"), _equity(" aapl ")))
    with pytest.raises(ValueError, match="duplicate or ambiguous"):
        CandidateUniverse("value-us-equities-v1", (_equity("AAPL", exchange="NASDAQ"), _equity("AAPL", exchange="NYSE")))


def test_screening_run_allows_up_to_five_selected_with_slot_caps() -> None:
    names = tuple(_equity(ticker) for ticker in ("AAPL", "MSFT", "JPM", "XOM", "UNH", "T"))
    results = (
        _result(names[0], rank_key=("a",), slot_role=ResearchSlotRole.RANKED),
        _result(names[1], rank_key=("b",), slot_role=ResearchSlotRole.RANKED),
        _result(names[2], rank_key=("c",), slot_role=ResearchSlotRole.RANKED),
        _result(names[3], rank_key=("d",), slot_role=ResearchSlotRole.COVERAGE),
        _result(names[4], rank_key=("e",), slot_role=ResearchSlotRole.REPORTING_CYCLE),
        _result(names[5], eligible=False),
    )

    run = ScreeningRun(
        screening_run_id=uuid4(),
        universe_version="value-us-equities-v1",
        universe_identities=names,
        as_of=AS_OF,
        results=results,
        selected=names[:5],
    )

    assert len(run.selected) == 5
    assert run.results[5].slot_role is None


def test_screening_run_allows_fewer_than_five_selected_without_padding() -> None:
    names = (_equity("AAPL"), _equity("MSFT"))
    run = ScreeningRun(
        screening_run_id=uuid4(),
        universe_version="value-us-equities-v1",
        universe_identities=names,
        as_of=AS_OF,
        results=(
            _result(names[0], slot_role=ResearchSlotRole.RANKED),
            _result(names[1], eligible=False),
        ),
        selected=(names[0],),
    )

    assert run.selected == (names[0],)


def test_screening_run_rejects_more_than_five_selected() -> None:
    names = tuple(_equity(ticker) for ticker in ("AAPL", "MSFT", "JPM", "XOM", "UNH", "T"))
    ranked = tuple(_result(name, slot_role=ResearchSlotRole.RANKED) for name in names)
    with pytest.raises(ValueError, match="at most 5"):
        ScreeningRun(
            screening_run_id=uuid4(),
            universe_version="value-us-equities-v1",
            universe_identities=names,
            as_of=AS_OF,
            results=ranked,
            selected=names,
        )


def test_screening_run_rejects_slot_role_caps_and_unselected_roles() -> None:
    names = tuple(_equity(ticker) for ticker in ("AAPL", "MSFT", "JPM", "XOM"))
    four_ranked = tuple(_result(name, slot_role=ResearchSlotRole.RANKED) for name in names)
    with pytest.raises(ValueError, match="at most 3 RANKED"):
        ScreeningRun(
            screening_run_id=uuid4(),
            universe_version="value-us-equities-v1",
            universe_identities=names,
            as_of=AS_OF,
            results=four_ranked,
            selected=names,
        )

    two_coverage = (
        _result(names[0], slot_role=ResearchSlotRole.COVERAGE),
        _result(names[1], slot_role=ResearchSlotRole.COVERAGE),
        _result(names[2], eligible=False),
        _result(names[3], eligible=False),
    )
    with pytest.raises(ValueError, match="at most 1 COVERAGE"):
        ScreeningRun(
            screening_run_id=uuid4(),
            universe_version="value-us-equities-v1",
            universe_identities=names,
            as_of=AS_OF,
            results=two_coverage,
            selected=names[:2],
        )

    leaked_role = (
        _result(names[0], slot_role=ResearchSlotRole.RANKED),
        _result(names[1], slot_role=ResearchSlotRole.COVERAGE),
        _result(names[2], eligible=False),
        _result(names[3], eligible=False),
    )
    with pytest.raises(ValueError, match="unselected results"):
        ScreeningRun(
            screening_run_id=uuid4(),
            universe_version="value-us-equities-v1",
            universe_identities=names,
            as_of=AS_OF,
            results=leaked_role,
            selected=(names[0],),
        )


def test_screening_run_rejects_ineligible_or_uncovered_selected_identities() -> None:
    names = (_equity("AAPL"), _equity("MSFT"))
    with pytest.raises(ValueError, match="eligible"):
        ScreeningRun(
            screening_run_id=uuid4(),
            universe_version="value-us-equities-v1",
            universe_identities=names,
            as_of=AS_OF,
            results=(_result(names[0], eligible=False), _result(names[1], slot_role=ResearchSlotRole.RANKED)),
            selected=(names[0],),
        )
    with pytest.raises(ValueError, match="exactly the universe"):
        ScreeningRun(
            screening_run_id=uuid4(),
            universe_version="value-us-equities-v1",
            universe_identities=names,
            as_of=AS_OF,
            results=(_result(names[0], slot_role=ResearchSlotRole.RANKED),),
            selected=(names[0],),
        )


def test_screening_candidate_result_requires_ineligibility_reason() -> None:
    security = _equity("AAPL")
    with pytest.raises(ValueError, match="ineligibility_reason"):
        ScreeningCandidateResult(
            security=security,
            eligible=False,
            ineligibility_reason=None,
            rank_key=(),
            rank_reason="ineligible",
        )
    with pytest.raises(ValueError, match="ineligibility_reason must be None"):
        ScreeningCandidateResult(
            security=security,
            eligible=True,
            ineligibility_reason="should not be set",
            rank_key=("1",),
            rank_reason="eligible",
        )


def test_manager_contracts_do_not_carry_screening_rank_or_slot_role() -> None:
    assert "rank" not in PortfolioRecommendation.__dataclass_fields__
    assert "slot_role" not in PortfolioRecommendation.__dataclass_fields__
    assert "rank" not in ValueManagerDecisionContext.__dataclass_fields__
    assert "slot_role" not in ValueManagerDecisionContext.__dataclass_fields__
    assert "screening_run_id" not in ValueManagerDecisionContext.__dataclass_fields__
