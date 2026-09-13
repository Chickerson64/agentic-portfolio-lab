# ADR-011: V2 daily-bar screening coexistence boundary

**Date:** 2026-09-12
**Status:** Accepted

## Decision

V2 screening is a separate immutable artifact flow. It consumes a selected
persisted `UniverseSnapshot`, a versioned manager profile, provider-neutral
`DailyBar` windows, and current managed holdings. It writes `screening_artifacts`
in local SQLite and does not append to the v0.1 `PersistedRunState.screening_runs`
or change its fixed five-slot contracts.

The pure screen records every snapshot outcome, calculated feature values for
advanced securities, explicit exclusion stage/reason for others, provenance,
and a stable `(score descending, ticker ascending)` tie-breaker. New candidates
are bounded by the profile; current holdings are appended to the review slate
once even when they are not eligible new ideas.

Profiles reserve provenance and future valuation/quality/growth configuration,
but this slice uses only price, dollar-volume liquidity, momentum,
benchmark-relative strength, and volatility. It makes no LLM or fundamental
provider request and introduces no portfolio, execution, recommendation,
brokerage, or backtest behavior.

## Operator usage

Construct `ScreenUniverseV2Service` with the existing SQLite store and a
`MarketDataProvider`, persist the desired profile with `save_screening_profile`,
then construct a `ScreeningProfileIdentity(manager_id, profile_name,
profile_version)` and call `execute(snapshot_id=..., profile_identity=...,
as_of=...)`. The service accepts no profile object: it loads that immutable
profile by its persisted composite identity,
reads current holdings from the managed portfolio state, and requests one
bounded daily-bar window per snapshot security and, when configured, one
benchmark window. The result can be reloaded with
`store.load_screening_artifact(run_id)`. Profiles can be selected independently
with `load_screening_profile(profile_identity)`; profile records are immutable.
The SQLite table stores the three identity components separately rather than a
delimiter-concatenated key. The artifact includes
the exact daily-bar inputs, a score-formula version, source identities, and
as-of checks so the calculation evidence is reproducible and auditable.
