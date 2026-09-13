# ADR-013: Research V3 candidate-and-holding batches

**Date:** 2026-09-13
**Status:** Accepted

## Decision

Research V3 records an evidence-oriented subject batch assembled from the exact
V2 screening run and every nonzero current holding. Subjects are explicitly
labelled as new candidates or existing holdings. Screening rank and features
are retained only as immutable evidence context; the contract contains no
allocation, target-weight, trade, or manager-decision fields.

Provider deep retrieval is deterministically bounded by
`max_deep_research_subjects`. Subjects beyond that cap remain in the durable
batch with explicit `NOT_RETRIEVED` evidence and missing-data state, so a cap
never silently drops a required holding. V3 adapts its evidence packets to the
existing V2 manager research boundary without changing V1/V2 stored artifacts.

## Consequences

An unbounded screening universe cannot cause unbounded provider calls. Missing,
stale, contradictory, and provider-failure evidence remains explicit and
auditable. V3 storage is append-only and uses the established versioned codec,
leaving V1/V2 research reads unchanged.
