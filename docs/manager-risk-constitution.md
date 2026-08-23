# Manager Risk Constitution Contract

## Status and scope

This document defines the accepted contract for manager-specific deterministic
risk policy. Lane 0 is documentation and contract alignment only. The current
runtime still performs the v0.1 mechanical risk checks and does **not** yet load
or enforce the artifacts described here.

The architecture has two policy layers:

1. a minimal universal **System Safety Envelope**; and
2. a versioned **Manager Risk Constitution** selected for the exact manager and
   managed portfolio.

Both layers are repository-owned typed, versioned, content-hashed artifacts.
They are selected explicitly; neither supports an implicit “latest” fallback.

The investment constitution remains a separate methodology artifact. It tells
the manager how to reason about investments. The Manager Risk Constitution
expresses deterministic strategy limits. The System Safety Envelope protects
platform integrity and non-bypassable safety without imposing one investment
philosophy on every manager.

## Ownership boundaries

### System Safety Envelope

The universal envelope owns only system-wide constraints, including:

- supported actions and instruments;
- no shorting, margin, leverage creation, options, or unsupported execution;
- BUY weights greater than zero and no greater than 100%;
- exact `SecurityIdentity` and currency agreement;
- attributable price observations and chronology;
- no future-dated price or research inputs;
- cash feasibility, non-negative state, Decimal-safe arithmetic, and positive
  executable quantity;
- immutable lineage from research through recommendation, validation, human
  outcome, execution, and history;
- HOLD, failed validation, REJECTED, and EXPIRED outcomes never execute;
- human approval before managed execution; and
- separation of managed and benchmark portfolios.

For the current paper experiment, the envelope has no concentration ceiling
below 100%. A sub-100% catastrophic universal ceiling is deferred until a
real-money safety design. Strategy-specific concentration belongs to each
Manager Risk Constitution.

The System Safety Envelope uses its own semantic version namespace, for example
`system-safety-v1.0.0`. Every decision-time journal stores the exact immutable
envelope snapshot, repository loading source, and canonical SHA-256 content
hash used for initial validation. A version may never be reused for different
content.

Its conceptual typed artifact is:

```text
SystemSafetyEnvelope
  schema_version
  system_safety_envelope_version
  supported_actions
  supported_security_types
  prohibited_mechanics
  identity_and_currency_policy
  chronology_and_provenance_policy
  cash_and_arithmetic_policy
  approval_and_execution_policy
  lineage_policy
```

The exact snapshot, not a version lookup performed later, is the reproducible
decision-time input.

### Manager Risk Constitution

The manager-specific artifact owns deterministic strategy policy, including:

- typical sizing guidance;
- maximum initial and total single-name target weights;
- maximum one-cycle additions;
- evidence-dependent sizing bands;
- cash-deployment preferences or limits;
- manager-specific diversification, balance-sheet, and liquidity policy; and
- behavior when required policy evidence is missing.

Future Growth / Tech and Conservative managers may define materially different
limits. Universal validation must not contain branches that encode one
manager's philosophy.

### Manager, Reviewer, and human

- The manager proposes one immutable `target_weight`. Deterministic code
  validates that exact weight and, only after it passes, converts it to notional
  and quantity. It never caps, normalizes, or silently resizes the weight.
- `confidence_score` is descriptive in v1. It does not increase a sizing limit,
  cure missing evidence, or authorize execution.
- The AI Reviewer critiques thesis quality, evidence sufficiency,
  contradictions, and methodology. It does not mutate the recommendation or
  calculate a replacement weight.
- The human remains the final paper-trading approval authority. During paper
  trading only, a human may override `REQUEST_CHANGES` containing at least one
  `CRITICAL`-severity finding, but the override requires the dedicated durable
  flag and rationale defined below.

## Repository-owned typed artifact

A Manager Risk Constitution is a repository-owned, typed, immutable artifact,
not an untyped rules expression or prompt fragment. Its conceptual fields are:

```text
ManagerRiskConstitution
  schema_version
  risk_constitution_version
  manager_type
  compatible_investment_constitutions (version/hash pairs)
  sizing_guidance
  sizing_limits
  evidence_bands
  cash_deployment_policy
  balance_sheet_policy
  liquidity_policy
  diversification_policy
  missing_data_policy
```

Repository path/loading source and content hash are immutable snapshot
metadata, not self-referential fields in the hashed content. The content hash
is computed over the validated artifact without embedding the hash inside that
payload.

Policy Decimals are serialized as JSON strings, such as `"0.1"`, never as
binary floating-point numbers. The eventual domain model must parse and
validate them as `Decimal` values.

Risk-constitution versions use an independent semantic namespace, for example
`value-risk-v1.0.0`. They do not reuse an investment-constitution version such
as `value-v1.0.0`, because methodology prose and deterministic risk policy can
change independently. The artifact declares its manager type and compatible
investment-constitution version/hash pairs; a mismatch fails before manager
invocation.

Every decision evaluated under the new contract persists:

- the exact investment-constitution version, repository loading source,
  immutable artifact snapshot, and canonical SHA-256 hash;
- the exact Manager Risk Constitution version, repository loading source,
  immutable artifact snapshot, and canonical SHA-256 hash;
- the exact decision-time System Safety Envelope version, repository loading
  source, immutable artifact snapshot, and canonical SHA-256 hash; and
- the evaluation inputs and rule results.

A version string alone is not proof of artifact identity. Published artifact
contents are immutable. Any semantic change requires a new version and hash;
reusing a version for changed content is invalid.

Before publishing any investment constitution, System Safety Envelope, or
Manager Risk Constitution with a persisted artifact hash, Lane 1 must
implement and test this canonical hash contract:

- validate the complete typed artifact first;
- serialize canonical JSON as UTF-8;
- normalize every string and object key to Unicode NFC, reject lone surrogates
  and all non-scalar input, and sort object keys lexicographically by the
  resulting Unicode scalar-value sequence;
- emit no insignificant whitespace and use `,` and `:` separators;
- escape quotation mark as `\"` and reverse solidus as `\\`; encode controls
  U+0008, U+0009, U+000A, U+000C, and U+000D as `\b`, `\t`, `\n`, `\f`, and
  `\r`, encode all other U+0000–U+001F controls as lowercase `\u00xx`, and emit
  every other Unicode scalar value literally as UTF-8 bytes;
- serialize enums by their stable string values;
- materialize all schema defaults and serialize every schema-defined optional
  field, using explicit `null` when it has no value;
- preserve array order where order is part of the typed contract;
- exclude snapshot metadata (`loading_source` and `content_hash`) from the
  hashed payload;
- canonicalize every finite Decimal as a non-exponent fixed-point string with
  no leading `+`, no redundant integer leading zeros, no trailing fractional
  zeros, no trailing decimal point, and `"0"` for positive or negative zero;
  thus equivalent values such as `Decimal("0.10")` and `Decimal("0.1")` hash
  identically without changing their numeric meaning; and
- encode SHA-256 as 64 lowercase hexadecimal characters.

Artifacts must not be published or selected until this serialization and its
golden hash vectors exist. The identical canonical contract applies to the
investment-constitution hashes persisted alongside risk policy.

## Authoritative policy selection

The application selects policy through an explicit registry keyed by exact
managed `portfolio_id` plus `manager_type`. Each entry configures exact
investment-constitution and Manager Risk Constitution versions and hashes.
The selected risk artifact must declare compatibility with the exact selected
investment artifact version/hash pair.

There is no implicit latest-version, manager-only, portfolio-only, or default
fallback. Missing, duplicate, ambiguous, hash-mismatched, or incompatible
configuration fails closed before manager invocation. System Safety Envelope
activation is likewise explicit and resolves one exact version and hash.

## Guidance and enforceable limits

The typed artifact separates:

- `SizingGuidance`: manager-visible typical sizes and cash preferences that do
  not themselves pass or fail a recommendation; and
- `SizingLimits`: hard deterministic ceilings and evidence prerequisites.

This prevents prose such as “measured position” from being mistaken for an
enforced limit.

## Value Manager Risk Constitution v1

The accepted Value-specific policy is:

| Policy | Value v1 |
|---|---:|
| Typical starter guidance | 5–10% |
| Maximum initial position, baseline Research v2 | 10% |
| Maximum initial position, enhanced evidence | 15% |
| Maximum total single-name target | 25% |
| Maximum one-cycle add | 5 percentage points |
| Minimum cash reserve | None |
| Confidence sizing authority | None |

These are not universal limits. The 25% maximum total target does not imply
that any 25% recommendation is prudent or permitted as an initial position.
All applicable rules must pass.

The enforceable predicates are inclusive:

- an **initial position** means the synchronized authoritative pre-trade
  managed portfolio has no positive-quantity position for the exact
  `SecurityIdentity`;
- an **add** means that portfolio has a positive-quantity position for the
  exact `SecurityIdentity`;
- a BUY must increase exact-identity exposure: its proposed target weight must
  be greater than the synchronized current exact-identity weight;
- baseline initial: `target_weight <= Decimal("0.1")`;
- enhanced initial: `target_weight <= Decimal("0.15")`;
- every BUY: proposed total exact-identity target
  `<= Decimal("0.25")`;
- every add: `target_weight - current_exact_identity_weight <= Decimal("0.05")`;
  and
- exactly-equal boundary values pass.

All applicable rules are cumulative. For example, an initial BUY must satisfy
its evidence-band initial ceiling and the total single-name ceiling. The 5–10%
starter range is guidance only: it creates no deterministic minimum and a
smaller positive BUY may pass.

No deterministic leverage or current-ratio threshold is adopted in v1.
Balance-sheet and liquidity facts remain required manager, Reviewer, and human
considerations; later policy versions may add deterministic thresholds only
through an explicit product decision.

## Evidence bands

Evidence bands are explicit typed coverage assessments, not subjective scores.
The assessment verifies presence, provenance, freshness, and required field
shape. It does not decide whether the evidence is economically persuasive.

`BASELINE_RESEARCH_V2` is the only currently defined and reachable band. It
requires the exact candidate `SecurityIdentity` to match the packet and every
endpoint record. The required endpoints are `OVERVIEW`, `INCOME_STATEMENT`,
`BALANCE_SHEET`, `CASH_FLOW`, and `EARNINGS`. Each must be current under the
existing packet/cycle-as-of freshness contract, represented by
`FETCHED_THIS_CYCLE` (current) or `REUSED_CURRENT`; `STALE` or `MISSING`
coverage disqualifies the band.

The current derived-metric identifiers are:

- `net_debt`, `current_ratio`, `gross_margin`, `operating_margin`, and
  `net_margin`;
- `fcf`, `ttm_ocf`, `ttm_capex`, `ttm_fcf`, `ttm_net_income`, and
  `ttm_revenue`; and
- `cash_conversion`, `share_count_change`, `market_cap`, `enterprise_value`,
  and `fcf_yield`.

Every defined derivation must have been evaluated deterministically from its
attributable typed inputs and produce either a typed Decimal value or explicit
typed `MissingData`. Baseline does not require every metric to be numerically
present. `MissingData` is preserved, never inferred or interpreted as zero,
and may still lead the manager, Reviewer, or human to reject a BUY. Missing a
derived-metric record entirely, using an unknown metric set, or losing input
attribution disqualifies the band.

An enhanced band is reserved so the accepted 15% enhanced initial ceiling can
be represented, but Lane 0 does not define the evidence that unlocks it. Until
a later contract and acquisition path are implemented, no packet can qualify
for enhanced sizing. Richer durability evidence and acquisition remain later
work.

## Deterministic evaluation and journal behavior

Each deterministic rule result will record:

- layer: `SYSTEM_SAFETY` or `MANAGER_POLICY`;
- stable rule identifier;
- applicable policy version;
- pass or fail;
- actual value and allowed threshold, where applicable;
- relevant immutable input references; and
- a human-readable explanation.

Stable manager-policy rule identifiers include:

- `RISK_CONSTITUTION_COMPATIBILITY`;
- `TARGET_WEIGHT_INCREASE`;
- `INITIAL_TARGET_WEIGHT_MAX`;
- `SINGLE_NAME_TARGET_WEIGHT_MAX`;
- `PER_CYCLE_ADD_MAX`;
- `EVIDENCE_BAND_WEIGHT_MAX`; and
- `REQUIRED_EVIDENCE_PRESENT`.

Later policy versions may add stable identifiers rather than changing the
meaning of an existing one. Value v1 has no active
`MINIMUM_POST_TRADE_CASH`, leverage-threshold, or current-ratio-threshold rule.

Evaluation uses an immutable, synchronized risk snapshot containing exact
portfolio state, attributable valuation inputs, current and proposed weights,
cash weight, initial-position/add classification, and evidence coverage.

When sizing or another policy rule fails:

1. preserve and journal the original recommendation unchanged;
2. persist the violations;
3. create no `ValidatedTrade` and make the cycle non-executable;
4. make no automatic manager retry; and
5. never cap or resize the recommendation.

Reconsideration requires an explicit operator action and a new decision cycle
linked through the immutable field `revision_of_decision_cycle_id`. The
predecessor must exist, belong to the same exact manager and managed portfolio,
be terminal and non-executable, and precede the revision chronologically. A
cycle cannot reference itself, create a lineage cycle, or have more than one
direct revision child; revision lineage is a linear chain. The new cycle reruns
the complete decision, so its recommendation action and ticker may differ. It
does not overwrite or add a second mutable attempt to the original cycle.

## Reviewer and human outcome

A deterministic failure always stops before an AI Reviewer invocation.
When deterministic validation passes and a Reviewer is configured, the
Reviewer receives the immutable recommendation, research, portfolio risk
snapshot, investment constitution, Manager Risk Constitution, and rule results.

The override trigger is specifically a `ReviewerResult` with disposition
`REQUEST_CHANGES` containing at least one finding whose severity is
`CRITICAL`. `CRITICAL` is a finding severity, not a ReviewerResult disposition.
For paper trading, a human may approve despite that result only by persisting
an explicit override flag and a dedicated non-empty override rationale linked
to the immutable ReviewerResult and human outcome. This permission does not
bypass a failed deterministic rule: deterministic failures cannot be approved
and are never routed through Reviewer override. Reviewer invocation occurs
only after deterministic validation passes. Reviewer override policy for any
future real-money workflow is unresolved and must not be inferred from the
paper policy.

## Execution-time revalidation

Approval does not freeze feasibility. Immediately before execution,
deterministic code must:

- rebuild the risk snapshot from current authoritative portfolio and price
  state;
- revalidate the exact approved target weight against the **journaled** Manager
  Risk Constitution version, artifact, loading source, and hash;
- apply the **currently active** exact System Safety Envelope version,
  artifact, loading source, and hash; and
- stop without execution if either layer fails.

Execution-time revalidation never changes the approved target. Any attempted
execution persists an immutable execution-policy check, whether it passes or
fails. That check records both policy identities: the journaled manager-policy
artifact/hash and the active execution-time safety-envelope artifact/hash. The
decision-time journal separately retains the exact safety-envelope
artifact/hash used for initial validation.

## Legacy behavior

Policy lineage is a discriminated reference:

```text
LegacyPolicyReference
  kind = "LEGACY_MECHANICAL"
  presentation_identity = "legacy-mechanical-v0.1.0"

CurrentPolicyReference
  kind = "CURRENT"
  investment_constitution_version / artifact / loading_source / hash
  system_safety_version / artifact / loading_source / hash
  manager_risk_version / artifact / loading_source / hash
```

Existing v0.1 journals reopen unchanged and remain authoritative historical
artifacts. The backward-compatible decoder may expose `LegacyPolicyReference`
in memory and through an API, but the marker is presentation identity only: it
does not fabricate an artifact, version, loading source, or hash. Re-encoding
an existing legacy journal omits all new persisted policy fields and preserves
its historical payload byte/semantic structure as required by the immutable
transition rules. New policy is never retroactively applied and old SQLite
documents are never rewritten merely to add the marker.

Policy activation occurs only after Lanes 1–5 are integrated and canonical
hash, migration, restart, validation, persistence, application/API, and
execution-time revalidation tests pass. After activation, every new production
cycle requires `CurrentPolicyReference` and cannot use the legacy marker.
Backward-compatible codec behavior is not permission to create new legacy
decisions.

## Multi-manager experimental fairness

Future manager comparisons hold these conditions equal:

- starting capital and immutable Cash Events;
- decision cadence, as-of cutoff, opportunity universe for the initial
  controlled experiment, and available provider evidence;
- price observations, execution conventions, fractional-share arithmetic,
  fees/slippage assumptions, and performance calculations;
- System Safety Envelope and human-approval protocol; and
- mechanical SPY benchmark methodology.

Managers do not see one another's recommendations before deciding. Deliberate
experimental variables are the manager's investment constitution, Manager Risk
Constitution, reasoning, cash preference, evidence requirements, and strategy
limits. Each manager eventually requires a separate managed portfolio,
history, decisions, approvals, and executions. The SPY benchmark remains a
separate deterministic portfolio.

## Runtime implementation sequence after Lane 0

1. **Lane 1 — typed policy domain:** artifact types, version compatibility,
   canonical hashing, evidence coverage, synchronized risk snapshot, and domain
   invariants.
2. **Lane 2 — two-layer validation:** immutable in-memory system/manager
   validation artifacts (including failures), Value v1 limits,
   unchanged-weight guarantees, and the CRM 25% regression. No durable policy
   persistence lands in this lane.
3. **Lane 3 — durable compatibility:** persist validation and exact policy
   artifacts, add legacy codec behavior, indexes, immutability, and restart
   tests.
4. **Lane 4 — application and API:** policy registry/selection, operator
   visibility, explicit linked revision command, and authoritative
   portfolio/manager research lineage.
5. **Lane 5 — execution revalidation:** current-state snapshot and immutable
   execution-policy checks.
6. **Lane 6 — AI Reviewer integration:** generalized manager contracts,
   Reviewer inputs, and durable paper-only critical override rationale. Risk
   policy may activate after Lanes 1–5 without an AI Reviewer adapter; until
   Lane 6 lands, production has no AI Reviewer result or override path.
7. **Lane 7 — multi-manager experiment:** separate managed portfolios and
   histories under shared experimental conditions.
