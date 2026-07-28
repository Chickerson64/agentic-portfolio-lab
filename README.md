# Agentic Portfolio Lab

Agentic Portfolio Lab is a documentation-first learning project for building a modular AI investment committee system.

The initial focus is paper trading and architecture exploration, with strong safety controls and clear separation between:

- investment philosophy
- research
- deterministic risk checks
- AI review
- human approval
- execution

## Current status

This repository is in the initial scaffold phase.

Implemented so far:

- project charter
- architecture notes
- design principles
- open questions
- backlog
- decision log placeholder
- Python package skeleton

Not implemented yet:

- agents
- trading logic
- brokerage integration
- market-data access
- databases
- frontend UI

## Repository layout

```text
.
├── README.md
├── docs
│   ├── architecture.md
│   ├── backlog.md
│   ├── decisions
│   │   └── README.md
│   ├── design-principles.md
│   ├── open-questions.md
│   └── project-charter.md
├── pyproject.toml
├── src
│   └── agentic_portfolio_lab
│       └── __init__.py
└── tests
    └── __init__.py
```

## Guiding idea

If normal code can do something reliably, use normal code.
AI should be used where judgment, critique, synthesis, or explanation are genuinely needed.

## Next milestones

1. Define the Value Manager constitution.
2. Design the research packet schema.
3. Specify the deterministic risk engine.
4. Build one complete paper-trading workflow.
