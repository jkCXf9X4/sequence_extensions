---
id: INFO-010
type: info
title: Use cases
summary: The use-case catalog — 15 capability leaves (CP-001 to CP-015) concretizing the INFO-001 system goal
date: 2026-10-13
status: current
---

# Use cases

The use cases concretize the system goal in `INFO-001`. Each is a capability leaf, cited by ID. Every leaf carries a scenario, a concrete workflow (schema example or API call), acceptance, and evidence from the pytest suite. Acceptance is the requirement where the scenario alone stays ambiguous.

## Catalog

- `CP-001` — define a workflow, XML or Python; identical constructs and results.
- `CP-002` — reuse a scenario subtree; one template, two use sites, parse-time expansion.
- `CP-003` — run a campaign unattended; composite workflow, deterministic result.
- `CP-004` — execute independent tasks concurrently; barrier-proven full wave.
- `CP-005` — bound the concurrency; `max_workers`, caller-owned executor.
- `CP-006` — order dependent tasks; upstream results as positional dependencies.
- `CP-007` — adapt per item found; `find_files` fans out the declared scope.
- `CP-008` — iterate until a condition holds; `while_condition`, copy-to-end, bounded.
- `CP-009` — consolidate results into one outcome; `aggregate`, deterministic fold.
- `CP-010` — handle a failure per policy; `try_action`, `retry`, `fallback`.
- `CP-011` — gate on incomplete results; `regression_gate`, marked never passed.
- `CP-012` — bound a hung action; `action_timeout`, `ActionTimeoutError`.
- `CP-013` — record and replay a run; `RunHistory`, `replay` by re-execution.
- `CP-014` — trace data by reference; `ArtifactStore`, causal past, manifest.
- `CP-015` — inspect the plan before execution; `dry_run` returns the expanded tree.

## Owns
- The catalog index and the use-case shape.

## Excludes
- The goal text: `INFO-001`.
- Each use case's content: its own `CP-` leaf.
- Test strategy and counts: `INFO-006`.
