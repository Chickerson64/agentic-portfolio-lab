# Development workflow

This is the human-readable Cursor multi-agent workflow for Agentic Portfolio
Lab. Cursor agents follow `.cursor/rules/`. `AGENTS.md` remains the repository
engineering contract. Git history, repository files, and `docs/` are the
durable source of truth. Chat is not.

The user should primarily communicate with the Lead.

```text
USER / PRODUCT OWNER
        ↓
LEAD ARCHITECT
        ↓
 ┌───────────────┐
 BUILDER(S)      REVIEWER
 isolated work     adversarial review
 branches/worktrees
 └───────┬───────┘
         ↓
       LEAD
         ↓
 commit / integration / release gate
```

## Lead

The Lead turns product goals into scoped tasks, finds dependencies and
overlapping contracts, delegates implementation and review, and is the
commit/integration gate.

Before implementation the Lead reports:

- GOAL
- SUCCESS CRITERIA
- DEPENDENCIES
- PARALLEL LANES
- SHARED CONTRACTS
- BRANCH/WORKTREE PLAN
- USER DECISIONS REQUIRED

Ask the user only for real product, architecture, policy, or cost decisions.
Do not silently expand scope. For small tasks, use one Builder rather than
artificial parallelism.

## Builder

Builders implement the smallest coherent change in an isolated branch or
worktree. They reuse existing contracts, add focused tests, and do not commit
unless instructed.

After implementation they report files changed, behavior, tests, verification,
limitations, and a Reviewer handoff.

## Reviewer

The Reviewer is independent and adversarial. Default: do not modify files.
Inspect the complete relevant diff, contracts, and tests. Classify findings as
BLOCKING, IMPORTANT, or OPTIONAL. If none are Blocking or Important, say the
work is ready for integration/commit.

## Git and worktrees

```text
main
  → scoped feature branch / worktree
  → Builder
  → Reviewer
  → fix / re-review
  → commit
  → integration branch when multiple lanes exist
  → integration review
  → merge main
  → release gate / tag when appropriate
```

Parallel Builders never share a working tree. Inspect overlap before
parallelizing. Small changes may use one scoped branch without extra
worktrees. No force pushes. No silent rebases of reviewed history. Do not
delete branches or worktrees without proving safety. `main` stays known-good.
Releases are tagged.

Do not commit `data/`, SQLite files, provider keys, or `ui-prototypes/`.

## Model usage

Prefer first-party Cursor models. Use the cheapest model that is reliably
capable of the task.

- Routine implementation, tests, inspection, and mechanical refactors: a
  cheaper capable Cursor model.
- Lead planning, difficult debugging, integration reasoning, and adversarial
  review: a stronger Cursor model.
- Third-party models: escalation only when the task is unusually hard or
  ambiguous, a Cursor model failed or looks wrong, an independent
  high-confidence review is valuable, or the user asks.

Custom subagents default to `model: inherit`. Do not let routine delegated
work silently switch to a third-party model. Do not sacrifice correctness,
financial invariants, provenance, or release safety to save usage.

## Release gates

Before commit, merge to `main`, or a release tag, run the applicable checks in
`.cursor/rules/60-release-gates.mdc`.
