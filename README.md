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
  Packet Viewer, and History & Timeline view.

All financial state transitions are deterministic and traceable through the
domain artifacts. The OpenAI adapter produces recommendations only; it never
executes trades.

## Not implemented yet

- live market-data providers;
- automatic research retrieval or ResearchBatch assembly;
- durable weekly-run persistence;
- Variant C production frontend integration;
- a FastAPI application layer; and
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

## Guiding idea

If normal code can do something reliably, use normal code. AI is reserved for
judgment, critique, synthesis, and explanation; deterministic code owns
financial calculations, validation, approval gates, and state transitions.
