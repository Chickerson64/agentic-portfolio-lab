# ADR-001: Cash Event Model

**Date:** 2026-08-08  
**Status:** Accepted

## Motivation

Portfolio capital must be auditable without assuming that received cash is immediately invested. Different portfolios may deploy the same capital at different times and under different rules. Combining receipt and investment would obscure both buying power and portfolio-specific behavior.

## Decision

Investment capital enters the system through immutable Cash Events, not automatic trades. A Cash Event creates buying power in each receiving portfolio. Receiving cash and investing cash are separate deterministic events.

Every portfolio receives identical Cash Events. Each portfolio independently decides whether and when to deploy available cash according to its constitution and, where applicable, its manager.

## Consequences

- Cash balances can be explained independently from trade history.
- Portfolios can share identical funding while following different deployment policies.
- A portfolio may legitimately retain cash when no investment clears its bar.
- Benchmark investment timing must be an explicit deterministic constitution rule; it must not be inferred from cash receipt.

## Alternatives Considered

- **Automatically invest every contribution:** rejected because it conflates funding with investment intent and prevents portfolios from holding cash.
- **Let managers create cash events:** rejected because funding is an external portfolio event, not an investment decision.
- **Maintain separate contribution schedules per portfolio:** rejected because identical cash events are needed for meaningful portfolio comparisons.
