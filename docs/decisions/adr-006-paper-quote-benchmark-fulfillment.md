# ADR-006: Provider-attributed paper quote benchmark fulfillment

The original `passive-index-v1.0.0` constitution remains unchanged: it calls
for deployment at the next applicable regular-session close. The current
Twelve Data `/quote` adapter provides an attributable quote `close` field but
does not establish that it is that session close. Calling it one would be
false.

For local paper simulation, `passive-index-paper-v1.0.0` therefore uses
`PROVIDER_ATTRIBUTED_PAPER_QUOTE`. It deterministically invests all feasible
benchmark cash into SPY with an explicitly persisted `PriceObservation` and
retains its provider, timestamp, market date, currency, and price convention.
It makes no market-calendar, brokerage, or real-fill claim. A future
session-aware execution capability may use the original close policy again.
