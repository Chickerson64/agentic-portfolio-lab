# Architecture

## Overview

The system is organized as an investment committee with clear responsibilities.

The expected flow is:

1. gather research
2. assemble a structured research packet
3. run manager logic
4. validate the proposal with deterministic risk checks
5. review the reasoning
6. request human approval when required
7. execute only if the approval gate allows it

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

SPY is tracked mechanically as the baseline comparison portfolio.

## Early implementation shape

The most likely initial implementation is:

- Python backend
- Pydantic models for structured data
- SQLite for local persistence
- a simple CLI or notebook-style workflow first

Framework and provider choices remain intentionally open.

