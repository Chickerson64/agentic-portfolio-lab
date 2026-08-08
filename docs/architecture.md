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

## Early implementation shape

The most likely initial implementation is:

- Python backend
- Pydantic models for structured data
- SQLite for local persistence
- a simple CLI or notebook-style workflow first

Framework and provider choices remain intentionally open.
