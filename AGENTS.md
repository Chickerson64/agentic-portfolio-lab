# AGENTS.md

This file is the human-readable repository engineering contract for Codex,
Cursor, and any other agent working in this repository.

## Project Purpose

- Agentic Portfolio Lab is primarily an AI engineering learning project.
- Investing is the first application domain.
- The system currently supports local paper trading and may later support human-approved real-money investing.
- It must never be presented as guaranteed financial advice or an oracle.

## Engineering Principles

- Prefer normal deterministic code over an LLM whenever code can solve the problem reliably.
- Keep architecture explicit, modular, and understandable.
- Avoid unnecessary abstractions and premature frameworks.
- Add dependencies only when a current requirement justifies them.
- Use typed Python.
- Use Pydantic for important structured boundaries when appropriate.
- Write tests for deterministic financial logic.
- Keep AI-generated reasoning separate from deterministic calculations.
- Important decisions should be explainable and traceable to evidence.
- Never add secrets, credentials, brokerage keys, or personal financial data to the repository.

## Workflow

- Inspect existing documents before proposing architectural changes.
- Do not silently make major design decisions.
- Record significant architecture decisions in `docs/decisions/`.
- For implementation tasks, explain the plan before changing many files.
- Run relevant tests and summarize what changed.
- Do not implement unrelated backlog items.
- Preserve human approval before any eventual real-money trade execution.

## Current Scope

v0.1.0 is the tagged known-good baseline. v0.1 is a local weekly paper-trading loop:

- One Value Manager, screened five-slot Alpha Vantage Research v2 (cheap
  OVERVIEW screen over the versioned universe, five deep slots, statement
  reuse, derived metrics in application code), deterministic validation, human
  approval, and simulated managed execution.
- Durable SQLite local-run state. Do not commit the database or provider keys.
- Twelve Data prices and a mechanical SPY benchmark (`SPY` / `NYSE ARCA` / `ETF` / `USD`).
- FastAPI plus the Variant C operator UI. The frontend must not own financial calculations or execution policy.
- HOLD is a legitimate terminal manager decision and must never become executable.
- No brokerage integration, autonomous trading, real-money execution, or additional managers.

## Cursor workflow

The user talks to the Lead. The Lead delegates implementation to Builder(s)
and completed work to a Reviewer, then owns commit, integration, and release
gates.

```text
Lead → Builder → Reviewer → Lead
```

Cursor agents must follow `.cursor/rules/`. Role details, worktrees, review
loops, model usage, and release gates are in
`docs/development-workflow.md`. Do not copy those rules back into this file.

Git history, repository files, and `docs/` are the durable shared memory
between agents. Chat is not.

## How agents should use this file

- Treat this as the default operating agreement for the repository unless a more specific instruction overrides it.
- Re-read it before starting new work in this project so decisions stay aligned over time.
- Use it to decide whether a task is in scope, whether a design choice needs documentation, and whether deterministic code should be preferred over AI.
- If a requested change conflicts with these rules, stop and surface the conflict instead of proceeding silently.

