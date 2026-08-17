# Open Questions

## Resolved for v0.1

- The first Value Manager adapter uses the OpenAI Responses API, `OPENAI_API_KEY`, default model `gpt-5.6-terra`, and optional `OPENAI_VALUE_MANAGER_MODEL` / `OPENAI_VALUE_MANAGER_REASONING_EFFORT`.
- The operator interface is FastAPI plus Variant C. Streamlit remains a diagnostic demo UI.
- Paper benchmark fills use a persisted Twelve Data quote attributed as `twelve-data-quote-close-field`, not an official regular-session close. See ADR-006.
- Durable local persistence is SQLite via `AGENTIC_PORTFOLIO_LAB_DB_PATH`.
- Market-data and research providers are Twelve Data and Alpha Vantage.
- Research v2 screening, statement reuse, derived metrics, and operator
  OVERVIEW bootstrap (≤25 requests per invocation) have landed. Rank and slot
  role stay off the Value Manager payload. Expanding `VALUE_US_EQUITIES_V1`
  waits on operator approval.

## Still open

- What additional evidence sources should later enrich packets beyond the
  current OVERVIEW, statements, and derived metrics?
- What position-size and concentration limits should deterministic validation enforce when those policies are introduced?
- What Cash Event schedule should be used after explicitly supplied events?
- When is a constitution content hash needed in addition to its stable semantic version?
- What should trigger re-review of an existing position?
