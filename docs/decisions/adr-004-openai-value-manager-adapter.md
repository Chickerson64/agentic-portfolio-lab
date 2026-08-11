# ADR-004: OpenAI-backed Value Manager Adapter

**Date:** 2026-08-10  
**Status:** Accepted

## Motivation

Issue #23 needs the first real LLM-backed adapter for the existing Value Manager
protocol without changing downstream workflow, validation, approval, or
execution boundaries.

## Decision

The first implementation uses the official OpenAI Python SDK with the Responses
API and a single concrete adapter that implements the existing
`ValueManager` protocol.

The adapter:

- accepts `ValueManagerDecisionContext`
- returns exactly one `PortfolioRecommendation`
- uses structured output and deterministic domain construction
- keeps provider-specific metadata outside domain recommendation models
- reads credentials from standard OpenAI environment configuration
- keeps the model name configurable, with `gpt-5.6-terra` as the default

## Consequences

- The rest of the application continues to depend on the `ValueManager`
  protocol, not on OpenAI-specific types.
- Tests can use a local fake client and do not require a live API key.
- Structured output failures remain explicit at the adapter boundary.
- Provider metadata is available for diagnostics without leaking into the
  domain recommendation schema.

## Alternatives Considered

- **Generic provider abstraction:** rejected as unnecessary for the first MVP.
- **LangChain / multi-agent stack:** rejected because the issue asks for the
  smallest official provider integration.
- **Embedding provider metadata in `PortfolioRecommendation`:** rejected because
  it would mix provider diagnostics into the domain contract.
