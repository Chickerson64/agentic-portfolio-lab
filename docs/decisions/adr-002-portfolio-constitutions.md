# ADR-002: Portfolio Constitutions

**Date:** 2026-08-08  
**Status:** Accepted

## Motivation

The system needs to support portfolios with different objectives and deployment behavior without tying portfolio accounting to a particular AI manager. A passive SPY baseline and an actively managed Value portfolio are both useful, but their decision mechanisms differ.

## Decision

Every portfolio is defined by:

```text
Portfolio + Constitution + Manager (optional)
```

A constitution defines the portfolio's objective, investment philosophy, capital deployment policy, constraints, and decision cadence. Examples include a Passive Index Constitution, a Value Constitution, and a Growth Constitution.

The Passive Index Constitution is deterministic rather than AI-driven. Its rules mechanically determine its behavior. A portfolio manager is optional: AI-managed portfolios use a manager to produce investment intent under their constitution, while deterministic portfolios use constitution rules directly.

## Consequences

- Deterministic and AI-managed portfolios share portfolio, cash, valuation, validation, approval, and execution infrastructure.
- Portfolio behavior is explicit, versionable, and reviewable independently of the implementation of any particular manager.
- A benchmark remains a mechanical baseline rather than an agent or a special case embedded in active-manager logic.
- New portfolios can be added by defining a constitution and selecting a manager only when one is needed.

## Alternatives Considered

- **Require an AI manager for every portfolio:** rejected because a passive benchmark should be deterministic and reproducible.
- **Embed policy directly in portfolio models:** rejected because it conflates state with behavior and makes new portfolio types harder to add safely.
- **Treat SPY as a special reporting-only calculation:** rejected because it would not preserve an auditable portfolio state or contribution history.
