# ADR-008: System Safety and Advisory Manager Risk Constitutions

**Date:** 2026-08-22
**Amended:** 2026-08-23
**Status:** Accepted

## Motivation

The first live Research v2 recommendation proposed BUY CRM at a 25% target
weight. Deterministic validation established that the proposal was mechanically
feasible, while human and adversarial review found that its concentration was
not well supported by the available evidence. The initial version of this ADR
responded by making Value-specific sizing preferences deterministic rejection
rules.

That would distort the intended manager competition. Value, Growth, and
Conservative managers must be able to exhibit materially different
concentration, turnover, and cash behavior. Deterministic platform safety must
not become the investment committee.

## Decision

Adopt three conceptually distinct layers:

1. the universal **System Safety Envelope**, which is hard deterministic
   enforcement;
2. a versioned **Manager Risk Constitution**, which is advisory strategy and
   risk personality; and
3. an optional explicit **Manager or Portfolio Mandate**, which may contain
   hard constraints for a future deliberately constrained portfolio but is not
   active in the current experiment.

The manager proposes one immutable target weight. No downstream component
normalizes, caps, or silently resizes it. Deterministic code validates universal
mechanical safety and converts a passing target to notional and quantity.
Manager-constitution observations inform the manager, AI Reviewer, human
operator, and durable audit history, but they do not make a mechanically valid
trade non-executable.

Both active artifacts are repository-owned, typed, independently versioned,
canonically serialized, and content-hashed. A Manager Risk Constitution declares
compatible investment-constitution version/hash pairs. Historical decisions
retain the exact artifacts used. Reusing a version for changed content is
invalid.

## Universal hard enforcement

The System Safety Envelope owns supported actions and instruments, long-only
funded mechanics, exact `SecurityIdentity` and currency, attributable price and
research provenance, chronology, cash feasibility, non-negative Decimal-safe
state, positive executable quantity, immutable lineage, human approval, HOLD
and failed/rejected/expired non-execution, and managed/benchmark separation.

For the current paper experiment, it has no concentration ceiling below 100%.
A mechanically valid long-only target up to 100% may pass. Real-money
catastrophic concentration policy remains deferred.

## Advisory manager risk personality

The Manager Risk Constitution describes:

- risk posture and normal sizing guidance;
- concentration, turnover, rotation, and cash preferences;
- evidence expected for unusual allocations;
- deviations that require explicit explanation;
- balance-sheet, liquidity, durability, and missing-data concerns; and
- the rubric the AI Reviewer should apply to that manager.

For Value v2, 5–10% is normal starter-position guidance only. It creates no
minimum or maximum and carries no execution authority. The former 10% baseline
initial, 15% enhanced initial, 25% total single-name, and five-percentage-point
add ceilings are not active deterministic rules. Confidence remains descriptive
and cannot authorize or bypass System Safety.

Evidence bands describe attributable evidence coverage and maturity. They do
not authorize portfolio weights. `BASELINE_RESEARCH_V2` remains the currently
reachable coverage profile, and richer durability evidence remains undefined
and unreachable. Missing values remain explicit `MissingData`, never zero.

The AI Reviewer critiques consistency with the selected manager personality,
the sufficiency of evidence for the proposed allocation, contradictions, and
unjustified deviations. It never resizes the recommendation. An adverse
Reviewer result is advisory for the current paper experiment: the human may
reject, request a new explicitly linked decision cycle, or approve with the
durable rationale required by the human-outcome contract. No Reviewer or human
may bypass System Safety.

## Optional future mandates

Some future portfolios may have explicit hard mandates, such as prohibited
asset classes, contractual cash reserves, or concentration restrictions. Such
constraints must be deliberately selected, typed, versioned, content-hashed,
and visibly distinct from manager personality. This ADR does not introduce a
mandate runtime or make any mandate active for Value, Growth, or Conservative.

## Execution and revision lineage

Reconsideration never overwrites a recommendation. It requires a new decision
cycle linked through `revision_of_decision_cycle_id` to an earlier terminal
cycle for the same manager and managed portfolio.

Immediately before execution, deterministic code rebuilds current portfolio and
price state and revalidates the unchanged approved target against the currently
active System Safety Envelope. It also verifies the journaled investment and
Manager Risk Constitution identities for immutable lineage. Advisory guidance
is not reinterpreted as an execution veto. A future explicit hard mandate would
require its own approved execution-time contract.

## Versioning and legacy artifacts

`value-risk-v1.0.0` retains its original hard-sizing content and hash. It was
never activated in production and must not be silently redefined. Because the
loaded Value methodology text also changed, `value-v1.0.0` remains frozen at
`docs/value-manager-constitution.md`; the amended methodology is
`value-v2.0.0` at `docs/value-manager-constitution-v2.md`. The new advisory
`value-risk-v2.0.0` declares compatibility only with that exact v2 investment
artifact and has a new schema identity and content hash.

Existing v0.1 journals remain immutable legacy mechanical validations exposed
through the presentation-only `LegacyPolicyReference`; no artifact, version, or
hash is fabricated. The new advisory architecture is not active in production
until its later persistence/application lanes are explicitly approved.

## Multi-manager experimental fairness

Value, Growth, and Conservative use separate managed portfolios and histories.
Starting capital, Cash Events, evidence cutoff, opportunity universe, provider
inputs, cadence, System Safety, execution arithmetic, approval procedure, and
benchmark methodology are held equal. Concentration, turnover, cash preference,
and investment reasoning are deliberate experimental variables.

The Reviewer applies the same procedure but evaluates each manager against its
own constitution. It must not impose one generic diversification philosophy on
all managers.

## Consequences

- System Safety remains deterministic and non-bypassable.
- Manager personalities remain observable rather than normalized away.
- Extreme concentration can be proposed and, if mechanically safe and human
  approved, executed unchanged.
- Strategy deviations are durable and reviewable without becoming hidden hard
  limits.
- Typed artifacts, hashes, compatibility references, evidence assessments,
  synchronized snapshots, and audit lineage remain useful.
- Optional hard mandates require a later explicit architecture decision.

## Clarifications to earlier decisions

- ADR-002 continues to own investment methodology. Manager Risk Constitutions
  add versioned advisory risk personality rather than deterministic sizing law.
- ADR-003's deterministic reproducibility applies to System Safety evaluation
  for the same recommendation and authoritative inputs.
- The manager-intent boundary includes the proposed target weight; deterministic
  systems validate and convert it but never choose a replacement weight.

## Alternatives considered

- **Universal sub-100% concentration ceiling:** rejected for the current paper
  experiment because it encodes one investment philosophy as platform safety.
- **Manager-specific hard sizing cage:** rejected because it suppresses the
  strategy differences the experiment is intended to observe.
- **Automatic deterministic capping:** rejected because it changes manager
  intent and breaks recommendation/execution consistency.
- **Confidence-based authority:** rejected because confidence is uncalibrated
  and cannot cure evidence or safety defects.
- **Untyped prompt-only personality:** rejected because strategy identity and
  reviewer expectations must remain versioned, reproducible, and auditable.

## Follow-up

Revise the Lane 1 typed artifact to publish `value-risk-v2.0.0`, then salvage
only the System Safety and audit portions of the frozen Lane 2 diff. Do not
activate persistence, application selection, Reviewer calls, or execution-time
policy behavior without separate approval.
