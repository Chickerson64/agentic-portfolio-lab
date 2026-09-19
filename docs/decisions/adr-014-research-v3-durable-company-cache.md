# ADR-014: Durable reusable Research V3 company cache

**Date:** 2026-09-18
**Status:** Accepted

## Decision

Persist every successful Alpha Vantage three-endpoint company document as an
append-only version immediately after it is retrieved. V3 batches continue to
be immutable run-specific evidence artifacts, but may reuse the latest company
version retrieved within seven days. The document retains its provider identity
and source dates; a later refresh appends another version rather than changing
historical evidence.

The durable cache also atomically reserves a daily number of deep-research
subjects. Its default is eight subjects, corresponding to 24 calls on the
current three-call Alpha Vantage path. A batch keeps its complete screened and
holding subject slate: fresh cache entries are reused, stale/missing entries
are fetched only while budget permits, and all remaining entries are represented
as `NOT_RETRIEVED`.

## Consequences

This cache covers only deep company research. Screening, prices, momentum, and
liquidity remain inputs to their existing per-cycle services and are never
satisfied from this cache. The cache does not alter the Value Manager
constitution, screening formula, target policy, or execution policy.
