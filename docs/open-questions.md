# Open Questions

## First MVP delivery

- Which LLM provider, model, and credential/configuration boundary will power the first real Value Manager adapter?
- What minimal operator interface will supply a Research Batch, capture a human approval decision, and display the simulated outcome: CLI, notebook, or web?
- What exact simulated-execution input represents the next applicable regular-session closing price when an approval arrives outside market hours?

## Data and evidence

- Which market-data and research sources should be evaluated for the post-MVP research-assembly pipeline?
- What sources count as acceptable evidence for claims, and how should source reliability and freshness be assessed?
- How should conflicting or unavailable upstream source data be recorded by the research assembler?

## Portfolio policy

- What position-size and concentration limits should deterministic validation enforce when those policies are introduced?
- What Cash Event schedule should be used after the MVP's explicitly supplied events?
- How many positions per active portfolio is the right starting point?

## Auditability and operations

- When should the system introduce durable persistence for Cash Events, journal entries, approvals, and executions?
- When is a constitution content hash needed in addition to its stable semantic version?
- What should trigger re-review of an existing position?

## Deferred implementation choices

- Which first UI stack should be selected once the basic dashboard issue begins?
- Which local persistence technology, if any, should be selected after the paper-trading workflow is proven?
