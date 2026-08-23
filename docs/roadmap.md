# Product Roadmap

## Current status (v0.1)

v0.1 implements the local weekly paper-trading loop through FastAPI, Variant C,
SQLite durability, Twelve Data prices, paper SPY fulfillment, Alpha Vantage
research, the OpenAI Value Manager, deterministic validation, human approval,
and managed paper execution. HOLD is a legitimate non-executing terminal
decision.

Research v2 screening, statement reuse, derived metrics, operator OVERVIEW
bootstrap, and the approved 30-name `value-us-equities-v1` snapshot as the live
managed universe are implemented on this branch. Remaining related research work
is additional evidence sources and retrieval adapters, not expanding this
universe snapshot.

Still later-phase work, not claimed as v0.1:

- export/import backups and a formal operator checklist
- additional research evidence sources and retrieval adapters
- AI reviewer adapter
- additional managers, SELL, and rebalance
- brokerage, authentication, scheduling, and cloud persistence

Amended ADR-008 locks hard universal System Safety plus versioned advisory
Manager Risk Constitutions, with optional explicit hard mandates deferred. The
current runtime still performs legacy mechanical validation; advisory policy
selection, linked revision cycles, and execution-time safety revalidation are
not yet implemented.

The phase list below remains the historical plan.

## Roadmap Principle

Every new feature should satisfy at least one of these criteria:

1. Makes the weekly operator workflow easier.
2. Makes investment decisions more correct.
3. Improves auditability or traceability.
4. Improves user understanding.

If it satisfies none of these, it likely belongs in a later phase.

The product priority is a usable local weekly paper-trading workflow before
platform-grade infrastructure.

## Phase 0 — Release 1.0 Consolidation

Consolidate completed MVP work into one canonical, runnable application
baseline. This phase adds no product capability.

- Integrate the completed MVP branches, including simulated execution and the
  OpenAI Value Manager adapter.
- Reconcile issue and milestone state with the integrated history.
- Update the README, backlog, and operator-facing project status.

## Phase 2 — Usable Operator Interface

Turn Variant C into the local operator application while retaining Streamlit as
an internal developer diagnostic tool.

- Add a thin FastAPI application adapter.
- Connect Variant C to portfolio, benchmark, decision, research, history,
  reviewer, approval, and simulated-execution artifacts.
- Provide explicit manual decision-run, approval/rejection, and simulation
  actions.

FastAPI exposes existing workflows over HTTP, orchestrates application
services, and provides the frontend API. It does **not** own portfolio,
recommendation, validation, benchmark, execution, financial-calculation, or
domain-policy logic; those remain in the existing deterministic
domain/application layers.

## Phase 3 — Live Market Data and Fair SPY Baseline

Replace synthetic prices with attributable market observations and make the SPY
benchmark a mechanically comparable portfolio.

- Define a market-price provider contract and add one provider.
- Support latest and historical observations with source attribution,
  timestamps, market date, currency, price convention, and stale-data handling.
- Add manual managed/benchmark valuation refresh.
- Fulfill deterministic passive-SPY execution intent and validate the fair
  comparison baseline.

## Phase 4 — Weekly Paper Trading

Make one real paper portfolio usable week after week.

- Use SQLite as the local durable store.
- Persist run state and artifacts, support resumable runs, and expose run
  status through the operator application.
- Add export/import backups, an operational checklist, and smoke tests.

This phase deliberately excludes a repository abstraction, event store,
migration framework, and distributed scheduling unless later usage proves one
necessary.

## Phase 5 — Research Automation

Reduce manual ResearchBatch preparation without weakening provenance.

- Define a candidate universe and retrieval adapters.
- Assemble deterministic, normalized Research Batches.
- Preserve provenance and explicit missing-data treatment.

## Phase 6 — Strategy Expansion

Add a second strategy only after the first manager has meaningful
paper-trading history.

- Add a minimal manager registry and one additional constitution.
- Compare recommendations and historical outcomes side by side.

Strategy expansion depends on completing the manager-risk implementation and
giving every manager a separate managed portfolio and history. The initial
controlled experiment keeps funding, data availability, as-of cutoff,
opportunity universe, execution convention, approval protocol, performance
calculation, and benchmark methodology equal. Investment and risk
constitutions are deliberate strategy variables.

## Phase 7 — Operational Hardening

Evolve into a more robust platform only after real usage validates the need.

- Consider stronger persistence, scheduling, retries, reconciliation, backups,
  migrations, authentication, and observability.

## Recommended Issue Sequence

1. Integrate completed MVP branches into one runnable baseline.
2. Refresh README, backlog, and local operator runbook.
3. Add the thin FastAPI application adapter.
4. Connect Variant C as the operator shell.
5. Add the manual decision, validation/review, approval, and simulation flow.
6. Define the market-price provider contract.
7. Implement the first attributed market-price provider.
8. Add manual managed/benchmark valuation refresh.
9. Fulfill passive-SPY benchmark execution intent.
10. Verify the fair-SPY baseline end to end.
11. Add the local SQLite weekly-run store.
12. Add resumable weekly-run status and workflow.
13. Back the application views with persisted weekly runs.
14. Add export/import backups and the operator checklist.
15. Add research retrieval.
16. Add deterministic ResearchBatch assembly.
17. Add research freshness/provenance review.
18. Add a second manager/constitution.
19. Add manager comparison.
20. Consider operational hardening work.

## Manager Risk Constitution implementation sequence

Lane 0 is ADR and contract alignment only. Subsequent lanes require separate
approval and must not be inferred to be current capability:

1. **Lane 1 — typed policy domain:** risk versions, typed artifacts, Decimal
   string parsing, canonical SHA-256 hashing, compatibility, evidence coverage,
   synchronized risk snapshots, and invariants.
2. **Lane 2 — safety plus advisory assessment:** immutable in-memory System
   Safety results and separate non-gating manager-constitution observations,
   unchanged target weights, and a CRM 25% mechanical-validity regression.
   Durable policy persistence is not part of Lane 2.
3. **Lane 3 — durable compatibility:** persist validation plus exact policy
   artifacts, implement discriminated legacy decoding/re-encoding, indexes,
   immutability, and restart coverage.
4. **Lane 4 — application and API:** exact policy selection, operator
   visibility, explicit linked revisions, and portfolio/manager research
   lineage.
5. **Lane 5 — execution revalidation:** current-state System Safety snapshots,
   advisory-policy lineage verification, and immutable execution-policy checks.
6. **Lane 6 — AI Reviewer integration:** generalized manager/reviewer types and
   durable paper-only REQUEST_CHANGES-with-CRITICAL override flag/rationale.
   Risk policy may activate without this optional adapter; until Lane 6 lands,
   production has no AI Reviewer result or override path.
7. **Lane 7 — multi-manager experiment:** separate managed portfolios and
   histories under controlled fair-comparison conditions.

Activation is a gate after Lanes 1–5 are integrated and canonical-hash,
migration, restart, persistence, and execution-revalidation tests pass. Before
that gate, the new documents describe target behavior only. After it, every
new production cycle requires current policy references and cannot use legacy
mechanical policy identity.
