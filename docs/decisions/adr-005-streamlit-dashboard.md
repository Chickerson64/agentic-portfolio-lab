# ADR-005: Streamlit Dashboard for the MVP

**Date:** 2026-08-13
**Status:** Accepted

## Motivation

Issue #18 needs a minimal local dashboard that can present the current portfolio
state, benchmark state, performance comparison, and latest decision summary
without introducing a heavier frontend stack.

## Decision

The first dashboard implementation uses Streamlit with a small pure
presentation layer and deterministic in-memory demo data.

## Consequences

- The dashboard can be run locally with a single command.
- Presentation logic stays separate from domain logic.
- No React, Next.js, persistence, or broker integration is introduced.
- Existing immutable domain objects and performance models remain the source of
  truth.

## Alternatives Considered

- **React / Next.js:** rejected because the repository has no frontend
  architecture yet and the MVP only needs a compact local view.
- **CLI-only reporting:** rejected because the issue explicitly asks for a
  dashboard view.
- **A custom web framework:** rejected because it adds more infrastructure than
  the first MVP requires.

## Follow-up

The later operator UI is FastAPI plus Variant C. This ADR still describes the
Streamlit diagnostic/reference dashboard, which remains demo-backed and is not
the v0.1 weekly-run interface.
