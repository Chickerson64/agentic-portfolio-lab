# ADR-007: Research v2 screening contracts

**Date:** 2026-08-17
**Status:** Accepted

## Motivation

v0.1 research fetches a small hardcoded candidate list every cycle. The approved
Research v2 shape is a broader static universe, a cheap deterministic screen,
and five deep research slots, with reusable per-endpoint fundamental records.
Lane 0 records those contracts. Later lanes implement screening, fetching,
derived metrics, and batch assembly.

## Decision

- The screener allocates research capacity. It is not a portfolio manager.
- A versioned `CandidateUniverse` snapshot is EQUITY + USD and excludes SPY/ETF.
- One `ScreeningRun` selects at most five names: at most three RANKED, one
  COVERAGE, and one REPORTING_CYCLE. If fewer than five names are eligible,
  select only those; never pad with randomness.
- Rank and slot role stay on the screening audit record. They are not added to
  `PortfolioRecommendation` or `ValueManagerDecisionContext`.
- Durable fundamentals are normalized per-endpoint `ProviderFundamentalRecord`
  rows, append-only, with explicit reuse/freshness/reliability on packets.
- `ResearchPacket.fundamentals` and `ResearchBatch.screening_run_id` default to
  `None` so existing v0.1 artifacts still construct and decode.

Lane 0 lands these types, invariants, codec defaults, and SQLite append-only
hooks. Screening rank policy, Alpha Vantage BALANCE_SHEET/CASH_FLOW fetching,
and derived FCF/EV math land in later lanes. Lane 3 weekly assembly now screens
`VALUE_US_EQUITIES_V1`, refreshes only selected names, attaches
`PacketFundamentals`, and persists `ScreeningRun` plus FETCHED records plus
`ResearchBatch.screening_run_id` in one append-only transition. Rank, slot
role, and `screening_run_id` stay off the Value Manager LLM payload.

Operator OVERVIEW bootstrap and the weekly screen → refresh-selected → assemble
loop have landed. Rank and slot role are still not sent to the Value Manager.
The operator API may show selected slot roles for audit only. The
operator-approved 30-name `VALUE_US_EQUITIES_V1` snapshot is now the live
managed universe.

## Research v2 net-debt / EV cash and debt

Derived `net_debt` and `enterprise_value` use cash_for_net_debt, not packet
`cash_and_equivalents` (CCE-only). The locked cash waterfall is:

1. Preferred: Alpha Vantage `cashAndShortTermInvestments`, used as-is when present.
   Do not recompute it from cash-and-equivalents plus short-term investments.
2. Fallback: `cashAndCashEquivalentsAtCarryingValue + shortTermInvestments` when
   both addends are valid parsed amounts. Do not add one side alone.
3. Degraded fallback: `cashAndCashEquivalentsAtCarryingValue` alone.

Persist `cash_field` whenever cash is present so reopen can tell which definition
produced the amount. Stable tokens:

- `cashAndShortTermInvestments`
- `cashAndCashEquivalentsAtCarryingValue+shortTermInvestments`
- `cashAndCashEquivalentsAtCarryingValue`

Total debt stays Alpha Vantage `shortLongTermDebtTotal`. Do not reconstruct face
notes. Do not subtract leases. That field may include finance and operating lease
liabilities and may differ materially from issuer-reported long-term debt/notes.

Formulas (unchanged arithmetically):

- `net_debt = total_debt - cash_for_net_debt`
- `enterprise_value = market_cap + net_debt`

Negative net debt is valid and stays PRESENT. Do not clamp, reject, or convert it
to `NOT_AVAILABLE`.

Legacy BALANCE_SHEET records without `cash_field` are CCE-era cash. The mapper
still uses `period_0_cash` and does not invent short-term investments. Do not
rewrite immutable historical artifacts.

## OVERVIEW reuse: initial hydration vs weekly refresh

Research v2 refresh keeps OVERVIEW rows append-only: only `FETCHED_THIS_CYCLE`
records are persisted. `REUSED_CURRENT` and `STALE` OVERVIEW coverage reuse the
original record object (timestamps, facts, and `record_id` unchanged).

**INITIAL HYDRATION.** When an identity has no complete statement set (all four
of `INCOME_STATEMENT`, `BALANCE_SHEET`, `CASH_FLOW`, and `EARNINGS` for the
exact `SecurityIdentity`), a persisted Alpha Vantage OVERVIEW may be
`REUSED_CURRENT` if it matches that identity, has a parseable LatestQuarter
(`fiscal_period` or `facts["latest_quarter"]`), and is fresh enough versus
cycle `as_of`. Freshness is application policy of `RefreshFundamentalsService`:
`OVERVIEW_REUSE_MAX_AGE = 7 days` from `as_of` (not wall-clock now).
`fetched_at` and `as_of` must be timezone-aware, `fetched_at <= as_of`, and
`(as_of - fetched_at) <= OVERVIEW_REUSE_MAX_AGE`. After the four statements are
fetched, if the newest statement `fiscal_period` is newer than LatestQuarter,
OVERVIEW coverage becomes `STALE`; original timestamps and facts stay, and the
packet still assembles. Do not fetch OVERVIEW just to “fix” STALE during
hydration.

**NORMAL WEEKLY REFRESH.** When a complete statement set already exists, a live
OVERVIEW is always the reporting-period probe (`FETCHED_THIS_CYCLE`, new
`fetched_at`). Statement reuse is unchanged: reuse cached statements only when
all four `fiscal_period` values equal that LatestQuarter; otherwise fetch all
four.

## Consequences

- Old `ResearchPacket` and `PersistedRunState` documents remain reopenable.
- The v0.1 Alpha Vantage adapter type-checks without new endpoint fetches
  because `SourceResearchDocument` balance-sheet and cash-flow fields default
  to `None`.
- Operators can later audit why a name was researched without showing rank to
  the Value Manager.

## Alternatives Considered

- **Manager-visible rank or slot role:** rejected; screening must not bias the
  manager's recommendation contract.
- **Raw vendor JSON as source of truth:** rejected; persist normalized
  per-endpoint records.
- **Pad the five deep slots randomly when eligible names are scarce:** rejected;
  select only eligible current-cycle names.
