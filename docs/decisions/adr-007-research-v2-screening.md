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
The operator API may show selected slot roles for audit only.

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
