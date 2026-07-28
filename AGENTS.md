# AGENTS.md

This file gives future Codex agents durable guidance for working in this repository.

## Project Purpose

- Agentic Portfolio Lab is primarily an AI engineering learning project.
- Investing is the first application domain.
- The system may eventually support paper trading and later human-approved real-money investing.
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

- Documentation and architecture first.
- No brokerage integration.
- No autonomous trading.
- No agent framework selection yet.
- No production database or frontend decision yet.
- The first future vertical slice will involve one Value Manager, one supplied research packet, one structured decision, deterministic validation, reviewer feedback, and a simulated portfolio action.

## How Codex Should Use This File

- Treat this as the default operating agreement for the repository unless a more specific instruction overrides it.
- Re-read it before starting new work in this project so decisions stay aligned over time.
- Use it to decide whether a task is in scope, whether a design choice needs documentation, and whether deterministic code should be preferred over AI.
- If a requested change conflicts with these rules, stop and surface the conflict instead of proceeding silently.

