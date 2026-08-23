# Agentic Portfolio Lab

Agentic Portfolio Lab is a learning project for a modular, auditable
paper-trading investment workflow. It separates AI-assisted investment judgment
from deterministic portfolio accounting, validation, approval, and simulated
execution. It is not financial advice, an oracle, or a brokerage system.

## v0.1 — Implemented

The current local weekly paper-trading loop includes:

- immutable, Decimal-safe portfolio, trade, valuation, and performance models;
- durable SQLite local-run state, including paired Cash Event funding;
- live Twelve Data price refresh for the configured candidate universe plus SPY;
- mechanical SPY benchmark fulfillment from a persisted provider-attributed quote;
- Alpha Vantage Research v2: a versioned managed universe (the operator-approved
  30-name `VALUE_US_EQUITIES_V1` snapshot), a cheap OVERVIEW screen, five
  deep research slots, statement reuse, initial-hydration OVERVIEW reuse,
  and derived metrics computed in application code;
- an explicit OVERVIEW bootstrap command that fills missing overview rows at
  most 25 Alpha Vantage requests per invocation;
- an OpenAI Value Manager adapter that consumes that research and produces one
  structured BUY or HOLD recommendation;
- deterministic risk validation, a decision journal, and human approval;
- managed paper BUY execution only after validation, approval, and executable
  readiness; HOLD is a legitimate terminal manager decision and never executes;
- a FastAPI adapter over those workflows; and
- a Variant C-inspired operator UI that reads API state and posts the existing
  commands. The frontend does not calculate fills, prices, quantities, or
  notional.

Canonical SPY identity remains `SPY` / `NYSE ARCA` / `ETF` / `USD`. Twelve Data
identity translation stays inside the adapter. Quote `close` is attributed as
`twelve-data-quote-close-field`; it is not claimed to be an official
regular-session close.

The live managed research universe is the operator-approved 30-name
`VALUE_US_EQUITIES_V1` snapshot. Live price refresh covers that universe plus
SPY.

All financial state transitions are deterministic and traceable through domain
artifacts. The OpenAI adapter produces recommendations only; it never executes
trades. There is no autonomous execution.

## Not implemented / future work

- an AI reviewer adapter;
- SELL, rebalance, or additional AI managers;
- brokerage integration or real-money execution;
- autonomous execution, scheduling, or authentication;
- export/import backups or cloud persistence;
- provider expansion beyond Twelve Data, Alpha Vantage, and OpenAI.

Unset `AGENTIC_PORTFOLIO_LAB_DB_PATH` still starts a synthetic in-memory demo
API for local UI inspection. That demo path is not the v0.1 paper-trading
workflow.

## Local development

Install the package and run the deterministic test suite from the repository
root:

```bash
PYTHONPATH=src pytest -q
```

For AI-assisted development workflow, see:

- `AGENTS.md`
- `docs/development-workflow.md`
- `.cursor/rules/`

### Durable live run

Do not commit API keys or the SQLite database. Export secrets in the shell; do
not add them to the repository.

Required for the live v0.1 workflow:

- `AGENTIC_PORTFOLIO_LAB_DB_PATH` — local SQLite file, for example
  `$PWD/data/paper-trading.sqlite3`
- `TWELVE_DATA_API_KEY`
- `ALPHA_VANTAGE_API_KEY`
- `OPENAI_API_KEY` — used by the official OpenAI SDK

Optional:

- `OPENAI_VALUE_MANAGER_MODEL` — default `gpt-5.6-terra`
- `OPENAI_VALUE_MANAGER_REASONING_EFFORT` — `low` (default), `medium`, or `high`

Initialize the durable run once. This creates paired managed and benchmark
portfolios and applies `$1000` `INITIAL_FUNDING`. The environment variable must
be set before the API process starts:

```bash
export AGENTIC_PORTFOLIO_LAB_DB_PATH="$PWD/data/paper-trading.sqlite3"
PYTHONPATH=src python -c "
from datetime import datetime, timezone
from agentic_portfolio_lab.infrastructure.sqlite_local_state import SQLiteLocalRunStore
import os
SQLiteLocalRunStore(os.environ['AGENTIC_PORTFOLIO_LAB_DB_PATH']).initialize_run(
    initialized_at=datetime.now(timezone.utc),
)
"
```

Start the API, then the frontend:

```bash
PYTHONPATH=src uvicorn agentic_portfolio_lab.api.app:app --reload
```

```bash
cd frontend
python -m http.server 8001
```

Open <http://localhost:8001>. Decimal financial values are JSON strings, and
timestamps are timezone-aware ISO 8601 strings.

The intended live workflow is:

1. initialize the durable run
2. bootstrap OVERVIEW as needed (multi-day; at most 25 Alpha Vantage requests
   per invocation; already-cached identities are skipped)
3. refresh prices
4. fulfill the SPY benchmark when an eligible quote exists
5. build research (screens the versioned universe and deep-refreshes selected
   names, reusing a recent cached OVERVIEW on initial hydration and current statements)
6. run the Value Manager
7. inspect deterministic validation
8. human approve or reject
9. execute a managed paper BUY only when the backend reports executable
   readiness

HOLD may be approved. Approval of HOLD does not create managed execution.

Additional Cash Events after initialization are optional paired contributions.
Restarting the API against the same `AGENTIC_PORTFOLIO_LAB_DB_PATH` reopens the
persisted run.

### Diagnostic Streamlit UI

```bash
PYTHONPATH=src streamlit run streamlit_app.py
```

Streamlit remains an internal diagnostic/reference UI over deterministic demo
data. It does not persist the weekly paper-trading run or place trades.

## Guiding idea

If normal code can do something reliably, use normal code. AI is reserved for
judgment, critique, synthesis, and explanation; deterministic code owns
financial calculations, validation, approval gates, and state transitions.
