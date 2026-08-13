# Agentic Portfolio Lab

Agentic Portfolio Lab is a learning project for a modular, auditable
paper-trading investment workflow. It separates AI-assisted investment judgment
from deterministic portfolio accounting, validation, approval, and simulated
execution. It is not financial advice, an oracle, or a brokerage system.

## Release 1.0 MVP

The integrated MVP includes:

- immutable, Decimal-safe portfolio, trade, valuation, and performance models;
- explicit Cash Event funding for managed and SPY benchmark portfolios;
- a deterministic Passive Index Constitution that creates full-cash SPY intent;
- the Value Manager recommendation workflow and an OpenAI Responses API adapter;
- deterministic risk validation, reviewer artifacts, decision journal, and
  human approval state;
- post-approval simulated BUY execution using caller-supplied price observations;
- capital-flow-adjusted managed-versus-SPY performance tracking; and
- a Streamlit diagnostic/reference dashboard with a Decision Memo, Research
  Packet Viewer, and History & Timeline view;
- a thin, read-only FastAPI adapter over deterministic synthetic in-memory MVP
  state; and
- a Variant C-inspired static frontend that consumes that API for the current
  operator interface.

All financial state transitions are deterministic and traceable through the
domain artifacts. The OpenAI adapter produces recommendations only; it never
executes trades.

## Not implemented yet

- live market-data providers;
- automatic research retrieval or ResearchBatch assembly;
- durable weekly-run persistence;
- real brokerage execution.

## Local development

Run the deterministic test suite from the repository root:

```bash
PYTHONPATH=src pytest -q
```

Run the current synthetic, in-memory Streamlit diagnostic UI:

```bash
PYTHONPATH=src streamlit run streamlit_app.py
```

The dashboard is a diagnostic/reference UI backed by deterministic demo data;
it does not persist portfolio state or place trades. A manual OpenAI smoke test,
when present in `scripts/`, requires `OPENAI_API_KEY`; it is not part of pytest.

Run the read-only local API:

```bash
PYTHONPATH=src uvicorn agentic_portfolio_lab.api.app:app --reload
```

The API exposes the same synthetic, in-memory artifacts through explicit JSON
schemas. Decimal financial values are JSON strings, and timestamps are
timezone-aware ISO 8601 strings, so the frontend never receives lossy binary
floating-point values.

Run the current read-only frontend against the local API in a second terminal:

```bash
cd frontend
python -m http.server 8001
```

Then open <http://localhost:8001>. The frontend has no write controls and does
not approve, execute, persist, or retrieve research; it presents the current
API state only.

## Guiding idea

If normal code can do something reliably, use normal code. AI is reserved for
judgment, critique, synthesis, and explanation; deterministic code owns
financial calculations, validation, approval gates, and state transitions.
