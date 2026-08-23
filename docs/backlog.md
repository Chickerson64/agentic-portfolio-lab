# Backlog

## Completed foundation

- [x] Define the Portfolio Manager, Research Packet, portfolio-domain, and Value Manager constitution contracts.
- [x] Implement immutable portfolio, trade, research, valuation, benchmark, recommendation, constitution, and approval domain models.
- [x] Implement pre-approval Value Manager decision orchestration: workflow, deterministic validation, reviewer, journal, and human approval state.
- [x] Record the Cash Event, Portfolio Constitution, and Decision vs Execution architecture decisions.

## First end-to-end MVP

The first usable MVP is a local paper-trading demonstration. v0.1 screens the
approved 30-name `value-us-equities-v1` snapshot as the live managed universe
and assembles a five-slot ResearchBatch through Alpha Vantage. Remaining related
research work is additional evidence sources, not expanding this universe
snapshot.

1. `#16` Cash Event funding workflow: apply the same explicit Cash Event to the
   Value portfolio and the Passive Index portfolio, creating buying power
   without automatically trading.
2. `#15` Passive Index Constitution / paper SPY fulfillment: deploy available
   benchmark cash into SPY using an eligible persisted, provider-attributed
   SPY PriceObservation. Fulfillment respects funding, observation, and
   fulfillment chronology. The current Twelve Data quote convention remains
   `twelve-data-quote-close-field`; it is not an official regular-session close.
3. `#22` Post-approval simulated execution: execute an approved managed BUY as
   a server-authoritative paper fill from an eligible persisted
   PriceObservation. Deterministic validation, human approval, and executable
   readiness are required. The frontend does not provide execution price,
   quantity, or notional.
4. `#23` First LLM-backed Value Manager adapter: produce one verified
   recommendation from the authoritative Alpha Vantage ResearchBatch.
5. `#17` Performance tracking and comparison: produce comparable managed and
   benchmark valuations.
6. `#18–#21` Basic MVP dashboard: expose portfolio state, decisions, and
   performance history.

## Post-MVP roadmap

The post-MVP roadmap is maintained in [Product Roadmap](roadmap.md). v0.1 already
covers the local weekly loop described in Phases 2–4 (operator UI, live prices,
paper SPY fulfillment, SQLite durability, Value Manager, approval, and managed
paper execution). Remaining later-phase items are listed below.

- **Phase 0 — Release 1.0 Consolidation:** integrate completed MVP work into
  one canonical baseline; this phase does not add product functionality.
- **Phase 2 — Usable Operator Interface:** make Variant C and a thin FastAPI
  application adapter the local operator interface.
- **Phase 3 — Live Market Data and Fair SPY Baseline:** replace synthetic
  observations and fulfill the mechanical benchmark path before weekly use.
- **Phase 4 — Weekly Paper Trading:** add the smallest SQLite-backed local
  workflow that can be operated week after week.
- **Phase 5 — Research v2; Phase 6 — Strategy Expansion; Phase 7 —
  Operational Hardening:** Research v2 screening, reuse, derived metrics,
  OVERVIEW bootstrap, and the approved 30-name `value-us-equities-v1` snapshot
  as the live managed universe are implemented; remaining research work is
  additional evidence sources, then later phases follow after the weekly loop is
  useful.

## Deferred beyond v0.1

v0.1 already retrieves and assembles a screened five-slot Alpha Vantage
ResearchBatch over the versioned managed universe. The following remain later
work:

- Additional research evidence sources and retrieval adapters.
- AI reviewer adapter.
- Recurring Cash Event scheduling.
- Additional active managers and constitutions; SELL and rebalance.
- Advanced performance analytics, optimization, or forecasting.
- Export/import backups, cloud persistence, broker integration, and real-money execution.

## Manager-Specific Risk Constitutions

- [x] **Lane 0 — ADR and contract alignment:** separate hard System Safety from
  advisory Manager Risk Constitutions, prohibit silent resizing, and document
  legacy and multi-manager boundaries.
- [x] **Lane 1 — typed policy domain:** define typed repository artifacts,
  independent versions, compatibility, canonical SHA-256 hashes, Decimal
  strings, evidence coverage, risk snapshots, and invariants.
- [x] **Recovery amendment:** publish advisory `value-risk-v2.0.0`, preserve the
  inactive `value-risk-v1.0.0` identity, remove deterministic sizing authority
  from current manager personality and evidence profiles, and align ADR-008.
- [ ] **Lane 2 — hard safety plus advisory assessment:** salvage universal
  System Safety layering and audit metadata, keep target weights unchanged,
  and represent manager-constitution deviations in a separate non-gating
  result. CRM 25% must remain mechanically valid when universally safe.
- [ ] **Lane 3 — durable compatibility:** persist validation and exact policy
  artifacts/hashes, decode legacy v0.1 journals through the discriminated
  reference without changing re-encoded historical payloads, and enforce
  immutability.
- [ ] **Lane 4 — production application/API:** select policy by manager and
  portfolio, expose layered results, and add an explicit new linked-cycle
  revision command.
- [ ] **Lane 5 — execution-time revalidation:** evaluate the active System
  Safety Envelope against current state, verify journaled advisory-policy
  lineage, and persist each execution-policy check.
- [ ] **Lane 6 — AI Reviewer integration:** generalize Value-specific Reviewer
  contracts and persist the explicit override flag plus mandatory rationale for
  a paper-only override of REQUEST_CHANGES containing a CRITICAL finding. This
  optional adapter may follow risk-policy activation; no AI Reviewer override
  path exists until it lands.
- [ ] **Lane 7 — multi-manager experiment:** separate managed portfolios,
  histories, policy artifacts, and decisions while keeping controlled inputs
  and performance conventions equal.

Richer evidence acquisition that could define an enhanced Value durability
profile is separate later research work and must not be fabricated.

Policy activation is blocked until Lanes 1–5 are integrated and their
canonical-hash, migration, restart, persistence, and execution-time
revalidation tests pass. After activation, new production cycles must use
current policy references; legacy identity is decode-only.
