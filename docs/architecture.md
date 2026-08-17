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

### Cash events

Cash Events create buying power and are separate from investment or execution.
Each portfolio receives the same Cash Events, then independently deploys its
available cash under its constitution.

### Deterministic risk engine

Normal code, not an LLM.

It validates:

- cash availability
- position sizing
- ticker eligibility
- concentration limits
- required fields
- prohibited actions

### AI investment reviewer

Critiques reasoning, evidence quality, hallucinations, and methodology drift.

### Human approval layer

Prevents unauthorized execution and keeps the system aligned with the user’s intent.

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
Validation
  ↓
Approval
  ↓
Execution
  ↓
Portfolio updated
  ↓
Repeat
```

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
`ResearchBatch`. An operator OVERVIEW bootstrap fills missing cache rows at
most 25 requests per invocation. Slot allocation and rank stay on the
screening audit record; they are not manager input. See ADR-007.

HOLD is a valid terminal manager decision. Managed paper execution requires
deterministic validation, human approval, and backend executable readiness.
There is no autonomous execution.

Not in v0.1: additional managers, an AI reviewer adapter, brokerage
integration, scheduling, authentication, and cloud persistence.
