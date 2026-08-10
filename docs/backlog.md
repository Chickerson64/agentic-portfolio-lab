# Backlog

## Completed foundation

- [x] Define the Portfolio Manager, Research Packet, portfolio-domain, and Value Manager constitution contracts.
- [x] Implement immutable portfolio, trade, research, valuation, benchmark, recommendation, constitution, and approval domain models.
- [x] Implement pre-approval Value Manager decision orchestration: workflow, deterministic validation, reviewer, journal, and human approval state.
- [x] Record the Cash Event, Portfolio Constitution, and Decision vs Execution architecture decisions.

## First end-to-end MVP

The first usable MVP is a paper-trading demonstration with manually supplied,
source-backed Research Batches. It intentionally defers automated research
retrieval until the decision and simulation path is proven.

1. `#16` Cash Event funding workflow: apply the same explicit Cash Event to the
   Value portfolio and the Passive Index portfolio, creating buying power
   without automatically trading.
2. `#15` Passive Index Constitution: deploy available cash into SPY at the next
   applicable regular-session close using the shared deterministic execution
   infrastructure and price convention.
3. `#22` Post-approval simulated execution: execute an approved BUY as a
   simulated next-applicable regular-session-close fill and update the Value
   portfolio.
4. `#23` First LLM-backed Value Manager adapter: produce one verified
   recommendation from a supplied Research Batch.
5. `#17` Performance tracking and comparison: produce comparable managed and
   benchmark valuations.
6. `#18–#21` Basic MVP dashboard: expose portfolio state, decisions, and
   performance history.

## Deferred until after the first MVP

- Automated research retrieval, normalization, and Research Batch assembly.
- Recurring Cash Event scheduling.
- Additional active managers and constitutions.
- Advanced performance analytics, optimization, or forecasting.
- Production persistence, broker integration, and real-money execution.
