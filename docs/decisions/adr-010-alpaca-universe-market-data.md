# ADR-010: Alpaca universe and market-data adapter

Status: Accepted

## Decision

Alpaca is a read-only infrastructure adapter for an immutable, broad U.S.
listed-equity universe and daily bars/latest quotes. The domain owns
`UniverseSnapshot`, eligibility rules, `SecurityIdentity`, `DailyBar`, and
`CurrentQuote`; Alpaca asset IDs, payload field names, credentials, endpoints,
and timestamp parsing remain in `infrastructure.alpaca`.

Alpaca's `us_equity` asset class is a mixed stock/ETF bucket. A refreshed
identity therefore uses the honest repository-owned type `US_EQUITY`, not
`EQUITY` or `ETF`. No symbol list is used to infer an ETF. A later consumer
that requires a stock-only managed universe must use a separately approved
reference-data classification boundary; this refresh is not wired into the
current fixed `CandidateUniverse`.

The adapter requests active `us_equity` assets and applies deterministic,
auditable rules for permitted exchange, tradability, fractionability, and
symbol syntax. Each outcome, including exclusions, is persisted in an
immutable SQLite snapshot with UTC retrieval/as-of timestamps and safe
provenance. Snapshot IDs are UTC-derived. This storage is intentionally
outside the paper-run transition graph, so an operator can refresh it before
initializing a run.

Daily bars and latest quotes use a provider-neutral protocol and validate
prices, ordering, quote spread, date bounds, pagination, and RFC 3339 source
timestamps at the adapter boundary. Alpaca request failures are sanitized:
credentials and underlying transport text are not retained as exception
causes.

## Operator refresh

With ignored local environment configuration, run:

```bash
export AGENTIC_PORTFOLIO_LAB_DB_PATH="$PWD/data/paper-trading.sqlite3"
export ALPACA_API_KEY_ID=... ALPACA_API_SECRET_KEY=...
PYTHONPATH=src python -m agentic_portfolio_lab.application.refresh_universe
```

The command accepts `--exchange`, `--allow-nontradable`,
`--require-fractionable`, and `--max-symbol-length`. It performs no order
placement and does not expose credentials to SQLite, logs, frontend, or
prompts.

## Consequences

Twelve Data and Alpha Vantage behavior remains unchanged. The new data is a
future screener input, not an instruction to research every eligible symbol or
to make any investment decision.
