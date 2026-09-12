# ADR-009: Additive Versioned Portfolio Target V2

**Date:** 2026-09-12  
**Status:** Accepted (domain contract only)

## Decision

Add an immutable, typed, provider-independent `portfolio-target-v2` domain
contract alongside V1. A V2 target identifies one portfolio and records a
complete Decimal allocation: explicit cash plus security targets summing exactly
to `1.000000` with at most six fractional places. It records rationale,
risk/concentration and benchmark-active-risk commentary, cash classification
and justification, and position role, thesis, confidence, evidence lineage,
invalidation, review lineage, and existing-holding disposition.

V1 `PortfolioRecommendation` and its history remain readable and unchanged.
V2 does not encode manager BUY/SELL/HOLD/TRIM/EXIT actions. Deterministic code
derives current-versus-target actions outside manager intent.

## Boundaries and semantics

Human approval remains mandatory. System Safety is the hard deterministic
boundary; Manager Risk and Reviewer remain explicit review and audit boundaries
and cannot silently resize or authorize an unsafe target. Models are
provider-independent and never fetch evidence. Strategic cash is intentional;
accidental cash describes residual or unplanned posture. Initial construction
and rebalance are explicit V2 modes; neither mode derives trades.

## Migration path

Future work proceeds in this order: manager adapter/context; decision journal
and persistence/versioned read projections; Reviewer; System Safety and Manager
Risk evaluation; approval; deterministic trade derivation/execution; API/UI;
then audit/history projections. This ADR implements none of those migrations.

## Consequences

The contract expresses retained, increased, reduced, removed, and newly
initiated positions without rewriting V1. Construction-time validation rejects
duplicate or unsupported identities, missing research evidence, malformed
weights or lineage collections, malformed ticker/exchange syntax, ambiguous
zero-weight dispositions, and incomplete or overallocated targets. Allocation
arithmetic uses the domain's fixed high-precision Decimal context rather than
the caller's ambient context, and no value is silently normalized. Existing
runtime workflows and journals remain on V1 until each migration seam receives
its own approval and verification.
