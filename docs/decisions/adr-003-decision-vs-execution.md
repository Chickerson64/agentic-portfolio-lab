# ADR-003: Decision vs Execution

**Date:** 2026-08-08  
**Status:** Accepted

## Motivation

Investment reasoning is subjective and may be AI-assisted, while validation, approval, execution, and accounting must be deterministic. Allowing managers to execute trades would blur this boundary and weaken the system's safety and audit trail.

## Decision

Managers never execute trades. They produce investment intent only.

Deterministic systems own validation, review routing, approval enforcement, execution, and portfolio mutation. A manager recommendation can become a trade only after it passes the relevant deterministic stages.

## Consequences

- Every state-changing trade has a traceable path from intent through approval to execution.
- The same recommendation can be validated and simulated repeatedly with the same deterministic result.
- Manager behavior and financial state transitions can be tested separately.
- Human approval remains an enforceable control point.
- Future brokerage integration can attach to the execution boundary without granting a manager brokerage authority.

## Alternatives Considered

- **Managers execute their own recommendations:** rejected because it couples subjective reasoning to irreversible state changes.
- **Validate only after portfolio mutation:** rejected because invalid trades could corrupt deterministic state.
- **Put approval inside a manager:** rejected because approval is a workflow control, not investment reasoning.
