# Portfolio Domain Model

## Purpose

This document defines the deterministic portfolio and trade domain for the first vertical slice.

The model exists to represent portfolio state, value, contributions, and approved buy-only trade flow in a way that is auditable, testable, and independent of any LLM provider or application framework.

It is the mechanical layer below the portfolio manager.

## Settled Decisions

For the first vertical slice:

- the only supported trade action is `BUY`
- `HOLD` is supported as a decision outcome, but it does not change portfolio state
- there is no `SELL`, `TRIM`, `REBALANCE`, options, leverage, margin, tax logic, or real brokerage execution
- portfolio state must be deterministic and auditable
- cash, quantities, prices, and weights must never be invented by an LLM
- authoritative calculations use decimal-safe arithmetic
- money and prices support at least 4 decimal places internally
- target weights support up to 6 decimal places
- fractional share quantities support up to 8 decimal places
- binary floating-point values must not be used for authoritative portfolio calculations
- position `total_cost_basis` is authoritative; per-share average cost basis is a derived informational value
- fractional shares are supported
- an approved `target_weight` is converted downstream into a dollar amount and a quantity
- the SPY benchmark uses the same starting capital and contribution schedule as the live portfolio
- the portfolio and SPY benchmark use the same valuation timestamp and price convention
- proposed trades remain distinct from validated trades and executed trades
- the first vertical slice uses one simulated fill per executed trade
- the simulation uses the next available regular-session market closing price following approval
- `constitution_version` is a required stable semantic-style string such as `value-v1.0.0`
- a constitution content hash may be added later for stronger auditability, but it is deferred from the MVP
- every state-changing event must be traceable to a decision cycle
- validation ownership belongs to deterministic code, not the portfolio manager

## Working Assumptions

These assumptions keep the model implementation-oriented without choosing storage or frameworks:

- money is represented with decimal-safe monetary values
- share quantities are represented with decimal-safe quantities
- a portfolio can hold multiple positions across multiple securities
- a contribution is an explicit one-time event
- a valuation snapshot is a point-in-time view used for reporting and validation
- a trade proposal is derived from a portfolio manager recommendation plus deterministic conversion
- a validated trade is a trade that has passed deterministic checks but has not yet executed
- an executed trade is a final, immutable fact in portfolio history
- benchmark tracking should use the same contribution events and valuation timing as the live portfolio
- benchmark tracking and live portfolio valuation use the same approved price source and convention within a decision cycle

## Core Concepts

### 1. Portfolio

A Portfolio is the deterministic container for positions, cash, valuation snapshots, contributions, and trade history.

### Conceptual fields

- `portfolio_id`
- `portfolio_name`
- `base_currency`
- `created_at`
- `status`
- `starting_capital`
- `current_cash_balance`
- `current_market_value`
- `current_total_value`
- `decision_cycle_id` on state-changing updates

### Why it exists

- it is the top-level owned state for the paper portfolio
- it provides the source of truth for positions and cash
- it supports valuation and comparison over time

### Invariants

- a portfolio has one base currency
- a portfolio has exactly one current deterministic state at a time
- portfolio value is derived, not invented
- every state change references a decision cycle or other approved source of change

### 2. Cash Balance

Cash Balance is the portfolio’s liquid cash state in the base currency.

### Conceptual fields

- `cash_balance_id`
- `portfolio_id`
- `amount`
- `currency`
- `as_of_timestamp`
- `source_event_id`

### Why it exists

- cash determines what can be bought
- cash is the bridge between contributions and trade execution
- deterministic cash state is required for validation

### Invariants

- cash is never negative in the first vertical slice
- cash changes only through contributions, trade validation, or trade execution
- cash is always expressed in the portfolio base currency

### 3. Position

A Position is the canonical ownership record for one security within a portfolio.

### Conceptual fields

- `position_id`
- `portfolio_id`
- `security_id`
- `ticker`
- `security_type`
- `exchange`
- `quantity`
- `quantity_precision`
- `fractional_quantity_supported`
- `total_cost_basis`
- `average_cost_basis` (derived informational value)
- `cost_basis_currency`
- `market_price`
- `market_value`
- `unrealized_pnl`
- `open_date`
- `last_updated_at`

### Why it exists

- positions are the core representation of ownership
- current quantity and authoritative total cost basis are needed for valuation and reporting
- market value and unrealized P&L are derived from deterministic price snapshots

### Invariants

- quantity is never negative
- a position belongs to exactly one portfolio
- a position refers to exactly one security
- market value is derived from quantity and price
- the model supports fractional share quantities where the security allows it
- quantity uses decimal-safe arithmetic and is rounded only by deterministic rules
- total cost basis is authoritative; average cost per share is derived for reporting only

### 4. Security Identity

Security Identity is the canonical identifier set for a security or tradable instrument.

### Conceptual fields

- `security_id`
- `ticker`
- `security_type`
- `company_name`
- `exchange`
- `currency`

### Why it exists

- portfolio state must be tied to a stable security identity
- identifiers prevent ticker ambiguity across venues or instrument types
- trade validation needs a canonical security reference

### Invariants

- security identity is deterministic input, not generated by a model
- one position maps to one security identity
- if an identity field is missing, it remains explicitly missing

### 5. Portfolio Valuation Snapshot

A Portfolio Valuation Snapshot is a point-in-time view of portfolio value derived
from supplied, source-attributed price observations rather than stored position prices.

### Conceptual fields

- `valuation_snapshot_id`
- `portfolio_id`
- `as_of_timestamp`
- `cash_balance`
- `positions_market_value`
- `total_value`
- `benchmark_total_value`
- `source_provider_identity`
- `market_date`
- `source_price_timestamp`
- `currency`
- `price_convention`
- `decision_cycle_id` if applicable

### Why it exists

- it supports reporting and auditability
- it provides the reference value for `target_weight` conversion
- it aligns portfolio and benchmark comparisons
- it records the approved source/provider identity, market date, timestamp, currency, and price convention used for both portfolio and benchmark

### Invariants

- snapshot values are derived from deterministic state and prices
- a snapshot must include the timestamps used to derive the valuation
- a snapshot is immutable once recorded
- portfolio and benchmark snapshots use the same valuation timestamp and price convention
- portfolio and benchmark snapshots use the same approved source/provider identity within a decision cycle

### 6. Contribution

A Contribution is an external increase in portfolio cash.

### Conceptual fields

- `contribution_id`
- `portfolio_id`
- `amount`
- `currency`
- `effective_at`
- `received_at`
- `source`
- `decision_cycle_id` if linked to a run
- `is_one_time_event`

### Why it exists

- contributions establish the cash available for buying securities
- contributions must be auditable and reproducible
- SPY should receive the same contribution schedule as the portfolio

### Invariants

- a contribution increases cash
- a contribution does not itself create positions
- a contribution is not a trade
- contribution records are immutable after creation
- a contribution is a one-time event in the first vertical slice

### 7. Trade Proposal

A Trade Proposal is a deterministic candidate trade derived from a portfolio manager recommendation.

### Conceptual fields

- `trade_proposal_id`
- `decision_cycle_id`
- `portfolio_id`
- `security_id`
- `ticker`
- `action`
- `target_weight`
- `proposed_notional_amount`
- `proposed_quantity`
- `price_source_timestamp`
- `reason_reference`
- `status`

### Why it exists

- it preserves the distinction between recommendation and executable trade state
- it captures deterministic conversion from weight to dollars and quantity
- it is the first step toward validation
- `proposed_quantity` is rounded down to 8 decimal places
- rounding must never cause available cash to be exceeded

### Invariants

- a trade proposal is not executed
- a trade proposal may be rejected by validation
- a trade proposal for this MVP always represents a `BUY`
- `target_weight` comes from the approved recommendation, not from an LLM-generated conversion
- quantity calculation rounds down to 8 decimal places

### 8. Validated Trade

A Validated Trade is a trade proposal that has passed deterministic checks.

### Conceptual fields

- `validated_trade_id`
- `trade_proposal_id`
- `decision_cycle_id`
- `portfolio_id`
- `security_id`
- `action`
- `validated_notional_amount`
- `validated_quantity`
- `validation_status`
- `validation_timestamp`
- `validation_results`

### Why it exists

- it separates approval of the trade shape from execution
- it creates a clear deterministic checkpoint
- it provides a reviewable record of what passed validation

### Invariants

- validation is deterministic
- a validated trade still may not be executed
- a validated trade must preserve the original proposal lineage

### 8a. Rejected Proposal Validation Record

A Rejected Proposal Validation Record captures the failed deterministic checks for a trade proposal.

### Conceptual fields

- `proposal_id`
- `decision_cycle_id`
- `validation_status`
- `rule_id`
- `reason`
- `actual_value` if applicable
- `allowed_threshold` if applicable
- `validated_at`

### Why it exists

- it preserves why a proposal was rejected
- it makes validation outcomes auditable
- it keeps the failed proposal lineage separate from executed state

### Invariants

- every rejection is persisted with the same deterministic rule identifiers used for validation
- a rejected proposal does not become a validated trade
- rejected validation records are immutable

### 9. Executed Trade

An Executed Trade is a finalized portfolio event representing a completed buy.

### Conceptual fields

- `executed_trade_id`
- `validated_trade_id`
- `decision_cycle_id`
- `portfolio_id`
- `security_id`
- `action`
- `executed_quantity`
- `execution_price`
- `source_provider_identity`
- `market_date`
- `currency`
- `price_convention`
- `executed_notional`
- `executed_at`
- `execution_source`

### Why it exists

- it is the authoritative record of what actually happened
- it updates positions, cash, and history
- it anchors audit trails and future cost basis calculations
- it records exactly one simulated fill in the first vertical slice
- it records the approved source/provider identity, market date, currency, and price convention for the fill

### Invariants

- execution is immutable after recording
- execution is downstream of validation
- executed state must be traceable back to a decision cycle
- each executed trade has exactly one `execution_price` and one `executed_at`
- each executed trade has one approved source/provider identity, market date, currency, and price convention

### 10. Cost Basis

Cost Basis is the deterministic total ownership cost used for reporting unrealized gains and future comparisons. Per-share average cost is derived for informational reporting using the deterministic domain-owned Decimal context/policy defined by the implementation.

### Conceptual fields

- `cost_basis_id`
- `position_id`
- `total_cost_basis`
- `average_cost_per_share` (derived informational value)
- `currency`
- `calculated_at`
- `method`

### Why it exists

- authoritative total cost basis supports unrealized P&L reporting
- it allows trade fills to update position economics deterministically

### Invariants

- total cost basis is derived from executed trades
- average cost per share is derived from total cost basis and quantity for informational reporting
- cost basis does not come from a manager recommendation
- cost basis changes only through deterministic update rules

### 11. Fractional Shares

Fractional Shares are decimal quantities representing partial ownership.

### Conceptual fields

- `quantity`
- `minimum_increment`
- `precision`
- `supported`

### Why it exists

- the first slice explicitly supports fractional share buying
- fractional support makes `target_weight` conversion practical for small accounts

### Invariants

- fractional quantities must use decimal-safe arithmetic
- a security must declare whether fractional shares are supported
- validation must enforce security-specific quantity precision

### 12. Benchmark Portfolio

The Benchmark Portfolio is the SPY comparison portfolio tracked mechanically alongside the live portfolio.

### Conceptual fields

- `benchmark_portfolio_id`
- `benchmark_symbol`
- `starting_capital`
- `contribution_schedule`
- `current_value`
- `current_shares`
- `as_of_timestamp`

### Why it exists

- the project requires SPY as a mechanical baseline
- the benchmark must use the same starting capital and contribution schedule
- benchmark tracking supports relative performance analysis

### Invariants

- the benchmark is updated mechanically, not by the manager
- the benchmark receives the same contribution schedule as the live portfolio
- benchmark state is distinct from live portfolio state

### 13. Portfolio History

Portfolio History is the append-only record of changes to portfolio state.

### Conceptual fields

- `history_event_id`
- `portfolio_id`
- `event_type`
- `event_timestamp`
- `decision_cycle_id`
- `related_entity_id`
- `before_state`
- `after_state`
- `source`
- `research_packet_ids`
- `cited_evidence_ids`

### Why it exists

- it provides a durable audit trail
- it enables reconstruction of portfolio state over time
- it links every state-changing event to a decision cycle
- it stores only research packet and cited evidence references

### Invariants

- history is append-only
- history events are immutable
- every state-changing event must be traceable to a decision cycle
- full research packets are not duplicated into portfolio history
- history stores only `research_packet_ids` and `cited_evidence_ids`

### 14. Decision-Cycle Linkage

Decision-cycle linkage connects portfolio events back to the manager recommendation that triggered them.

### Conceptual fields

- `decision_cycle_id`
- `manager_type`
- `research_batch_id`
- `research_packet_ids`
- `portfolio_id`
- `trade_proposal_ids`
- `validated_trade_ids`
- `executed_trade_ids`
- `constitution_version`

### Why it exists

- it creates end-to-end traceability from evidence to portfolio change
- it supports review and audit of each state-changing event

### Invariants

- a state-changing event must point back to a decision cycle
- a decision cycle may produce zero or more state changes
- a trade proposal should retain its originating recommendation lineage
- traceability includes research packet references and cited evidence
- decision-cycle linkage records the constitution version used for the cycle

## Invariants

The model should preserve the following system-wide invariants:

- portfolio cash, positions, and valuation must be deterministic
- money and quantity calculations must use decimal-safe concepts
- authoritative calculations use at least 4 decimal places for money and prices, 6 decimal places for target weights, and 8 decimal places for share quantities
- binary floating-point values are prohibited for authoritative calculations
- LLMs may interpret evidence and recommend actions, but they do not invent cash, prices, or quantities
- `BUY` is the only trade action in the first vertical slice
- `HOLD` changes no portfolio state
- all executed changes are traceable to a decision cycle
- executed trades are distinct from proposals and validations
- benchmark tracking uses the same starting capital and contribution schedule
- portfolio and benchmark valuation use the same timestamp and price convention
- portfolio and benchmark valuation use the same approved price source within a decision cycle
- security identity must be stable enough to support audit and comparison

## Validation Ownership

Deterministic code owns validation.

It is responsible for:

- cash feasibility
- target-weight to dollar conversion
- dollar to quantity conversion
- fractional-share rounding and precision checks
- security eligibility checks
- maximum-position checks
- required-field checks
- duplicate or conflicting event checks
- portfolio invariants
- rejection of impossible or inconsistent trade proposals
- persistence of rejected proposal validation records

The portfolio domain model describes the facts and lifecycle; it does not make subjective decisions.

## What Belongs in Deterministic Code

The following belong in deterministic code, not in an LLM:

- portfolio state updates
- contribution application
- market value calculations
- cash balance updates
- quantity and cost-basis calculations
- benchmark replication logic
- trade proposal conversion from `target_weight`
- rounding down to approved quantity precision
- trade validation
- execution recording
- history append logic
- invariant checks

## What Does Not Belong in This Domain Model

The following are out of scope for this model:

- broker integrations
- live order routing
- order status polling
- tax treatment
- options logic
- leverage or margin
- portfolio optimization
- forecasting
- recommendation language
- prompt design
- framework-specific entity classes
- database selection

## MVP Scope

The first vertical slice includes:

- one portfolio
- one benchmark portfolio
- contributions
- cash balance tracking
- positions
- security identity
- portfolio valuation snapshots
- buy-only trade proposals
- validated trades
- rejected validation records
- executed trades as simulated paper actions
- portfolio history and decision-cycle linkage
- fractional shares
- deterministic validation

## Deferred Concepts

The following are intentionally deferred:

- `SELL`
- `TRIM`
- `REBALANCE`
- replacement trades
- options
- leverage
- margin
- taxes
- real brokerage execution
- order management
- tax lots beyond basic cost basis
- multi-currency portfolio conversion
- portfolio optimization engines
- advanced attribution
- recurring contribution schedules
- multiple fills per executed trade
- partial fill aggregation

## Open Questions

These items are intentionally unresolved and should not be invented here.

- What is the canonical source for the next available regular-session market closing price following approval?
