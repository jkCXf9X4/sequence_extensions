---
id: INFO-010
type: info
title: Use cases
summary: The use-case catalog — seven capability leaves (CP-016 to CP-022) concretizing the INFO-001 goal
date: 2026-10-13
status: current
---

# Use cases

The use cases concretize the goal in `INFO-001`. Each is a capability leaf, cited by ID. Every leaf carries a scenario, the API call, acceptance, and evidence from the pytest suite. Acceptance is the requirement where the scenario alone stays ambiguous.

The previous catalog — fifteen workflow-layer capabilities — was superseded with the layer itself (`DR-005`); list the tombstones via `pb archive list --deprecated`.

## Catalog

- `CP-016` — define a flow: decorated Python functions; no schema, no XML.
- `CP-017` — run independent tasks concurrently: submit, bounded pool, drain on return.
- `CP-018` — order dependent tasks: futures as arguments; general DAG.
- `CP-019` — retry, back off, and bound a task: attempts, wall budget, `TaskTimeoutError`.
- `CP-020` — audit a run: one JSON-lines file, attempt granularity, skipped records.
- `CP-021` — bound the concurrency: `max_workers`, caller-owned pool.
- `CP-022` — run CPU-bound tasks in parallel: `ProcessGraphPool`, pickling contract, parent-side record replay.

## Owns

- The catalog index and the use-case shape.

## Excludes

- The goal text: `INFO-001`.
- Each use case's content: its own `CP-` leaf.
- Test strategy and counts: `INFO-006`.
