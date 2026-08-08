# Portfolio Manager Contract

## Purpose

A Portfolio Manager turns a portfolio context and a research packet into one structured investment recommendation.

It solves the software problem of translating evidence, portfolio constraints, and investment philosophy into a decision that can be validated, reviewed, and potentially approved downstream.

It is the layer that answers: "Given this portfolio, this evidence, and this philosophy, what should we do now?"

### What it is not responsible for

The Portfolio Manager does not:

- collect raw market data
- fetch or normalize research sources
- calculate deterministic risk checks
- place orders or execute trades
- maintain portfolio accounting state
- decide whether a human approval gate is satisfied
- compare itself to SPY mechanically
- invent missing evidence or fill gaps with guesses
- choose the software framework or LLM provider used to implement it

The manager may reason about evidence and portfolio state, but it does not own the surrounding workflow.

### Settled MVP decisions

For the first implementation:

- the manager is the Value Manager
- each decision cycle returns exactly one portfolio-level recommendation
- the manager may evaluate multiple supplied candidates, but it outputs only one recommendation
- the only action enum values are `BUY` and `HOLD`
- `SELL`, `TRIM`, `REBALANCE`, and replacement trades are deferred
- for a portfolio-level `HOLD`, `ticker` is `null` and `target_weight` is `null`
- `target_weight` is the allocation shape, expressed as a decimal from `0.0` to `1.0`
- a `BUY` requires `target_weight` to be strictly greater than `0`; `HOLD` uses `null`
- the deterministic portfolio engine converts `target_weight` into dollars and fractional shares
- `confidence_score` is an integer from `0` to `100`
- `confidence_score` reflects confidence in the decision given the supplied evidence, not probability of positive returns
- any categorical confidence label is derived downstream
- every recommendation requires `decision_rationale`
- `investment_thesis` is required for `BUY` and `null` for `HOLD`
- evidence consists of references to supplied research-packet evidence items
- the manager must not invent new evidence sources
- review triggers may be event-based or scheduled
- prior reviewer feedback is optional input and is not required in the first vertical slice
- deterministic downstream code owns schema validation, ticker eligibility, evidence-reference verification, numeric bounds, cash feasibility, position-size enforcement, concentration enforcement, dollar/share calculation, execution, and portfolio mutation
- the manager may discuss concentration implications but must not be treated as the enforcing authority

## Inputs

The Portfolio Manager should receive a fully structured request object. It must not depend on hidden state, ambient globals, or implicit conversation history.

The inputs below are the minimum contract surface. Future managers may accept additional fields, but they should not require unstructured prompt text to operate.

### 1. Portfolio state

What it is:

- current portfolio identifier
- cash balance
- current positions
- realized and unrealized gains if available
- per-position cost basis if available
- portfolio-level constraints already in force

Why it exists:

- the manager must know what is already owned before recommending a new action
- allocation decisions depend on current exposure, not just the target idea
- portfolio context is required to avoid duplicated or conflicting recommendations

Deterministic or AI-generated:

- deterministic input from portfolio accounting

### 2. Available cash

What it is:

- immediately deployable cash
- cash reserved for other obligations if applicable

Why it exists:

- a recommendation must be feasible within available capital
- sizing and action choice depend on capital availability

Deterministic or AI-generated:

- deterministic input from portfolio state

### 3. Existing holdings

What it is:

- ticker
- share count or units
- current market value if known
- entry price or cost basis if known
- thesis status if tracked
- holding age if tracked

Why it exists:

- the manager needs to know whether a recommendation is a new buy, add, trim, hold, or exit
- existing holdings shape concentration, diversification, and conviction decisions
- prior thesis context helps determine whether the original case is still intact

Deterministic or AI-generated:

- deterministic input from portfolio accounting

### 4. Research packet

What it is:

A structured evidence bundle for one or more candidate opportunities. It should contain the factual inputs the manager is allowed to use.

Typical contents may include:

- company and security identifiers
- business summary
- financial metrics
- valuation metrics
- recent filings or earnings highlights
- catalyst summary
- risks and counterarguments
- citations or evidence references
- freshness metadata
- source quality metadata

Why it exists:

- the manager needs evidence to justify a recommendation
- the manager should not fetch raw data itself
- structured evidence makes review and auditing possible

Deterministic or AI-generated:

- evidence content is deterministic input assembled by upstream systems
- interpretation of the packet may be AI-assisted

### 5. Market snapshot

What it is:

- current or recent price
- broad market context
- sector or industry context if available
- benchmark reference values if available
- volatility or regime indicators if available

Why it exists:

- valuation and timing depend on the current market context
- the manager may need to explain whether the opportunity is attractive relative to the market
- the manager needs enough context to judge whether a thesis is likely stale

Deterministic or AI-generated:

- deterministic input from market-data systems

### 6. Investment constitution

What it is:

The governing rules for this specific portfolio manager.

May include:

- philosophy definition
- mandate
- approved universe
- prohibited assets or actions
- concentration limits
- maximum position size
- minimum conviction thresholds
- required evidence standards
- benchmark expectation
- hold/trim/add/exit preferences

Why it exists:

- different managers must behave differently without changing the surrounding system
- the constitution makes the philosophy explicit and auditable
- the same manager class can be reused with different rules over time

Deterministic or AI-generated:

- deterministic configuration input

### 7. Previous decisions

What it is:

- prior recommendation for the same ticker
- prior recommendation for related holdings if relevant
- prior thesis summary
- prior invalidation points
- prior review feedback
- prior approval or rejection outcome if applicable

Why it exists:

- the manager should know whether it is continuing, revising, or reversing a prior thesis
- consistency across runs matters for auditability
- review feedback should influence future recommendations

Deterministic or AI-generated:

- deterministic input from decision history

### 8. Review feedback, if available

What it is:

- critique from prior review stages
- missing evidence flags
- methodology concerns
- prior validation failures

Why it exists:

- the manager should be able to incorporate known weaknesses from earlier cycles
- repeated mistakes should not be regenerated unchanged

Deterministic or AI-generated:

- deterministic input from prior review systems

For the MVP, this input is optional.

### 9. Decision context

What it is:

- decision timestamp
- portfolio run identifier
- intended horizon if known
- whether the run is routine, event-driven, or re-evaluation driven

Why it exists:

- temporal context matters for evidence freshness and re-review logic
- the manager should know whether this is a new idea or a maintenance decision

Deterministic or AI-generated:

- deterministic input from the orchestrator

## Output

The Portfolio Manager must return exactly one structured recommendation object.

The object must be machine-readable and suitable for downstream validation and review.

The recommendation must support a HOLD outcome.

### Required top-level fields

#### `action`

- Purpose: states the recommended portfolio action.
- Required: yes.
- Allowed values: `BUY`, `HOLD`.
- Deterministic or AI-generated: AI-generated recommendation, constrained by deterministic enum values.

Why it exists:

- downstream systems need a single action to route
- validation rules depend on the action type

#### `ticker`

- Purpose: identifies the security the recommendation applies to.
- Required: yes for `BUY`; `null` for `HOLD`.
- Deterministic or AI-generated: AI-selected from the candidate set provided in the research packet.

Why it exists:

- downstream systems need a security identifier
- the output must be unambiguous

#### `allocation`

- Purpose: states the intended capital or position change.
- Required: yes.
- Shape: `target_weight`.
- Range: decimal from `0.0` to `1.0`.
- Meaning: proposed percentage of total portfolio value.
- Deterministic or AI-generated: AI-proposed, then normalized deterministically downstream if needed.

Why it exists:

- sizing is part of the recommendation
- risk checks need a concrete magnitude

#### `thesis`

- Purpose: explains the core investment case in concise structured form.
- Required: yes for `BUY`; `null` for `HOLD`.
- Deterministic or AI-generated: AI-generated.

Why it exists:

- reviewers need to understand the rationale
- future re-review needs a stable thesis summary

#### `valuation`

- Purpose: captures the valuation view behind the recommendation.
- Required: yes when the action is directional; may be a brief null-equivalent explanation for HOLD if valuation is not the reason.
- Deterministic or AI-generated: primarily AI-generated from evidence, but may include deterministic referenced metrics.

Why it exists:

- valuation is a central part of portfolio reasoning
- the manager must not hide valuation assumptions inside free text

#### `risks`

- Purpose: lists the main risks, uncertainties, and adverse scenarios.
- Required: yes.
- Deterministic or AI-generated: AI-generated, grounded in evidence.

Why it exists:

- every recommendation should be paired with a downside view
- reviewers need to know what would break the idea

#### `confidence`

- Purpose: expresses the manager’s confidence in the recommendation.
- Required: yes.
- Shape: `confidence_score`.
- Range: integer from `0` to `100`.
- Meaning: confidence in the decision given the supplied evidence, not probability of positive returns.
- Any categorical label is derived downstream.
- Deterministic or AI-generated: AI-generated, with deterministic bounds.

Why it exists:

- confidence supports triage and review thresholds
- low-confidence ideas may still be useful, but they should be visible as such

#### `evidence`

- Purpose: cites the specific evidence used.
- Required: yes.
- Shape: structured references to supplied research-packet evidence items.
- Deterministic or AI-generated: evidence references are deterministic; evidence interpretation is AI-generated.

Why it exists:

- important claims must be traceable
- the system needs auditable source grounding

#### `why_not_spy`

- Purpose: explains why the recommendation is preferable to simply buying SPY.
- Required: yes.
- Deterministic or AI-generated: AI-generated.

Why it exists:

- this repository treats SPY as the mechanical benchmark
- a manager must justify active risk with explicit expected benefit

#### `thesis_invalidation`

- Purpose: states what evidence or market movement would cause the thesis to fail.
- Required: yes.
- Deterministic or AI-generated: AI-generated.

Why it exists:

- invalidation criteria make the thesis testable
- future review and rebalancing logic can use it

#### `review_triggers`

- Purpose: defines events or conditions that should cause re-review.
- Required: yes.
- Shape: event-based and/or scheduled triggers.
- Deterministic or AI-generated: AI-generated, though it may reference deterministic thresholds.

Why it exists:

- the system needs explicit triggers for future reassessment
- good portfolio management is ongoing, not one-shot

### Recommended additional fields

The contract may also include the following fields if they are useful to downstream validation:

- `rationale_structure`
- `position_role`
- `time_horizon`
- `expected_return_case`
- `bear_case`
- `base_case`
- `source_ids`
- `notes_for_reviewer`
- `revision_of`

These should remain optional unless the first implementation proves otherwise.

### Required conceptual fields for the MVP

For the first implementation, the recommendation object should conceptually include:

- `action`
- `ticker`
- `target_weight`
- `decision_rationale`
- `investment_thesis`
- `valuation`
- `risks`
- `confidence_score`
- `evidence`
- `why_not_spy`
- `thesis_invalidation`
- `review_triggers`

`decision_rationale` is required for every recommendation. `investment_thesis` is required only when `action` is `BUY`.

## Field Guidance

### Required vs optional

For the first version of the contract:

- `action` is always required
- `confidence_score` is always required
- `evidence` is always required
- `why_not_spy` is always required
- `thesis_invalidation` is always required
- `review_triggers` is always required
- `decision_rationale` is always required
- `investment_thesis` is required for `BUY`
- `ticker` is required for `BUY`
- `target_weight` is required and strictly greater than `0` for `BUY`
- `ticker` is `null` for `HOLD`
- `target_weight` is `null` for `HOLD`

### AI-generated vs deterministic

The manager may generate the reasoning fields, but it must not fabricate input data.

The following should be deterministic inputs from upstream systems:

- portfolio state
- available cash
- existing holdings
- research packet contents
- market snapshot
- investment constitution
- previous decisions

The following should be AI-generated by the Portfolio Manager:

- action selection
- decision_rationale
- investment_thesis
- valuation interpretation
- risk framing
- confidence_score
- why not SPY
- thesis invalidation
- review triggers

The following should be deterministic wherever possible in downstream code:

- schema validation
- required-field checks
- numeric bounds
- allocation feasibility
- prohibited-action checks
- concentration checks

## Responsibilities

### The manager SHOULD

- interpret the supplied research packet in light of the investment constitution
- compare the opportunity against the current portfolio state
- return one and only one recommendation
- evaluate multiple supplied candidates when present and choose one
- explain the recommendation clearly enough for review
- ground claims in the supplied evidence
- discuss concentration implications in the recommendation when relevant
- state what would make the thesis wrong
- state what should trigger future review
- support HOLD when no attractive opportunity exists
- distinguish between new ideas and revisions to existing positions
- remain philosophy-consistent across runs
- surface low confidence when evidence is thin or conflicting
- make the active-risk case against SPY explicit

### The manager MUST NOT

- mutate portfolio state
- place orders
- bypass risk validation
- assume access to data it was not given
- invent missing facts
- rely on hidden memory as a source of truth
- output multiple conflicting recommendations
- silently ignore the investment constitution
- optimize for short-term prediction at the expense of the stated mandate
- replace deterministic checks with reasoning text
- claim certainty when evidence does not support it
- present itself as an oracle or guarantee outcomes
- invent new evidence sources
- enforce concentration limits itself
- treat concentration discussion as a substitute for deterministic enforcement

## Failure Modes

The manager must handle failure cases explicitly rather than masking them.

### When evidence conflicts

If the evidence is mixed or contradictory:

- the recommendation should acknowledge the conflict
- the confidence should decrease
- the risks section should name the conflict directly
- the recommendation may resolve to HOLD if the conflict is material

The manager should not cherry-pick supportive evidence while omitting strong counterevidence.

### When insufficient information exists

If the manager does not have enough evidence to make a justified recommendation:

- it should return HOLD or a clearly low-conviction recommendation only if the constitution allows that behavior
- it should identify which input is missing or insufficient
- it should make the limitation visible in the output

The manager must not infer missing facts as if they were known.

### When no attractive investment exists

If nothing meets the mandate:

- HOLD is a valid and expected outcome
- the output should say why no candidate clears the bar
- the review triggers should still describe what future change would justify reconsideration

This is a successful result, not a failure.

### When confidence is low

If confidence is low:

- the manager should state that explicitly
- it should avoid overstating conviction
- it should prefer HOLD over forced action unless the constitution says otherwise
- downstream review may require tighter scrutiny

Low confidence is acceptable if clearly labeled.

### When no attractive candidate exists

If multiple supplied candidates are evaluated and none are attractive enough:

- the manager should return `HOLD`
- `ticker` should be `null`
- `target_weight` should be `null`
- `decision_rationale` should explain why none of the candidates cleared the bar
- the output should still include review triggers

This is a valid outcome, not a failure.

## Open Questions

These items are intentionally unresolved and should not be invented in this document.

- What is the exact internal shape of `decision_rationale`?
- What is the exact structure of each `valuation` and `risks` subfield?
- What is the canonical evidence-item schema beyond the required reference fields?
- What is the exact input schema for candidate evaluation when multiple candidates are supplied?
- Should `why_not_spy` be a free-form narrative or a structured set of reasons?
- What are the exact event types and schedule types allowed for `review_triggers`?
- What manager-specific constitution should the first Value Manager use?
- How should the first implementation represent candidate priority or ranking internally, if needed?
