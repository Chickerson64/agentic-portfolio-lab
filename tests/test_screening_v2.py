from datetime import date, datetime, timedelta, timezone
from decimal import Context, Decimal, localcontext
from dataclasses import replace

from agentic_portfolio_lab.application.screen_universe_v2 import ScreenUniverseV2Service
from agentic_portfolio_lab.domain.market_data import DailyBar
from agentic_portfolio_lab.domain.portfolio import SecurityIdentity
from agentic_portfolio_lab.domain.screening_v2 import ScreeningExclusionReason, ScreeningProfile, ScreeningProfileIdentity, ScreeningProvenance, screen_universe_v2
from agentic_portfolio_lab.domain.universe_snapshots import EligibilityOutcome, UniverseEligibilityRules, UniverseSnapshot
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore


UTC_NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


def _snapshot(*securities):
    return UniverseSnapshot("snap-v2", "fixture", UTC_NOW, UTC_NOW, UniverseEligibilityRules(), tuple(EligibilityOutcome(x.ticker, True, "eligible", x) for x in securities), ())


def _bars(security, *, count=25, price="10", volume=100_000):
    return tuple(DailyBar(security, date(2026, 8, 1) + timedelta(days=i), Decimal("1"), Decimal("20"), Decimal("0.1"), Decimal(price), volume, "fixture-bars") for i in range(count))


def _profile(**kwargs):
    manager_id = kwargs.pop("manager_id", "value-manager")
    profile_name = kwargs.pop("profile_name", "daily-v2")
    profile_version = kwargs.pop("profile_version", "2026-09-1")
    return ScreeningProfile(
        ScreeningProfileIdentity(manager_id, profile_name, profile_version),
        Decimal("5"),
        Decimal("100"),
        liquidity_window=kwargs.pop("liquidity_window", 5),
        momentum_window=kwargs.pop("momentum_window", 5),
        relative_strength_window=kwargs.pop("relative_strength_window", 5),
        volatility_window=kwargs.pop("volatility_window", 5),
        **kwargs,
    )


def test_v2_ranking_is_stable_on_equal_scores_and_candidate_limit_carries_holdings():
    aaa = SecurityIdentity("AAA", "EQUITY", "NASDAQ", "USD")
    bbb = SecurityIdentity("BBB", "EQUITY", "NASDAQ", "USD")
    held = SecurityIdentity("HELD", "EQUITY", "NASDAQ", "USD")
    snapshot = _snapshot(aaa, bbb)
    provenance = ScreeningProvenance(UTC_NOW, ("fixture-bars",), snapshot.snapshot_id, UTC_NOW)
    run = screen_universe_v2(snapshot=snapshot, profile=_profile(candidate_limit=1), daily_bars={"AAA": _bars(aaa), "BBB": _bars(bbb)}, benchmark_bars=None, current_holdings=(held, held), provenance=provenance)
    assert [row.symbol for row in run.results if row.advanced] == ["AAA", "BBB"]
    assert run.new_candidates == (aaa,)
    assert run.downstream_review_slate == (aaa, held)
    assert run.results[0].ranking_basis == ("score_desc", "ticker_asc")


def test_v2_excludes_ranked_holdings_before_applying_candidate_limit():
    held = SecurityIdentity("HELD", "EQUITY", "NASDAQ", "USD")
    idea = SecurityIdentity("IDEA", "EQUITY", "NASDAQ", "USD")
    snapshot = _snapshot(held, idea)
    provenance = ScreeningProvenance(UTC_NOW, ("fixture-bars",), snapshot.snapshot_id, UTC_NOW)
    run = screen_universe_v2(snapshot=snapshot, profile=_profile(candidate_limit=1), daily_bars={"HELD": _bars(held, price="20"), "IDEA": _bars(idea)}, benchmark_bars=None, current_holdings=(held,), provenance=provenance)
    assert run.new_candidates == (idea,)
    assert run.downstream_review_slate == (idea, held)


def test_v2_ranking_is_independent_of_ambient_decimal_precision():
    aaa = SecurityIdentity("AAA", "EQUITY", "NASDAQ", "USD")
    bbb = SecurityIdentity("BBB", "EQUITY", "NASDAQ", "USD")
    bbb_history = _bars(bbb)
    bbb_history = bbb_history[:-1] + (replace(bbb_history[-1], close=Decimal("9.99")),)
    snapshot = _snapshot(aaa, bbb)
    provenance = ScreeningProvenance(UTC_NOW, ("fixture-bars",), snapshot.snapshot_id, UTC_NOW)
    kwargs = dict(snapshot=snapshot, profile=_profile(), daily_bars={"AAA": _bars(aaa), "BBB": bbb_history}, benchmark_bars=None, current_holdings=(), provenance=provenance)
    with localcontext(Context(prec=28)):
        normal = screen_universe_v2(**kwargs)
    with localcontext(Context(prec=1)):
        low_precision = screen_universe_v2(**kwargs)
    assert [row.symbol for row in normal.results if row.advanced] == [row.symbol for row in low_precision.results if row.advanced]
    assert [row.symbol for row in normal.results if row.rank] == [row.symbol for row in low_precision.results if row.rank]


def test_v2_preserves_universe_exclusion_reason_and_rejects_future_or_mismatched_bars():
    good = SecurityIdentity("GOOD", "EQUITY", "NASDAQ", "USD")
    other = SecurityIdentity("OTHER", "EQUITY", "NASDAQ", "USD")
    snapshot = UniverseSnapshot("snap-v2", "fixture", UTC_NOW, UTC_NOW, UniverseEligibilityRules(), (EligibilityOutcome("GOOD", True, "eligible", good), EligibilityOutcome("BAD", False, "exchange_not_allowed", None)), ())
    provenance = ScreeningProvenance(UTC_NOW, ("fixture-bars",), snapshot.snapshot_id, UTC_NOW)
    with_future = _bars(good) + (DailyBar(good, date(2026, 9, 13), Decimal("1"), Decimal("20"), Decimal("0.1"), Decimal("10"), 100_000, "fixture-bars"),)
    run = screen_universe_v2(snapshot=snapshot, profile=_profile(), daily_bars={"GOOD": with_future}, benchmark_bars=None, current_holdings=(), provenance=provenance)
    by_symbol = {row.symbol: row for row in run.results}
    assert by_symbol["BAD"].exclusion_reason is ScreeningExclusionReason.EXCHANGE_NOT_ALLOWED
    assert by_symbol["BAD"].universe_exclusion_reason == "exchange_not_allowed"
    assert by_symbol["GOOD"].exclusion_reason is ScreeningExclusionReason.INVALID_HISTORY
    mismatched = screen_universe_v2(snapshot=snapshot, profile=_profile(), daily_bars={"GOOD": _bars(other)}, benchmark_bars=None, current_holdings=(), provenance=provenance)
    assert by_symbol["GOOD"].exclusion_reason is ScreeningExclusionReason.INVALID_HISTORY
    assert mismatched.results[0].exclusion_reason is ScreeningExclusionReason.INVALID_HISTORY


def test_v2_profile_is_an_independently_selectable_immutable_record(tmp_path):
    store = SQLiteLocalRunStore(tmp_path / "state.db")
    profile = _profile()
    store.save_screening_profile(profile)
    assert store.load_screening_profile(profile.identity) == profile
    changed = ScreeningProfile(profile.identity, Decimal("6"), profile.minimum_average_dollar_volume)
    try:
        store.save_screening_profile(changed)
    except ValueError:
        pass
    else:
        raise AssertionError("persisted profiles must be immutable")


def test_v2_profile_identity_is_composite_not_colon_concatenated(tmp_path):
    store = SQLiteLocalRunStore(tmp_path / "state.db")
    first = _profile(manager_id="a", profile_name="b:c", profile_version="d")
    second = _profile(manager_id="a:b", profile_name="c", profile_version="d")
    store.save_screening_profile(first)
    store.save_screening_profile(second)
    assert store.load_screening_profile(first.identity) == first
    assert store.load_screening_profile(second.identity) == second


def test_v2_records_explicit_history_and_liquidity_exclusions_and_features():
    good = SecurityIdentity("GOOD", "EQUITY", "NASDAQ", "USD")
    short = SecurityIdentity("SHORT", "EQUITY", "NASDAQ", "USD")
    illiquid = SecurityIdentity("ILLIQ", "EQUITY", "NASDAQ", "USD")
    snapshot = _snapshot(good, short, illiquid)
    provenance = ScreeningProvenance(UTC_NOW, ("fixture-bars",), snapshot.snapshot_id, UTC_NOW)
    run = screen_universe_v2(snapshot=snapshot, profile=_profile(), daily_bars={"GOOD": _bars(good), "SHORT": _bars(short, count=2), "ILLIQ": _bars(illiquid, volume=1)}, benchmark_bars=None, current_holdings=(), provenance=provenance)
    by_symbol = {row.symbol: row for row in run.results}
    assert by_symbol["GOOD"].advanced and by_symbol["GOOD"].features is not None
    assert by_symbol["SHORT"].exclusion_reason is ScreeningExclusionReason.INSUFFICIENT_HISTORY
    assert by_symbol["ILLIQ"].exclusion_reason is ScreeningExclusionReason.LIQUIDITY_BELOW_MINIMUM


def test_v2_records_price_and_missing_history_exclusions_and_carries_ineligible_holding():
    cheap = SecurityIdentity("CHEAP", "EQUITY", "NASDAQ", "USD")
    missing = SecurityIdentity("MISSING", "EQUITY", "NASDAQ", "USD")
    snapshot = _snapshot(cheap, missing)
    provenance = ScreeningProvenance(UTC_NOW, ("fixture-bars",), snapshot.snapshot_id, UTC_NOW)
    run = screen_universe_v2(
        snapshot=snapshot,
        profile=_profile(),
        daily_bars={"CHEAP": _bars(cheap, price="4")},
        benchmark_bars=None,
        current_holdings=(cheap,),
        provenance=provenance,
    )
    by_symbol = {row.symbol: row for row in run.results}
    assert by_symbol["CHEAP"].exclusion_reason is ScreeningExclusionReason.PRICE_BELOW_MINIMUM
    assert by_symbol["MISSING"].exclusion_reason is ScreeningExclusionReason.MISSING_HISTORY
    assert run.new_candidates == ()
    assert run.downstream_review_slate == (cheap,)


def test_v2_uses_aligned_relative_strength_window_and_calculates_volatility():
    security = SecurityIdentity("AAA", "EQUITY", "NASDAQ", "USD")
    benchmark = SecurityIdentity("SPY", "ETF", "NYSE ARCA", "USD")
    profile = _profile(
        benchmark=benchmark,
        liquidity_window=2,
        momentum_window=2,
        relative_strength_window=2,
        volatility_window=2,
    )
    snapshot = _snapshot(security)
    provenance = ScreeningProvenance(UTC_NOW, ("fixture-bars",), snapshot.snapshot_id, UTC_NOW)
    security_bars = tuple(
        replace(bar, close=Decimal(str(close)))
        for bar, close in zip(_bars(security, count=4), ("10", "11", "12", "13"), strict=True)
    )
    benchmark_bars = tuple(
        replace(bar, close=Decimal("10")) for bar in _bars(benchmark, count=4)
    )
    run = screen_universe_v2(
        snapshot=snapshot,
        profile=profile,
        daily_bars={security.ticker: security_bars},
        benchmark_bars=benchmark_bars,
        current_holdings=(),
        provenance=provenance,
    )
    features = run.results[0].features
    assert features is not None
    assert Decimal("0.18") < features.momentum < Decimal("0.19")
    assert features.relative_strength == features.momentum
    assert features.volatility > Decimal("0")

    unaligned = benchmark_bars[::2]
    failed = screen_universe_v2(
        snapshot=snapshot,
        profile=profile,
        daily_bars={security.ticker: security_bars},
        benchmark_bars=unaligned,
        current_holdings=(),
        provenance=provenance,
    )
    assert failed.results[0].exclusion_reason is ScreeningExclusionReason.INSUFFICIENT_HISTORY


def test_v2_artifact_persists_independently_and_reloads(tmp_path):
    security = SecurityIdentity("AAA", "EQUITY", "NASDAQ", "USD")
    snapshot = _snapshot(security)
    provenance = ScreeningProvenance(UTC_NOW, ("fixture-bars",), snapshot.snapshot_id, UTC_NOW)
    run = screen_universe_v2(snapshot=snapshot, profile=_profile(), daily_bars={"AAA": _bars(security)}, benchmark_bars=None, current_holdings=(), provenance=provenance)
    store = SQLiteLocalRunStore(tmp_path / "state.db")
    store.save_universe_snapshot(snapshot)
    store.save_screening_artifact(run)
    assert store.load_screening_artifact(run.screening_run_id) == run


def test_v2_service_loads_only_persisted_profile_and_uses_market_data(tmp_path):
    security = SecurityIdentity("AAA", "EQUITY", "NASDAQ", "USD")
    benchmark = SecurityIdentity("SPY", "ETF", "NYSE ARCA", "USD")
    snapshot = _snapshot(security)
    profile = _profile(benchmark=benchmark)
    store = SQLiteLocalRunStore(tmp_path / "state.db")
    store.initialize_run(initialized_at=UTC_NOW)
    store.save_universe_snapshot(snapshot)
    store.save_screening_profile(profile)

    class FakeMarketData:
        def __init__(self):
            self.calls = []

        def get_daily_bars(self, requested, *, start, end):
            self.calls.append((requested, start, end))
            return _bars(requested)

    provider = FakeMarketData()
    run = ScreenUniverseV2Service(store, provider, clock=lambda: UTC_NOW).execute(
        snapshot_id=snapshot.snapshot_id,
        profile_identity=profile.identity,
        as_of=UTC_NOW,
    )
    assert [call[0] for call in provider.calls] == [security, benchmark]
    assert all(call[2] == UTC_NOW.date() for call in provider.calls)
    assert store.load_screening_artifact(run.screening_run_id) == run
    assert run.profile == profile
    missing = ScreeningProfileIdentity("value-manager", "missing", "1")
    try:
        ScreenUniverseV2Service(store, provider, clock=lambda: UTC_NOW).execute(
            snapshot_id=snapshot.snapshot_id,
            profile_identity=missing,
            as_of=UTC_NOW,
        )
    except ValueError as error:
        assert "profile not found" in str(error)
    else:
        raise AssertionError("service must not accept an unpersisted profile")
