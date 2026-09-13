# ADR-012: V2 immutable target-derived batch plans

**Date:** 2026-09-13
**Status:** Accepted

## Decision

V2 manager output remains an immutable complete target allocation. Deterministic
code derives one immutable ordered batch plan from that target, the exact
portfolio state, and an immutable complete price snapshot. Plans sell first,
then buy, so proceeds may fund purchases. System Safety validates the exact
plan; it never rescales or normalizes manager weights.

The only no-op policy is `v1-8dp-half-even`: quantities are calculated and
rounded to eight tradable fractional-share decimal places. A required delta
that rounds to `0.00000000` produces no leg. There is no independent weight or
percentage tolerance.

BUY initiates an absent holding; ADD increases one; TRIM partially reduces one;
EXIT removes an explicit V2 `REMOVE` target; SELL removes an existing holding
omitted from the complete target. All execution is simulated, long-only, and
cash-funded. A human approval contains a SHA-256 structural binding over exact
target, plan, original portfolio, and price snapshot. Execution rejects any
changed portfolio or snapshot before it applies the full batch atomically.

## Consequences

V1 BUY journals, approvals, executions, and history remain compatible and are
not reinterpreted. V2 batch persistence/audit integration is additive; no
brokerage integration or real-money order path is introduced.
