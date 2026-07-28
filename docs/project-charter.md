# Project Charter

## Purpose

Agentic Portfolio Lab is a learning project for designing and testing an AI-assisted investment committee system.

The first domain is investing, but the deeper goal is to learn how to build:

- LLM agents and tool use
- structured prompts and workflows
- research pipelines
- API integrations
- deterministic validation layers
- approval workflows
- scheduled jobs
- auditable decision systems

## Scope

The project begins with paper trading only.

In scope for the early phases:

- portfolio-manager abstractions
- research packets
- risk checks
- AI reviewer workflows
- human approval gates
- SPY benchmark comparison
- paper portfolio accounting

Out of scope for now:

- real-money trading
- brokerage integration
- execution automation
- live market-data provider selection
- frontend implementation details
- persistent order management

## Core portfolios

The long-term design includes three investment managers:

- Value Manager
- Conservative Manager
- Growth / Opportunity Manager

These are philosophy layers, not personalities. Presentation details must not control portfolio logic.

## Safety stance

No autonomous real-money trading.

Human approval is required before real-money execution and should also be used during early testing.

## Success criteria

The project is successful if it becomes:

- understandable to a computer-science student
- explainable and auditable
- safe by default
- modular enough to grow over time
- useful as both a learning project and a potential future personal investing tool

