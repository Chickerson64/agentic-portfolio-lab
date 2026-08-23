# Open Questions

## Resolved for v0.1

- The first Value Manager adapter uses the OpenAI Responses API, `OPENAI_API_KEY`, default model `gpt-5.6-terra`, and optional `OPENAI_VALUE_MANAGER_MODEL` / `OPENAI_VALUE_MANAGER_REASONING_EFFORT`.
- The operator interface is FastAPI plus Variant C. Streamlit remains a diagnostic demo UI.
- Paper benchmark fills use a persisted Twelve Data quote attributed as `twelve-data-quote-close-field`, not an official regular-session close. See ADR-006.
- Durable local persistence is SQLite via `AGENTIC_PORTFOLIO_LAB_DB_PATH`.
- Market-data and research providers are Twelve Data and Alpha Vantage.
- Research v2 screening, statement reuse, derived metrics, and operator
  OVERVIEW bootstrap (≤25 requests per invocation) have landed. Rank and slot
  role stay off the Value Manager payload. The operator-approved 30-name
  `VALUE_US_EQUITIES_V1` snapshot is live.

## Resolved by ADR-008 for post-v0.1 implementation

- Deterministic risk uses a minimal universal System Safety Envelope plus
  versioned Manager Risk Constitutions.
- The manager proposes an immutable target weight. Validation never silently
  normalizes or resizes it.
- Value v1 uses 5–10% starter guidance, a 10% baseline initial ceiling, a 15%
  enhanced-evidence initial ceiling, a 25% total single-name ceiling, and a
  five-percentage-point one-cycle add ceiling.
- Value v1 has no minimum-cash requirement and no deterministic leverage or
  current-ratio threshold.
- Confidence is descriptive and has no sizing authority in v1.
- The current paper System Safety Envelope has no universal concentration
  ceiling below 100%; real-money catastrophic policy is deferred.
- Risk constitutions are repository-owned typed artifacts with Decimal strings,
  independent versions, exact snapshots, and content hashes.
- A failed recommendation can be reconsidered only in a new explicitly linked
  decision cycle.
- During paper trading only, a human may override a `REQUEST_CHANGES`
  ReviewerResult containing at least one `CRITICAL`-severity finding with an
  explicit durable flag and dedicated non-empty rationale; deterministic
  failures remain non-overridable.

## Still open

- What additional evidence sources should later enrich packets beyond the
  current OVERVIEW, statements, and derived metrics?
- What exact typed, freshness, and provenance prerequisites should make the
  enhanced Value evidence band reachable?
- Should later Value policy versions add deterministic leverage or liquidity
  thresholds, and what evidence would justify their values?
- What Cash Event schedule should be used after explicitly supplied events?
- What should trigger re-review of an existing position?
- What Reviewer authority and universal catastrophic concentration ceiling
  should apply if a real-money workflow is ever designed?
- After the first activation gate, what operator governance should authorize a
  new System Safety Envelope version while already-approved decisions remain
  pending? Execution will use the new active envelope and may stop, but the
  operational rollout procedure remains open.
