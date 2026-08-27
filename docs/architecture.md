# Architecture

## Overview

The system is organized as an investment committee with clear responsibilities.

The expected decision and execution flow is:

1. receive a Cash Event that creates buying power
2. gather research and assemble a structured research packet when needed
3. apply the portfolio constitution through manager logic or deterministic rules
4. validate investment intent with deterministic risk checks
5. review the reasoning and request human approval when required
6. execute only if the approval gate allows it

## Planned components

### Main orchestrator

Coordinates the overall workflow and routes work to the right component.

### FastAPI application adapter

The FastAPI layer is an application adapter. It exposes existing workflows over
HTTP, orchestrates application services, and provides the frontend API.

It does not own portfolio logic, recommendation logic, validation, benchmark
logic, execution logic, financial calculations, or domain policy. Those
responsibilities remain inside the deterministic domain and application layers.

### Research pipeline

Collects and structures evidence.

It does not make trade decisions.

### Portfolio managers

Each manager expresses a distinct investing philosophy.

- Value Manager
- Conservative Manager
- Growth / Opportunity Manager

Managers produce investment intent; they do not execute trades or mutate
portfolio state.

### Portfolio constitutions

Every portfolio is defined by a Portfolio, a Constitution, and an optional
Manager. A constitution defines the objective, investment philosophy, capital
deployment policy, constraints, and decision cadence. A Passive Index
Constitution is deterministic, while active constitutions may use a manager.

For AI-managed portfolios, investment methodology and advisory risk personality
are separate versioned artifacts. The investment constitution governs manager
reasoning. A Manager Risk Constitution describes strategy-specific risk posture,
sizing guidance, concentration, turnover, and evidence expectations. A minimal
universal System Safety Envelope separately owns hard enforcement. See ADR-008 and the
[Manager Risk Constitution Contract](manager-risk-constitution.md).

The System Safety Envelope is itself a repository-owned typed artifact with an
independent version, exact immutable snapshot/loading source, and canonical
SHA-256 hash. A decision journal records the exact envelope and manager-risk
artifacts used initially. Execution revalidates the active safety envelope and
retains manager-risk identity as immutable advisory lineage.

### Cash events

Cash Events create buying power and are separate from investment or execution.
Each portfolio receives the same Cash Events, then independently deploys its
available cash under its constitution.

### Deterministic risk engine

Normal code, not an LLM.

The accepted architecture separates:

- universal system-safety validation, including supported mechanics, cash,
  exact identity, currency, provenance, chronology, and immutable lineage; and
- manager-constitution assessment, including versioned concentration,
  turnover, sizing-guidance, evidence-sufficiency, and deviation observations.
  These findings are advisory and do not gate a mechanically safe trade.

The manager's proposed `target_weight` is immutable. Validation either accepts
that exact weight or records a failure; it never silently resizes it. Only a
passing weight is converted deterministically to dollars and quantity.

The current v0.1 runtime loads the active System Safety and Manager Risk
Constitutions for new decision cycles and persists their two-layer evaluation.
System Safety is hard; Manager Risk remains advisory.

Policy selection is keyed by exact managed portfolio identity plus manager
type and configured constitution versions/hashes. There is no implicit latest
fallback; missing, ambiguous, hash-mismatched, or incompatible selection fails
before manager invocation.

### AI investment reviewer

Critiques reasoning, evidence quality, hallucinations, methodology drift, and
whether concentration or turnover is justified under the selected manager's
own risk personality. It runs only after System Safety passes, is explicitly
operator-invoked, and persists one immutable result per decision cycle. Adverse
findings remain advisory in paper trading; human approval remains separate.

### Human approval layer

Prevents unauthorized execution and keeps the system aligned with the user’s intent.
It cannot override failed deterministic System Safety.

### Benchmark portfolio

SPY is tracked mechanically as the baseline comparison portfolio under a
deterministic Passive Index Constitution. It uses the same core Portfolio model
as managed portfolios, with benchmark-specific constraints applied separately.

## Portfolio Lifecycle

```text
Cash Event
  ↓
Portfolio receives buying power
  ↓
Constitution determines behavior
  ↓
Manager produces intent (or deterministic rule)
  ↓
System Safety validation (hard)
  ↓
Manager Risk Constitution assessment (advisory)
  ↓
AI review when configured
  ↓
Approval
  ↓
Execution-time revalidation
  ↓
Execution
  ↓
Portfolio updated
  ↓
Repeat
```

Failed System Safety remains journaled with the original recommendation and is
non-executable. Advisory manager-constitution findings remain attached without
resizing or automatically blocking the proposal. Reconsideration requires a
new explicitly linked decision cycle.

Revision lineage uses `revision_of_decision_cycle_id` and is a linear chain
between terminal non-executable cycles for the same manager and managed
portfolio. The complete manager decision reruns, so action or ticker may
change.

Immediately before managed execution, the accepted architecture revalidates
the exact approved target against current portfolio and price state plus the
currently active System Safety Envelope. It verifies the journaled Manager Risk
Constitution identity for lineage without converting advisory guidance into an
execution veto. This execution-time check is not yet implemented in v0.1.

## Current application shape (v0.1)

The operator-facing implementation uses:

- Python backend with Pydantic models at structured boundaries
- a thin FastAPI application adapter over deterministic domain/application services
- Variant C as the local operator UI
- Streamlit retained as an internal developer diagnostic tool over demo data
- SQLite as the local durable weekly-run store when
  `AGENTIC_PORTFOLIO_LAB_DB_PATH` is set

v0.1 providers are Twelve Data (prices), Alpha Vantage (research), and OpenAI
(Value Manager). Provider-specific identity translation stays at adapter
boundaries. Canonical SPY remains `SPY` / `NYSE ARCA` / `ETF` / `USD`.

Research uses the Research v2 weekly assembly: screen the versioned managed
universe, refresh selected names with statement reuse, and persist one
`ResearchBatch`. Initial hydration may reuse a cached OVERVIEW at most seven
days older than cycle `as_of`; a complete statement set still probes
LatestQuarter with a live OVERVIEW. An operator OVERVIEW bootstrap fills
missing cache rows at most 25 requests per invocation. Slot allocation and
rank stay on the screening audit record; they are not manager input. See
ADR-007 for screening contracts and the locked net-debt/EV cash and debt
convention.

HOLD is a valid terminal manager decision. Managed paper execution requires
deterministic validation, human approval, and backend executable readiness.
There is no autonomous execution.

Current validation proves mechanical feasibility; it must not be described as
enforcing Value-specific sizing or concentration. Existing v0.1 journals are
legacy mechanical validations and remain immutable. New typed and content-
hashed risk-policy artifacts, synchronized risk snapshots, layered rule
results, linked revision cycles, and execution-time policy records are planned
post-v0.1 work under ADR-008.

The new policy contract activates only after implementation Lanes 1–5 and
their migration/restart tests are integrated. Until then, new cycles continue
to use current v0.1 behavior; after activation, new cycles require current
policy references and cannot create legacy references.

Not in v0.1: additional managers, brokerage
integration, scheduling, authentication, and cloud persistence.
