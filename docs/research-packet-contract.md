# Research Packet Contract

## Purpose

A Research Packet is the structured evidence bundle for exactly one company or security, supplied to the first Value Manager.

It exists to give the manager facts, source-backed summaries, and explicit uncertainty so the manager can make a portfolio decision without performing raw research itself.

A Research Batch is a separate top-level object that groups one or more Research Packets for a single decision cycle.

The packet is an evidence container, not a decision engine.

## Responsibilities

The research packet should:

- present factual inputs in a structured form
- preserve source provenance for every important claim
- include both positive and negative evidence
- capture freshness and as-of timing for numerical data
- make missing information explicit
- remain usable regardless of LLM provider or agent framework
- be independently cacheable, refreshable, testable, and reusable
- allow downstream components to verify that evidence citations are real and traceable

## Explicit Non-Responsibilities

The research packet must not:

- recommend `BUY`, `HOLD`, or any other action
- decide which Research Packet should be selected
- enforce portfolio sizing, concentration, or eligibility rules
- normalize raw source data itself
- hide contradictory evidence
- fabricate missing data
- depend on a particular market-data provider, news provider, database, brokerage, or agent framework
- replace deterministic validation
- contain private credentials or non-public personal financial data

Raw source retrieval and normalization happen upstream. Decision-making happens downstream in the Value Manager and deterministic validation layers.

## Settled Decisions

For the first Value Manager workflow:

- a Research Packet represents exactly one company or security
- a Research Batch is the single decision-cycle container that contains one or more Research Packets
- the Research Batch may preserve ordering
- the Research Batch may include decision-cycle metadata
- the packet is a structured evidence bundle, not a prompt
- the manager may cite only evidence identifiers that appear in the packet
- every important numerical value must include an as-of period or date
- every AI-generated summary must reference underlying evidence items
- missing values must be explicit and never silently inferred
- current events and news may be included if they include publication date, event date when known, source, and relevance
- the packet should support deterministic downstream verification of evidence references

## Proposed Working Assumptions

These are the working assumptions used to define the MVP contract:

- the top-level Research Batch is delivered as a separate object that can contain one or more Research Packets
- the batch may preserve packet ordering for downstream review or prioritization
- each Research Packet includes a stable `packet_id` and refers to exactly one company or security
- packet-level content is independently reusable across different batches when refreshed or re-run
- upstream systems own raw retrieval, normalization, and source selection
- the packet may include AI-generated summaries, but those summaries are strictly derived from evidence items already in the packet
- any source-backed claim that matters to the decision should be traceable to one or more evidence items
- the first implementation will prioritize a compact packet over an exhaustive report

## Research Batch Metadata

The Research Batch should include decision-cycle metadata that describes the whole submission.

### Required batch-level metadata

- `batch_id`
- `decision_cycle_id`
- `portfolio_id`
- `manager_type`
- `created_at`
- `as_of_timestamp`
- `packets`

### Why it exists

- `batch_id` provides a stable identifier for logging and review
- `decision_cycle_id` groups the packet set for one evaluation run
- `portfolio_id` ties the batch to the intended portfolio context
- `manager_type` indicates the intended philosophy layer, such as Value Manager
- `created_at` shows when the packet was assembled
- `as_of_timestamp` marks the freshness boundary for the decision cycle
- `packets` contains the ordered Research Packets for the decision cycle

## Research Packet Identity

Each Research Packet should identify exactly one company or security being evaluated.

### Required fields

- `packet_id`
- `candidate_id`
- `ticker`
- `company_name`
- `security_type`
- `exchange`
- `currency`
- `sector`
- `industry`

### Why it exists

- `packet_id` lets the manager reference one packet unambiguously
- `candidate_id` provides a stable candidate reference inside the packet
- `ticker` is the primary market identifier used downstream
- `company_name` helps human review and reduces identifier ambiguity
- `security_type` prevents mixing common stocks with other instruments
- `exchange` and `currency` help interpret market and valuation data correctly
- `sector` and `industry` provide context for comparables and business structure

### Missing-data rule

If any identity field is unknown, it must be represented explicitly as missing rather than guessed.

## Market-Price Snapshot

Each Research Packet should include the latest usable market-price snapshot available upstream.

### Required fields

- `price`
- `price_as_of`
- `price_currency`
- `quote_source`

### Optional fields

- `market_cap`
- `market_cap_as_of`
- `day_change`
- `week_change`
- `volume`
- `average_volume`
- `bid`
- `ask`
- `trading_halt_status`

### Why it exists

- price context is needed to interpret valuation and recent movement
- `price_as_of` anchors the quote in time
- currency is needed to avoid unit confusion
- source information supports provenance and review

### Important constraint

The packet should present the price snapshot only as a fact bundle. It must not infer whether the stock is cheap or expensive.

## Business Overview

Each Research Packet should describe the business in a concise, source-backed way.

### Required fields

- `business_summary`
- `revenue_model`
- `customer_or_user_base`
- `products_or_services`
- `geography`
- `business_stage`

### Why it exists

- the manager needs to understand what the company actually does
- business model context is required for evaluating durability and economics
- geography and business stage often affect risk and comparables

### Guidance

Business summaries may be AI-generated, but they must point back to evidence items that support the summary.

## Financial Performance

Each Research Packet should include core operating performance data.

### Required fields

- `revenue`
- `revenue_period`
- `revenue_as_of`
- `revenue_growth`
- `eps` or `net_income_per_share` if available
- `operating_income` if available
- `gross_margin` if available
- `operating_margin` if available

### Why it exists

- revenue and growth show business scale and trajectory
- profitability metrics help distinguish durable businesses from unprofitable ones
- period and as-of data prevent time ambiguity

### Guidance

If a metric is unavailable, the missing value must be explicit. A blank field is not acceptable.

## Balance-Sheet and Debt Information

Each Research Packet should include the balance-sheet facts needed to judge financial resilience.

### Required fields

- `cash_and_equivalents`
- `total_debt`
- `net_debt` if available
- `current_assets` if available
- `current_liabilities` if available
- `debt_maturity_profile` if available
- `interest_expense` if available
- `balance_sheet_as_of`

Packet `cash_and_equivalents` remains the cash-and-equivalents fact for the
manager-facing packet. Research v2 derived `net_debt` and `enterprise_value`
use a separate cash_for_net_debt input (preferred
`cashAndShortTermInvestments`, then CCE+STI, then CCE-only). See ADR-007.
Those derived values must not be treated as if they subtracted CCE-only cash
from `shortLongTermDebtTotal`.

### Why it exists

- leverage and liquidity affect downside risk
- debt maturity structure matters for refinancing risk
- balance-sheet strength is often critical in Value Manager decisions

## Cash-Flow Information

Each Research Packet should include cash-flow facts where available.

### Required fields

- `operating_cash_flow`
- `free_cash_flow` if available
- `capital_expenditure` if available
- `cash_flow_period`
- `cash_flow_as_of`

### Why it exists

- cash flow shows whether accounting earnings are supported by actual cash generation
- free cash flow is central to long-term value assessment
- period and as-of timing keep comparisons honest

## Profitability and Margin Trends

Each Research Packet should describe how profitability is evolving over time.

### Required fields

- `gross_margin_trend` if available
- `operating_margin_trend` if available
- `net_margin_trend` if available
- `return_on_equity` if available
- `return_on_invested_capital` if available
- `trend_period`
- `trend_as_of`

### Why it exists

- Value decisions often depend on whether quality is improving or deteriorating
- trends provide context beyond a single point-in-time metric

## Share Count and Dilution

Each Research Packet should show share count behavior clearly.

### Required fields

- `basic_shares_outstanding`
- `diluted_shares_outstanding` if available
- `share_count_period`
- `share_count_as_of`
- `share_based_compensation` if available
- `buybacks` if available
- `issuance` if available

### Why it exists

- dilution affects per-share value
- buybacks and issuance change how value accrues to owners
- share count trends can matter as much as revenue growth

## Valuation Metrics

Each Research Packet should include the current valuation facts used by the manager.

### Required fields

- `price_to_earnings`
- `price_to_sales` if available
- `enterprise_value`
- `enterprise_value_to_ebitda` if available
- `free_cash_flow_yield` if available
- `price_to_book` if available
- `valuation_as_of`

Research v2 `enterprise_value` is `market_cap + net_debt`, and that `net_debt`
uses cash_for_net_debt rather than packet `cash_and_equivalents`. See ADR-007.

### Why it exists

- Value Manager decisions depend on valuation relative to fundamentals
- multiple valuation lenses reduce overreliance on one metric
- `valuation_as_of` prevents stale comparisons

### Constraint

The packet should report valuation metrics as facts, not as a recommendation that the asset is cheap or expensive.

## Historical Valuation Context

Each Research Packet should include enough history to show whether valuation is improving, deteriorating, or mean-reverting.

### Required fields

- `historical_valuation_summary`
- `historical_highlights`
- `historical_period`
- `historical_as_of`

### Why it exists

- one point in time is not enough to judge value
- context helps the manager determine whether a valuation level is unusual

### Guidance

This section may be summary-heavy, but every summary must still point to evidence items.

## Competitive Position and Business Durability

Each Research Packet should describe how the business is positioned relative to competitors and how durable that position appears.

### Required fields

- `competitive_position_summary`
- `moat_or_advantage_summary` if available
- `customer_retention` if available
- `pricing_power` if available
- `market_share` if available
- `durability_summary`

### Why it exists

- Value decisions are not only about price; they are also about business quality and durability
- competitive position helps distinguish temporary weakness from structural weakness

## Recent SEC Filing Evidence

Each Research Packet should include relevant filing evidence when available.

### Required fields

- `filing_type`
- `filing_date`
- `filing_as_of`
- `filing_source`
- `filing_highlights`

### Optional filings

- 10-K
- 10-Q
- 8-K
- proxy statement
- other relevant SEC filings

### Why it exists

- SEC filings are primary evidence for public-company facts
- filing highlights help the manager and reviewer quickly locate material claims

### Constraint

Filing highlights may summarize the filing, but they must still reference the filing evidence item they came from.

## Earnings Information

Each Research Packet should include earnings data and recent earnings commentary when available.

### Required fields

- `earnings_date`
- `earnings_release_as_of`
- `eps_actual` if available
- `eps_estimate` if available
- `revenue_actual` if available
- `revenue_estimate` if available
- `earnings_surprise` if available
- `guidance_summary` if available

### Why it exists

- earnings are a common source of new information and sentiment shifts
- guidance can materially affect the value case

## Relevant Recent News and Current Events

Each Research Packet may include current events and news when they are relevant to the security.

### Required fields for each news item

- `news_id`
- `publication_date`
- `event_date` if known
- `source`
- `headline`
- `summary`
- `relevance`

### Why it exists

- recent events can change the investment case quickly
- publication date and event date help distinguish new information from old
- relevance prevents noisy news from overwhelming the packet

### Guidance

News summaries may be AI-generated, but they must reference the underlying news evidence items and should not obscure negative items.

## Known Risks and Contradictory Evidence

Each Research Packet must preserve downside evidence, not just supportive material.

### Required fields

- `known_risks`
- `contradictory_evidence`
- `bear_case`
- `thesis_challenges`
- `risk_severity` if available

### Why it exists

- the manager needs to know what could break the thesis
- contradictory evidence is essential for balanced decision-making
- hiding downside evidence would distort the manager output

### Constraint

Negative evidence must be represented with the same seriousness as positive evidence.

## Evidence-Item Structure

Every important claim should trace back to one or more evidence items.

### Required evidence-item fields

- `evidence_id`
- `source_type`
- `source_title`
- `source_date`
- `claim_supported`

### Strongly recommended evidence-item fields

- `source_url` if available
- `retrieved_at`
- `as_of`
- `excerpt_or_summary`
- `confidence_in_extraction` if AI-assisted
- `notes`

### Why it exists

- `evidence_id` gives each item a stable reference
- `source_type` helps distinguish filings, earnings releases, news, and market data
- `source_title` and `source_date` support review
- `claim_supported` makes the evidence-to-claim relationship explicit

### Constraint

The manager may only cite evidence identifiers present in the packet.

## Data Freshness and As-Of Timestamps

Every important numeric value must include an as-of period or date.

### Required freshness fields

- `as_of_timestamp` at packet level
- per-section or per-metric `as_of` fields where applicable
- `retrieved_at` for evidence items when available

### Why it exists

- valuations, price data, earnings, and filings become stale over time
- freshness makes comparison and review possible
- time anchoring is essential for auditability

### Rule

If a metric does not include an as-of period or date, it should be treated as incomplete.

## Missing-Data Representation

Missing values must be explicit.

### Required behavior

- use a null-like explicit missing marker, not an empty guess
- distinguish between `unknown`, `not available`, and `not applicable` when possible
- do not silently impute missing values
- do not infer a value from context unless the upstream process explicitly did so and documented it

### Why it exists

- the manager needs to know what is known versus assumed
- silent inference hides uncertainty
- explicit missingness improves review quality

## Source Reliability and Provenance

The packet should preserve source quality information so downstream reasoning can account for it.

### Recommended fields

- `source_type`
- `source_name`
- `source_url`
- `source_author`
- `retrieved_at`
- `published_at`
- `primary_or_secondary`
- `reliability_notes`

### Why it exists

- not all evidence is equally strong
- provenance helps reviewers weigh claims correctly
- primary sources should be distinguishable from secondary summaries

## How Multiple Research Packets Are Supplied to the Manager

For the MVP, multiple Research Packets should be delivered in a single Research Batch, with packet order preserved when needed.

### Proposed top-level structure

- `batch_id`
- `decision_cycle_id`
- `portfolio_id`
- `manager_type`
- `created_at`
- `as_of_timestamp`
- `packets`

Each item in `packets` should contain:

- `packet_id`
- `candidate_id`
- identity fields
- evidence sections
- freshness metadata
- source references

### Why it exists

- the Value Manager may evaluate more than one Research Packet but must return only one recommendation
- a single Research Batch makes comparison between packets easier
- ordered packets allow the upstream system to preserve a review priority if needed

### Constraint

The batch may contain multiple Research Packets, but it must not choose one for the manager.

## What Information Must Be Deterministic

The following information should be deterministic upstream inputs whenever possible:

- packet identifiers
- ticker and identity fields
- source references
- dates and timestamps
- raw market data
- filing metadata
- earnings metadata
- news metadata
- numerical metrics
- evidence-item identifiers
- source provenance fields

Deterministic data is important because the manager should reason over stable facts rather than uncertain paraphrases.

## What Information May Be AI-Generated Summaries

The following may be AI-generated summaries if they remain traceable to evidence items:

- business summary
- competitive position summary
- historical valuation summary
- durability summary
- filing highlights
- earnings commentary
- news summaries
- risk synthesis
- contradiction synthesis
- concise section-level summaries

### Rule

Any AI-generated summary must reference the evidence items it depends on.

## Failure Behavior

The Research Packet and Research Batch should fail closed when critical data is missing or ambiguous.

### Failure cases

- missing identity data for a Research Packet
- missing or stale price data when the packet depends on a current quote
- missing evidence identifiers for a summary claim
- missing as-of dates for important numbers
- contradictory data that cannot be reconciled upstream
- evidence references that cannot be traced to packet contents

### Required failure behavior

- surface the problem explicitly
- avoid silent normalization
- avoid invented fallback values
- allow downstream validation to reject the packet

The packet should be treated as incomplete rather than auto-corrected when the evidence is not sound.

## Research Batch and Packet Example

This is a minimal illustration of the intended shape, not a production schema.

```text
research_batch:
  batch_id: rb_2026_08_06_001
  decision_cycle_id: dc_2026_08_06_am
  portfolio_id: portfolio_value_001
  manager_type: value
  created_at: 2026-08-06T14:00:00Z
  as_of_timestamp: 2026-08-06T13:30:00Z
  packets:
    - packet_id: rp_abc
      candidate_id: cand_abc
      ticker: ABC
      company_name: Example Components Inc.
      security_type: common_stock
      exchange: NYSE
      currency: USD
      sector: Industrials
      industry: Electrical Equipment
      price:
        value: 42.15
        price_as_of: 2026-08-06T13:30:00Z
      business_summary: Source-backed summary of the company and its revenue model.
      valuation_metrics:
        price_to_earnings:
          value: 12.4
          as_of: 2026-08-06T13:30:00Z
      risks:
        - summary: Margin pressure from input costs.
          evidence_ids: [ev_01, ev_04]
      evidence_items:
        - evidence_id: ev_01
          source_type: filing
          source_title: "Quarterly Report"
          source_date: 2026-08-01
          claim_supported: "Revenue growth and margin trend"
        - evidence_id: ev_04
          source_type: news
          source_title: "Industry pricing update"
          source_date: 2026-08-05
          claim_supported: "Input cost pressure"
    - packet_id: rp_xyz
      candidate_id: cand_xyz
      ticker: XYZ
      company_name: Example Software Co.
      security_type: common_stock
      exchange: NASDAQ
      currency: USD
      sector: Technology
      industry: Application Software
      price:
        value: 88.20
        price_as_of: 2026-08-06T13:30:00Z
      business_summary: Separate packet for a different company in the same batch.
      evidence_items:
        - evidence_id: ev_10
          source_type: filing
          source_title: "Annual Report"
          source_date: 2026-07-29
          claim_supported: "Business model and revenue mix"
```

The example shows the expected pattern:

- the batch groups multiple packets for one decision cycle
- each packet stands on its own for one company or security
- batch metadata stays on the Research Batch
- timestamps are explicit
- evidence is referenced by identifier
- negative evidence is retained
- no investment decision is embedded in the packet

## Manager-risk evidence coverage

ADR-008 introduces typed evidence coverage for manager reasoning, Reviewer
assessment, human review, and audit. This is a coverage/maturity assessment,
not an investment-quality score, sizing authorization, or new responsibility of
the Research Packet.

`BASELINE_RESEARCH_V2` is the only currently defined and reachable band. It
requires exact `SecurityIdentity` agreement among candidate, packet, and every
endpoint record. Required endpoints are `OVERVIEW`, `INCOME_STATEMENT`,
`BALANCE_SHEET`, `CASH_FLOW`, and `EARNINGS`. Under the existing packet and
cycle-as-of freshness contracts, each coverage record must be
`FETCHED_THIS_CYCLE` (current) or `REUSED_CURRENT`; `STALE` and `MISSING`
disqualify the band.

All current deterministic derivations must be evaluated:

- `net_debt`, `current_ratio`, `gross_margin`, `operating_margin`, and
  `net_margin`;
- `fcf`, `ttm_ocf`, `ttm_capex`, `ttm_fcf`, `ttm_net_income`, and
  `ttm_revenue`; and
- `cash_conversion`, `share_count_change`, `market_cap`, `enterprise_value`,
  and `fcf_yield`.

Each required metric record must retain its formula/metric identity,
attributable typed input references, deterministic reliability, and freshness.
Its value may be either a typed Decimal or explicit typed `MissingData`.
Baseline does not require every derivation to be numerically present. A missing
metric record or lost input attribution disqualifies the band; a correctly
preserved `MissingData` result does not.

The assessment verifies that required evidence is present and attributable. It
does not claim that cash flow is normalized, leverage is safe, business
durability is established, or the evidence economically supports a BUY.
Missing facts and derived `MissingData` are preserved and never inferred or
interpreted as zero.

An enhanced evidence profile is reserved by the Value Manager Risk
Constitution, but its evidence topics and acquisition path are deliberately
deferred. It carries no portfolio-weight ceiling or sizing authority.

## Remaining Open Questions

These are general/future packet-schema questions. They do not alter
`BASELINE_RESEARCH_V2`'s locked five endpoint coverage records, 16 evaluated
derived-metric records, exact-identity requirement, or typed `MissingData`
semantics described above.

- What is the exact canonical JSON shape of the packet envelope?
- What is the canonical set of required fields for every Research Packet in the MVP?
- Which valuation metrics are mandatory versus optional in the first slice?
- How should evidence quality be scored, if at all?
- Beyond the existing typed `MissingData` used by baseline Research v2, what
  missing-value representation should future packet sections use?
- How should upstream systems encode primary versus secondary sources?
- Should market-cap and liquidity data be required in the first implementation?
- Should the packet include analyst estimates, and if so, in what sections?
- What is the minimum news horizon the first implementation should include?
- How much historical valuation context is enough for the Value Manager?
- Should competitive position be narrative-only or partially structured?
- What exact schema should be used for evidence-item provenance metadata?
