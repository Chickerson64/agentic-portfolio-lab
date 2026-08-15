# Backlog

## Completed foundation

- [x] Define the Portfolio Manager, Research Packet, portfolio-domain, and Value Manager constitution contracts.
- [x] Implement immutable portfolio, trade, research, valuation, benchmark, recommendation, constitution, and approval domain models.
- [x] Implement pre-approval Value Manager decision orchestration: workflow, deterministic validation, reviewer, journal, and human approval state.
- [x] Record the Cash Event, Portfolio Constitution, and Decision vs Execution architecture decisions.

## First end-to-end MVP

The first usable MVP is a local paper-trading demonstration. v0.1 assembles a
five-company ResearchBatch through Alpha Vantage. Research v2 / richer evidence
remains future work.

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
  Operational Hardening:** first-week Alpha Vantage assembly is in v0.1;
  richer research and later phases follow after the weekly loop is useful.

## Deferred beyond v0.1

v0.1 already retrieves and assembles a first-week Alpha Vantage ResearchBatch
for five candidates. The following remain later work:

- Research v2 / richer fundamental, cash-flow, dilution, and valuation evidence.
- AI reviewer adapter.
- Recurring Cash Event scheduling.
- Additional active managers and constitutions; SELL and rebalance.
- Advanced performance analytics, optimization, or forecasting.
- Export/import backups, cloud persistence, broker integration, and real-money execution.
