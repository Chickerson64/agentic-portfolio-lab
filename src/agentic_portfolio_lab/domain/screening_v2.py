"""Provider-neutral, deterministic V2 candidate screening contracts.

This module is deliberately independent from the fixed-five-slot ``screening``
contracts used by v0.1 research.  It is a capacity-screening evidence record,
not a recommendation or portfolio-construction model.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Context, Decimal, MAX_EMAX, MIN_EMIN, ROUND_HALF_EVEN, localcontext
from enum import StrEnum
from functools import cmp_to_key
from typing import Mapping, Sequence
from uuid import UUID, uuid4

from .market_data import DailyBar
from .portfolio import SecurityIdentity, _require_non_empty_text, _require_positive_decimal
from .universe_snapshots import UniverseSnapshot


class ScreeningExclusionReason(StrEnum):
    PRICE_BELOW_MINIMUM = "PRICE_BELOW_MINIMUM"
    LIQUIDITY_BELOW_MINIMUM = "LIQUIDITY_BELOW_MINIMUM"
    MISSING_HISTORY = "MISSING_HISTORY"
    INVALID_HISTORY = "INVALID_HISTORY"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    NO_ELIGIBLE_CLOSE = "NO_ELIGIBLE_CLOSE"
    EXCHANGE_NOT_ALLOWED = "EXCHANGE_NOT_ALLOWED"
    NOT_TRADABLE = "NOT_TRADABLE"
    NOT_FRACTIONABLE = "NOT_FRACTIONABLE"
    SYMBOL_RULE_VIOLATION = "SYMBOL_RULE_VIOLATION"
    UNIVERSE_EXCLUDED = "UNIVERSE_EXCLUDED"


SCORE_FORMULA_VERSION = "screening-v2-score-1"
# Screening values are derived metrics, not source facts.  A bounded, owned
# context keeps recurring divisions/square roots finite and makes both feature
# calculation and ranking independent of the caller's Decimal context.
_SCREENING_DECIMAL_CONTEXT = Context(
    prec=50,
    rounding=ROUND_HALF_EVEN,
    Emax=MAX_EMAX,
    Emin=MIN_EMIN,
)


@dataclass(frozen=True, slots=True)
class ScreeningProfileIdentity:
    """Stable, composite identity for an immutable screening profile."""

    manager_id: str
    profile_name: str
    profile_version: str

    def __post_init__(self) -> None:
        for field_name in ("manager_id", "profile_name", "profile_version"):
            value = _require_non_empty_text(getattr(self, field_name), field_name=field_name).strip()
            object.__setattr__(self, field_name, value)


@dataclass(frozen=True, slots=True)
class ScreeningProvenance:
    as_of: datetime
    source_provider_identities: tuple[str, ...]
    universe_snapshot_id: str
    generated_at: datetime

    def __post_init__(self) -> None:
        for field in ("as_of", "generated_at"):
            value = getattr(self, field)
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
                raise ValueError(f"{field} must be UTC")
        if self.generated_at < self.as_of:
            raise ValueError("generated_at must not precede as_of")
        if not self.source_provider_identities or not all(isinstance(x, str) and x.strip() for x in self.source_provider_identities):
            raise ValueError("source_provider_identities must be non-empty")
        object.__setattr__(self, "source_provider_identities", tuple(sorted(set(x.strip() for x in self.source_provider_identities))))
        object.__setattr__(self, "universe_snapshot_id", _require_non_empty_text(self.universe_snapshot_id, field_name="universe_snapshot_id").strip())


@dataclass(frozen=True, slots=True)
class ScreeningProfile:
    identity: ScreeningProfileIdentity
    minimum_price: Decimal
    minimum_average_dollar_volume: Decimal
    liquidity_window: int = 20
    momentum_window: int = 20
    relative_strength_window: int = 20
    volatility_window: int = 20
    candidate_limit: int = 5
    benchmark: SecurityIdentity | None = None
    provenance: tuple[tuple[str, str], ...] = ()
    reserved_feature_groups: tuple[str, ...] = ("valuation", "quality", "growth")

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ScreeningProfileIdentity):
            raise TypeError("identity must be a ScreeningProfileIdentity")
        object.__setattr__(self, "minimum_price", _require_positive_decimal(self.minimum_price, field_name="minimum_price"))
        object.__setattr__(self, "minimum_average_dollar_volume", _require_positive_decimal(self.minimum_average_dollar_volume, field_name="minimum_average_dollar_volume"))
        for name in ("liquidity_window", "momentum_window", "relative_strength_window", "volatility_window", "candidate_limit"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.benchmark is not None and not isinstance(self.benchmark, SecurityIdentity):
            raise TypeError("benchmark must be a SecurityIdentity or None")
        if not isinstance(self.provenance, tuple) or not all(isinstance(x, tuple) and len(x) == 2 and all(isinstance(y, str) and y.strip() for y in x) for x in self.provenance):
            raise TypeError("provenance must contain string pairs")
        if not isinstance(self.reserved_feature_groups, tuple) or not all(isinstance(x, str) and x.strip() for x in self.reserved_feature_groups):
            raise TypeError("reserved_feature_groups must contain strings")

    @property
    def manager_id(self) -> str:
        return self.identity.manager_id

    @property
    def profile_name(self) -> str:
        return self.identity.profile_name

    @property
    def profile_version(self) -> str:
        return self.identity.profile_version

    @property
    def required_history_days(self) -> int:
        return max(self.liquidity_window, self.momentum_window + 1, self.relative_strength_window + 1, self.volatility_window + 1)

    def to_json(self) -> str:
        return json.dumps(_encode(self), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> "ScreeningProfile":
        raw = json.loads(value)
        identity = raw.get("identity") or {
            "manager_id": raw["manager_id"],
            "profile_name": raw["profile_name"],
            "profile_version": raw["profile_version"],
        }
        return cls(ScreeningProfileIdentity(**identity), Decimal(raw["minimum_price"]["$decimal"]), Decimal(raw["minimum_average_dollar_volume"]["$decimal"]), raw["liquidity_window"], raw["momentum_window"], raw["relative_strength_window"], raw["volatility_window"], raw["candidate_limit"], None if raw.get("benchmark") is None else SecurityIdentity(**raw["benchmark"]), tuple(tuple(x) for x in raw.get("provenance", ())), tuple(raw.get("reserved_feature_groups", ("valuation", "quality", "growth"))))


@dataclass(frozen=True, slots=True)
class ScreeningFeatures:
    latest_price: Decimal
    average_dollar_volume: Decimal
    momentum: Decimal
    relative_strength: Decimal | None
    volatility: Decimal


@dataclass(frozen=True, slots=True)
class ScreeningSecurityResult:
    symbol: str
    security: SecurityIdentity | None
    advanced: bool
    stage: str
    exclusion_reason: ScreeningExclusionReason | None
    features: ScreeningFeatures | None
    score: Decimal | None
    ranking_basis: tuple[str, ...]
    rank: int | None
    universe_exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _require_non_empty_text(self.symbol, field_name="symbol").strip().upper())
        if self.security is not None and self.security.ticker != self.symbol:
            raise ValueError("security ticker must equal symbol")
        object.__setattr__(self, "stage", _require_non_empty_text(self.stage, field_name="stage").strip())
        if not isinstance(self.ranking_basis, tuple) or not all(isinstance(x, str) and x for x in self.ranking_basis):
            raise TypeError("ranking_basis must be a tuple of strings")
        if self.advanced != (self.features is not None and self.exclusion_reason is None):
            raise ValueError("advanced must match features and exclusion_reason")
        if self.advanced and self.score is None:
            raise ValueError("advanced result requires score")
        if not self.advanced and self.exclusion_reason is None:
            raise ValueError("excluded result requires exclusion_reason")
        if self.universe_exclusion_reason is not None:
            if self.security is not None or self.stage != "UNIVERSE":
                raise ValueError("universe_exclusion_reason is only valid for universe exclusions")
            object.__setattr__(self, "universe_exclusion_reason", _require_non_empty_text(self.universe_exclusion_reason, field_name="universe_exclusion_reason").strip())


@dataclass(frozen=True, slots=True)
class ScreeningRunV2:
    screening_run_id: UUID
    profile: ScreeningProfile
    provenance: ScreeningProvenance
    universe_snapshot_id: str
    results: tuple[ScreeningSecurityResult, ...]
    new_candidates: tuple[SecurityIdentity, ...]
    current_holdings: tuple[SecurityIdentity, ...]
    downstream_review_slate: tuple[SecurityIdentity, ...]
    score_formula_version: str = SCORE_FORMULA_VERSION
    daily_bar_inputs: tuple[DailyBar, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.screening_run_id, UUID) or not isinstance(self.profile, ScreeningProfile) or not isinstance(self.provenance, ScreeningProvenance):
            raise TypeError("invalid V2 screening run identity, profile, or provenance")
        if self.provenance.universe_snapshot_id != self.universe_snapshot_id:
            raise ValueError("provenance snapshot must match run snapshot")
        if len({x.symbol for x in self.results}) != len(self.results):
            raise ValueError("results must contain one row per symbol")
        if len(self.new_candidates) > self.profile.candidate_limit:
            raise ValueError("new_candidates exceeds profile candidate_limit")
        if len(set(self.downstream_review_slate)) != len(self.downstream_review_slate):
            raise ValueError("downstream_review_slate must be deduplicated")
        if not set(self.current_holdings).issubset(self.downstream_review_slate):
            raise ValueError("all current holdings must carry forward")
        if self.score_formula_version != SCORE_FORMULA_VERSION:
            raise ValueError("unsupported screening score formula version")
        if not all(isinstance(bar, DailyBar) for bar in self.daily_bar_inputs):
            raise TypeError("daily_bar_inputs must contain DailyBar instances")

    def to_json(self) -> str:
        return json.dumps(_encode(self), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> "ScreeningRunV2":
        try:
            return _decode(json.loads(value))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("screening V2 artifact is malformed") from error


def _ordered_bars(bars: Sequence[DailyBar], *, expected_security: SecurityIdentity | None = None, as_of: date | None = None) -> tuple[DailyBar, ...]:
    if not all(isinstance(x, DailyBar) for x in bars):
        raise TypeError("daily bars must contain DailyBar instances")
    ordered = tuple(sorted(bars, key=lambda x: x.market_date))
    if len({x.market_date for x in ordered}) != len(ordered):
        raise ValueError("duplicate daily bar dates")
    if expected_security is not None and any(x.security != expected_security for x in ordered):
        raise ValueError("daily bar security does not match requested security")
    if as_of is not None and any(x.market_date > as_of for x in ordered):
        raise ValueError("daily bar is newer than screening as_of")
    return ordered


def _return(bars: tuple[DailyBar, ...], window: int) -> Decimal:
    return bars[-1].close / bars[-1 - window].close - Decimal("1")


def _features(bars: tuple[DailyBar, ...], benchmark_bars: tuple[DailyBar, ...] | None, profile: ScreeningProfile) -> ScreeningFeatures:
    latest = bars[-1].close
    liquid = bars[-profile.liquidity_window:]
    avg_dollar_volume = sum((x.close * x.volume for x in liquid), Decimal("0")) / Decimal(len(liquid))
    momentum = _return(bars, profile.momentum_window)
    relative_bars = bars
    relative_benchmark = benchmark_bars
    if benchmark_bars is not None:
        benchmark_dates = {bar.market_date for bar in benchmark_bars}
        common_dates = tuple(bar.market_date for bar in bars if bar.market_date in benchmark_dates)
        if len(common_dates) < profile.relative_strength_window + 1:
            raise ValueError("insufficient date-aligned benchmark history")
        common = set(common_dates)
        relative_bars = tuple(bar for bar in bars if bar.market_date in common)
        relative_benchmark = tuple(bar for bar in benchmark_bars if bar.market_date in common)
    security_relative_return = _return(relative_bars, profile.relative_strength_window)
    benchmark_return = _return(relative_benchmark, profile.relative_strength_window) if relative_benchmark is not None else None
    relative = None if benchmark_return is None else security_relative_return - benchmark_return
    returns = tuple(_return(bars[i - 1:i + 1], 1) for i in range(len(bars) - profile.volatility_window, len(bars)))
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum(((item - mean) ** 2 for item in returns), Decimal("0")) / Decimal(len(returns))
    return ScreeningFeatures(latest, avg_dollar_volume, momentum, relative, variance.sqrt())


def screen_universe_v2(*, snapshot: UniverseSnapshot, profile: ScreeningProfile, daily_bars: Mapping[str, Sequence[DailyBar]], benchmark_bars: Sequence[DailyBar] | None, current_holdings: Sequence[SecurityIdentity], provenance: ScreeningProvenance) -> ScreeningRunV2:
    """Pure screen. It performs no I/O, LLM work, or fundamental-provider calls."""
    if provenance.universe_snapshot_id != snapshot.snapshot_id:
        raise ValueError("provenance must name the selected universe snapshot")
    if snapshot.as_of > provenance.as_of:
        raise ValueError("universe snapshot is newer than screening as_of")
    benchmark = None
    benchmark_error: ScreeningExclusionReason | None = None
    if profile.benchmark is not None:
        if benchmark_bars is None:
            benchmark_error = ScreeningExclusionReason.MISSING_HISTORY
        else:
            try:
                benchmark = _ordered_bars(benchmark_bars, expected_security=profile.benchmark, as_of=provenance.as_of.date())
                if len(benchmark) < profile.relative_strength_window + 1:
                    benchmark_error = ScreeningExclusionReason.INSUFFICIENT_HISTORY
            except (TypeError, ValueError):
                benchmark_error = ScreeningExclusionReason.INVALID_HISTORY
    holdings = tuple(dict.fromkeys(current_holdings))
    rows: list[ScreeningSecurityResult] = []
    for outcome in snapshot.outcomes:
        security = outcome.identity
        if security is None:
            rows.append(ScreeningSecurityResult(outcome.symbol, None, False, "UNIVERSE", _universe_exclusion_reason(outcome.reason), None, None, ("excluded_by_universe_snapshot",), None, outcome.reason))
            continue
        raw = daily_bars.get(security.ticker)
        if raw is None:
            rows.append(ScreeningSecurityResult(security.ticker, security, False, "HISTORY", ScreeningExclusionReason.MISSING_HISTORY, None, None, ("daily_bars",), None)); continue
        try:
            bars = _ordered_bars(raw, expected_security=security, as_of=provenance.as_of.date())
        except (TypeError, ValueError):
            rows.append(ScreeningSecurityResult(security.ticker, security, False, "HISTORY", ScreeningExclusionReason.INVALID_HISTORY, None, None, ("daily_bars",), None)); continue
        if len(bars) < profile.required_history_days:
            rows.append(ScreeningSecurityResult(security.ticker, security, False, "HISTORY", ScreeningExclusionReason.INSUFFICIENT_HISTORY, None, None, (f"required_history_days={profile.required_history_days}",), None)); continue
        if benchmark_error is not None:
            rows.append(ScreeningSecurityResult(security.ticker, security, False, "BENCHMARK_HISTORY", benchmark_error, None, None, ("benchmark_relative_strength",), None)); continue
        try:
            with localcontext(_SCREENING_DECIMAL_CONTEXT):
                feature = _features(bars, benchmark, profile)
        except (ValueError, IndexError):
            rows.append(ScreeningSecurityResult(security.ticker, security, False, "BENCHMARK_HISTORY", ScreeningExclusionReason.INSUFFICIENT_HISTORY, None, None, ("benchmark_relative_strength",), None)); continue
        if feature.latest_price < profile.minimum_price:
            reason = ScreeningExclusionReason.PRICE_BELOW_MINIMUM
        elif feature.average_dollar_volume < profile.minimum_average_dollar_volume:
            reason = ScreeningExclusionReason.LIQUIDITY_BELOW_MINIMUM
        elif profile.benchmark is not None and feature.relative_strength is None:
            reason = ScreeningExclusionReason.INSUFFICIENT_HISTORY
        else:
            reason = None
        score = None if reason else _score(feature)
        rows.append(ScreeningSecurityResult(security.ticker, security, reason is None, "RANKED" if reason is None else "ELIGIBILITY", reason, feature if reason is None else feature, score, ("score_desc", "ticker_asc"), None))
    ranked = _ranked_results(tuple(x for x in rows if x.advanced))
    ranked_rows = {x.symbol: i + 1 for i, x in enumerate(ranked)}
    rows = [ScreeningSecurityResult(x.symbol, x.security, x.advanced, x.stage, x.exclusion_reason, x.features, x.score, x.ranking_basis, ranked_rows.get(x.symbol), x.universe_exclusion_reason) for x in rows]
    new = tuple(x.security for x in sorted((x for x in rows if x.advanced and x.security not in holdings), key=lambda x: (x.rank or 0, x.symbol))[:profile.candidate_limit] if x.security is not None)
    slate = tuple(dict.fromkeys((*new, *holdings)))
    evidence = tuple(bar for history in daily_bars.values() for bar in history) + (() if benchmark_bars is None else tuple(benchmark_bars))
    return ScreeningRunV2(uuid4(), profile, provenance, snapshot.snapshot_id, tuple(rows), new, holdings, slate, SCORE_FORMULA_VERSION, evidence)


def _score(features: ScreeningFeatures) -> Decimal:
    with localcontext(_SCREENING_DECIMAL_CONTEXT):
        return features.momentum + (features.relative_strength or Decimal("0")) - features.volatility


def _universe_exclusion_reason(reason: str) -> ScreeningExclusionReason:
    normalized = reason.strip().lower().replace("-", "_").replace(" ", "_")
    known = {
        "exchange_not_allowed": ScreeningExclusionReason.EXCHANGE_NOT_ALLOWED,
        "not_tradable": ScreeningExclusionReason.NOT_TRADABLE,
        "not_fractionable": ScreeningExclusionReason.NOT_FRACTIONABLE,
        "symbol_rule": ScreeningExclusionReason.SYMBOL_RULE_VIOLATION,
        "symbol_rule_violation": ScreeningExclusionReason.SYMBOL_RULE_VIOLATION,
    }
    return known.get(normalized, ScreeningExclusionReason.UNIVERSE_EXCLUDED)


def _ranked_results(results: Sequence[ScreeningSecurityResult]) -> list[ScreeningSecurityResult]:
    def compare(left: ScreeningSecurityResult, right: ScreeningSecurityResult) -> int:
        # Decimal comparison itself is exact and does not use the caller's
        # context. Avoid unary negation here: Decimal negation rounds under
        # the ambient context before the sort key is evaluated.
        with localcontext(_SCREENING_DECIMAL_CONTEXT):
            left_score, right_score = left.score or Decimal("0"), right.score or Decimal("0")
            if left_score != right_score:
                return -1 if left_score > right_score else 1
        return (left.symbol > right.symbol) - (left.symbol < right.symbol)

    return sorted(results, key=cmp_to_key(compare))


def _encode(run: ScreeningRunV2) -> dict:
    from dataclasses import asdict
    def conv(x):
        if isinstance(x, Decimal): return {"$decimal": str(x)}
        if isinstance(x, (datetime, date)): return {"$date": x.isoformat()}
        if isinstance(x, UUID): return {"$uuid": str(x)}
        if isinstance(x, SecurityIdentity): return {"ticker": x.ticker, "security_type": x.security_type, "exchange": x.exchange, "currency": x.currency}
        if isinstance(x, StrEnum): return x.value
        if isinstance(x, tuple): return [conv(y) for y in x]
        if isinstance(x, dict): return {k: conv(v) for k, v in x.items()}
        if hasattr(x, "__dataclass_fields__"): return {k: conv(v) for k, v in asdict(x).items()}
        return x
    return conv(run)


def _decode(value: dict) -> ScreeningRunV2:
    def dec_sec(x): return None if x is None else SecurityIdentity(**x)
    p = value["profile"]
    profile_identity = p.get("identity") or {"manager_id": p["manager_id"], "profile_name": p["profile_name"], "profile_version": p["profile_version"]}
    profile = ScreeningProfile(ScreeningProfileIdentity(**profile_identity), Decimal(p["minimum_price"]["$decimal"]), Decimal(p["minimum_average_dollar_volume"]["$decimal"]), p["liquidity_window"], p["momentum_window"], p["relative_strength_window"], p["volatility_window"], p["candidate_limit"], dec_sec(p.get("benchmark")), tuple(tuple(x) for x in p["provenance"]), tuple(p.get("reserved_feature_groups", ("valuation", "quality", "growth"))))
    prov = value["provenance"]
    provenance = ScreeningProvenance(datetime.fromisoformat(prov["as_of"]["$date"]), tuple(prov["source_provider_identities"]), prov["universe_snapshot_id"], datetime.fromisoformat(prov["generated_at"]["$date"]))
    def feat(x):
        if x is None: return None
        return ScreeningFeatures(Decimal(x["latest_price"]["$decimal"]), Decimal(x["average_dollar_volume"]["$decimal"]), Decimal(x["momentum"]["$decimal"]), None if x["relative_strength"] is None else Decimal(x["relative_strength"]["$decimal"]), Decimal(x["volatility"]["$decimal"]))
    results = []
    for x in value["results"]:
        results.append(ScreeningSecurityResult(x["symbol"], dec_sec(x["security"]), x["advanced"], x["stage"], None if x["exclusion_reason"] is None else ScreeningExclusionReason(x["exclusion_reason"]), feat(x["features"]), None if x["score"] is None else Decimal(x["score"]["$decimal"]), tuple(x["ranking_basis"]), x["rank"], x.get("universe_exclusion_reason")))
    def bar(x):
        return DailyBar(dec_sec(x["security"]), date.fromisoformat(x["market_date"]["$date"]), Decimal(x["open"]["$decimal"]), Decimal(x["high"]["$decimal"]), Decimal(x["low"]["$decimal"]), Decimal(x["close"]["$decimal"]), x["volume"], x["source_provider_identity"])
    return ScreeningRunV2(UUID(value["screening_run_id"]["$uuid"]), profile, provenance, value["universe_snapshot_id"], tuple(results), tuple(dec_sec(x) for x in value["new_candidates"]), tuple(dec_sec(x) for x in value["current_holdings"]), tuple(dec_sec(x) for x in value["downstream_review_slate"]), value.get("score_formula_version", SCORE_FORMULA_VERSION), tuple(bar(x) for x in value.get("daily_bar_inputs", ())))
