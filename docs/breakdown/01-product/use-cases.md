---
id: INFO-010
type: info
title: Use cases
summary: The use-case catalog — ten capability leaves (CP-016 to CP-025) concretizing the INFO-001 goal
date: 2026-10-14
status: current
---

# Use cases

The use cases concretize the goal in `INFO-001`. Each is a capability leaf, cited by ID. Every leaf carries a scenario, acceptance, and evidence from the pytest suite. Acceptance is the requirement where the scenario alone stays ambiguous.

## Catalog

- `CP-016` — define a flow: a campaign authored as ordinary Python; no schema, no XML.
- `CP-017` — run independent tasks concurrently: several tasks at once; the campaign returns only when all finish.
- `CP-018` — order dependent tasks: any dependency shape, joins included; cycles rejected at declaration.
- `CP-019` — retry, back off, and bound a task: extra attempts with a pause; a wall-clock budget per attempt.
- `CP-020` — audit a run: one complete record per run — every attempt, every skip, the verdict.
- `CP-021` — bound the concurrency: never more tasks at once than the chosen limit; one shared execution context may serve several campaigns.
- `CP-022` — run CPU-bound tasks in parallel: compute-heavy work on several cores, same campaign, complete record.
- `CP-023` — run flows concurrently in one process: several campaigns at the same time in one process, without interference.
- `CP-024` — see what a run did: one compact account of a completed run — attempts, statuses, and time per task, plus the verdict — and selection of the records of interest.
- `CP-025` — verify two runs executed identically: same code and inputs, same execution — completion order, clock readings, and worker identity never count.

## Owns

- The catalog index and the use-case shape.

## Excludes

- The goal text: `INFO-001`.
- Each use case's content: its own `CP-` leaf.
- Test strategy and counts: `INFO-006`.
