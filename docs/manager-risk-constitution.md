# Manager Risk Constitution Contract

## Status and scope

This contract defines a minimal universal System Safety Envelope and a separate
advisory Manager Risk Constitution. Lane 1 provides typed, hashable domain
artifacts only. The production workflow still uses the v0.1 mechanical
validator and does not yet persist or activate these artifacts.

Three conceptual layers are recognized:

1. **System Safety Envelope** — universal hard deterministic enforcement.
2. **Manager Risk Constitution** — versioned advisory strategy personality.
3. **Optional explicit Manager or Portfolio Mandate** — potentially hard for a
   future deliberately constrained portfolio; not implemented or active now.

## System Safety Envelope

The universal envelope owns:

- supported actions and instruments;
- no unsupported shorting, margin, leverage, options, or execution mechanics;
- BUY weights greater than zero and no greater than 100%;
- exact `SecurityIdentity` and currency agreement;
- attributable price observations and research inputs;
- no future-dated inputs and timezone-aware chronology;
- cash feasibility, non-negative state, Decimal-safe arithmetic, and positive
  executable quantity;
- immutable research-to-execution lineage;
- HOLD, failed safety validation, REJECTED, and EXPIRED outcomes never execute;
- human approval before execution; and
- managed/benchmark separation.

There is no universal concentration ceiling below 100% for the paper
experiment. The envelope uses its own semantic version namespace, canonical
artifact hash, and exact repository loading source.

## Manager Risk Constitution

The manager-specific artifact is supplied to the manager, AI Reviewer, human
operator, and durable audit history. It describes:

- risk posture;
- normal, non-binding sizing guidance;
- concentration, turnover, rotation, and cash preferences;
- expectations for explaining unusual allocations;
- evidence maturity and missing-data concerns;
- balance-sheet, liquidity, durability, and valuation questions; and
- manager-specific Reviewer focus.

It does not pass or fail a trade, cap a weight, or manufacture a replacement
weight. A mechanically valid 80% or 100% target is representable. Confidence is
descriptive and has no sizing or safety authority.

The current action contract remains BUY/HOLD only. Extreme concentration is
therefore representable only when a funded long-only BUY can express it; SELL,
multi-leg liquidation, and portfolio rotation remain deferred rather than being
silently inferred from a target weight.

The conceptual advisory artifact is:

```text
ManagerRiskConstitution
  schema_version
  risk_constitution_version
  manager_type
  compatible_investment_constitutions
  sizing_guidance
  risk_personality
  evidence_bands
  cash_deployment_policy
  balance_sheet_policy
  liquidity_policy
  diversification_policy
  missing_data_policy
  loading_source
  content_hash
```

`SizingGuidance` and `ManagerRiskPersonality` are explicitly advisory. The
current artifact has no `SizingLimits`. Evidence-band records contain coverage
requirements but no weight ceilings.

## Artifact identity and compatibility

Artifacts are immutable, repository-owned typed values. Risk-constitution
versions have an independent semantic namespace and declare compatible exact
investment-constitution version/hash pairs. Missing, ambiguous, incompatible,
or hash-mismatched selection fails as configuration integrity before manager
invocation.

Canonical JSON uses sorted keys, no insignificant whitespace, stable enum
strings, materialized schema fields, Unicode NFC, explicit nulls, finite Decimal
strings in normalized fixed-point form, and lowercase SHA-256. Loading source
and content hash are excluded from the hashed payload. A version may never be
reused for changed content.

`value-risk-v1.0.0` preserves the reviewed but never-activated hard-sizing
artifact and its original hash. The production `value-v1.0.0` investment
constitution also remains byte-for-byte frozen. The amended methodology is
`value-v2.0.0`, and advisory `value-risk-v2.0.0` declares compatibility only
with its exact hash. No production migration is required because the new risk
artifact was never activated.

## Value advisory personality v2

Value is moderately risk-averse and normally prefers measured entries. A
5–10% starter is normal guidance, not a minimum or maximum. Value may propose a
larger concentration when valuation, quality, and durability evidence appears
unusually compelling, but it should explain the deviation and confront the
associated downside.

Value has:

- no manager-specific deterministic initial-position ceiling;
- no manager-specific deterministic total single-name ceiling;
- no manager-specific deterministic one-cycle-add ceiling;
- no minimum cash reserve;
- no deterministic leverage or current-ratio threshold; and
- no confidence-based authority.

The AI Reviewer should challenge exceptional concentration, normalized cash-flow
durability, leverage and liquidity, provenance, missing evidence, share-count
reliability, and economically misleading comparisons. These findings inform the
human; they do not alter System Safety or automatically block execution.

## Evidence coverage profiles

Evidence profiles assess typed coverage maturity, not investment quality or
portfolio authority. `BASELINE_RESEARCH_V2` requires exact candidate identity,
current/reused-current OVERVIEW and statement coverage, correct endpoint
reliability/freshness, and the locked Research v2 derived-metric set with typed
inputs and explicit `MissingData` where necessary.

The richer evidence profile remains reserved and unreachable until later
research contracts define it. Neither profile contains a maximum target weight.

## Recommendation, review, and human outcome

The manager's target remains immutable. System Safety evaluates it unchanged
and deterministic code converts only a mechanically passing target to dollars
and quantity. Advisory assessment may record alignment, deviations, evidence
gaps, and Reviewer concerns in separate non-gating artifacts.

The Reviewer never resizes a recommendation. For paper trading, a human may
reject, request a new linked cycle, or approve despite adverse advisory findings
with the required durable rationale. No human or Reviewer may override System
Safety.

Reconsideration requires a new cycle linked through
`revision_of_decision_cycle_id`; the original recommendation and journal remain
immutable.

## Execution-time behavior

Immediately before execution, deterministic code reconstructs current
authoritative portfolio and quote state and revalidates the unchanged approved
target against the currently active System Safety Envelope. It verifies the
journaled investment and Manager Risk Constitution identities for audit lineage
but does not turn advisory guidance into an execution veto.

## Optional future mandates

A future deliberately constrained portfolio may require hard rules such as
prohibited asset classes or contractual concentration/cash limits. Those rules
must be modeled separately from manager personality, explicitly selected, and
versioned and hashed. This contract does not build or activate that subsystem.

## Legacy behavior

Existing v0.1 journals remain authoritative and immutable. A
`LegacyPolicyReference` may identify them in presentation without fabricating a
policy artifact, version, source, or hash. `CurrentPolicyReference` retains the
exact investment, safety, and manager-risk artifacts for future current cycles.

## Multi-manager fairness

Value, Growth, and Conservative receive equal funding, evidence cutoff,
opportunity universe, provider inputs, cadence, System Safety, execution
mechanics, human procedure, and benchmark treatment. Separate managed
portfolios and histories are mandatory. Their concentration, turnover, cash
preference, and reasoning are experimental variables.

The Reviewer uses one procedure but judges each manager against its own risk
personality rather than imposing a shared diversification preference.

## Revised implementation sequence

1. **Recovery amendment:** align ADR-008/contracts and publish the advisory Lane
   1 artifact without activating runtime behavior.
2. **Lane 2 salvage:** retain universal System Safety layering and audit metadata;
   add separate non-gating manager-constitution assessment.
3. **Durable compatibility:** persist exact artifacts and legacy/current
   references without rewriting history.
4. **Application/API selection:** explicit registry and operator visibility.
5. **Execution revalidation:** current System Safety plus immutable lineage.
6. **AI Reviewer integration:** manager-specific advisory review and durable
   human rationale.
7. **Multi-manager experiment:** separate portfolios under controlled shared
   conditions.

No later lane is authorized by this amendment.
