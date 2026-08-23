# ADR-008: Two-Layer Manager Risk Constitutions

**Date:** 2026-08-22
**Status:** Accepted

## Motivation

The first live Research v2 recommendation proposed BUY CRM at a 25% target
weight. Existing deterministic validation correctly preserved identity,
chronology, cash feasibility, and weight-to-quantity arithmetic, but it had no
manager-specific initial-position or concentration policy. The validation pass
therefore established mechanical feasibility, not that 25% was justified by
the Value strategy or its evidence.

One universal concentration policy would incorrectly force Value, Growth /
Tech, and Conservative managers to share an investment philosophy. Letting an
LLM confidence score or an automatic cap choose the executable weight would
blur the boundary between manager intent and deterministic policy.

## Decision

Adopt two deterministic policy layers:

1. a minimal universal **System Safety Envelope** for supported mechanics,
   state integrity, provenance, chronology, cash feasibility, immutable
   lineage, approval, and execution safety; and
2. a versioned **Manager Risk Constitution** for strategy-specific sizing,
   concentration, evidence, cash-deployment, and diversification policy.

The manager proposes an immutable target weight. Deterministic validation
evaluates that weight unchanged and then converts it to notional and quantity;
it never normalizes, caps, or silently resizes it. A policy failure is journaled
with the original recommendation, creates no validated trade, and is
non-executable. Reconsideration requires a new explicitly linked decision
cycle, never an automatic retry.

Both layers are repository-owned typed artifacts with independent semantic
version namespaces, canonical typed serialization, exact immutable snapshots,
repository loading sources, and SHA-256 content hashes. Manager Risk
Constitutions also declare compatible investment-constitution version/hash
pairs. Historical decisions retain the exact safety and manager-policy
artifacts under which they were evaluated. Reusing a version for changed
content is invalid.

For the current paper experiment, the System Safety Envelope has no universal
concentration ceiling below 100%. A real-money catastrophic ceiling is
deferred. Confidence is descriptive only and has no deterministic sizing
authority.

The first Value-specific policy is:

- typical starter guidance: 5–10%;
- baseline Research v2 maximum initial position: 10%;
- enhanced-evidence maximum initial position: 15%;
- maximum total single-name target: 25%;
- maximum one-cycle add: 5 percentage points;
- no minimum cash reserve; and
- no deterministic leverage or current-ratio thresholds yet.

These ceilings are inclusive. Initial means no positive-quantity position for
the exact `SecurityIdentity`; add means a positive-quantity exact-identity
position. A BUY must increase exposure. Baseline and enhanced initial targets
must be at most 10% and 15%, every target at most 25%, and each add delta
(`proposed target - synchronized current exact-identity weight`) at most five
percentage points. Exactly-equal boundaries pass. The 5–10% starter range is
non-enforceable guidance and creates no minimum.

`BASELINE_RESEARCH_V2` is the only currently reachable evidence band. It
requires exact identity, current/reused-current coverage for OVERVIEW and all
four statements, and evaluation of the locked 16 derived metrics. Each metric
retains either its typed value or explicit `MissingData`; missing values are
never required to become numeric and are never interpreted as zero. Richer
enhanced/durability evidence is deferred and unreachable.

During paper trading only, a human may override a `ReviewerResult` disposition
of `REQUEST_CHANGES` containing at least one `CRITICAL`-severity finding. The
human outcome stores an explicit override flag and dedicated non-empty durable
rationale linked to that immutable result. Human review cannot override a
failed deterministic safety or manager-policy rule, and Reviewer invocation
occurs only after deterministic validation passes.

Before execution, the system rebuilds current portfolio/valuation inputs and
revalidates the exact target against the journaled Manager Risk Constitution
artifact/hash and the currently active exact System Safety Envelope
artifact/hash. The execution check persists both identities. It does not
change the approved target.

Existing v0.1 artifacts remain immutable legacy mechanical validations and
reopen through a discriminated presentation-only legacy reference without a
fabricated artifact, version, or hash. Re-encoding omits new policy fields and
preserves historical payload structure. Policy activation requires Lanes 1–5
plus migration/restart tests; new cycles may not use the legacy reference after
activation.

## Consequences

- Mechanical validity is explicitly distinct from manager-policy validity.
- Future managers can adopt materially different strategy limits while sharing
  the same platform safety rules and arithmetic.
- Invalid sizing cannot be made executable by silent resizing, confidence, AI
  Reviewer output, or human override.
- Decisions persist exact policy identity and reproducible rule inputs.
- Execution can stop safely when portfolio state, prices, or active system
  safety change after approval.
- Additional typed artifacts, snapshots, persistence fields, API fields, and
  backward-compatible decoding are required in later implementation lanes.
- Multi-manager comparisons require separate managed portfolios and histories
  under equal funding, data, timing, execution, approval, and performance
  conditions. SPY remains a separate deterministic benchmark.
- Policy selection is keyed by exact managed portfolio identity and manager
  type with configured investment/risk versions and hashes. Missing,
  ambiguous, incompatible, or implicit-latest selection fails before manager
  invocation.

## Clarifications to earlier decisions

- ADR-002's portfolio constitution remains the investment-methodology and
  deployment-philosophy contract. This ADR separates machine-enforced manager
  risk policy from that prose artifact.
- ADR-003's “same deterministic result” applies only when recommendation,
  portfolio and valuation snapshot, price observations, evidence assessment,
  exact System Safety Envelope artifact/hash, and exact Manager Risk
  Constitution artifact/hash are identical.
- ADR-003's manager-intent boundary includes the proposed target weight.
  Deterministic systems validate and convert it; they do not choose a
  replacement weight.

## Revision lineage

An invalid recommendation may be reconsidered only through a new cycle whose
`revision_of_decision_cycle_id` points to an existing, earlier, terminal,
non-executable cycle for the same manager and managed portfolio. Revision
lineage is linear: no self-reference, cycles, or more than one direct child.
The complete decision reruns, so action and ticker may differ from the
predecessor.

## Canonical identity

Lane 1 must normatively implement canonical UTF-8 JSON before publishing an
artifact: lexicographically sorted object keys, no insignificant whitespace,
stable enum strings, defaults materialized, optional fields explicit as
`null`, ordered arrays preserved, and loading source/hash excluded from the
hashed payload. Finite Decimals use one normalized non-exponent fixed-point
string (no redundant zeros, `"0"` for either signed zero), so numerically
equivalent Decimals hash identically. All strings are normalized to Unicode
NFC and lone surrogates/non-scalar input are rejected. Object keys sort by the
NFC Unicode scalar-value sequence. JSON escapes `"` as `\"` and `\` as `\\`;
U+0008/U+0009/U+000A/U+000C/U+000D use `\b`/`\t`/`\n`/`\f`/`\r`, and other
U+0000–U+001F controls use lowercase `\u00xx`. Every other scalar is emitted
literally as UTF-8. SHA-256 is lowercase hexadecimal. This same canonical
contract applies to persisted investment-constitution artifact hashes.

## Alternatives considered

- **One universal sub-100% concentration ceiling:** rejected for the current
  paper experiment because it would encode a strategy preference as platform
  safety.
- **Automatic deterministic capping:** rejected because it changes manager
  intent and makes the thesis, confidence, and executable trade inconsistent.
- **Confidence-based sizing:** rejected for v1 because model confidence is
  uncalibrated and descriptive.
- **Policy only in prose or prompts:** rejected because hard limits must be
  typed, versioned, deterministic, and reproducible.
- **Retroactively apply policy to v0.1 journals:** rejected because historical
  artifacts are immutable and did not contain these inputs.

## Follow-up

Implement the sequenced lanes in [Manager Risk Constitution Contract](../manager-risk-constitution.md), beginning with typed domain artifacts only after explicit approval for Lane 1.
