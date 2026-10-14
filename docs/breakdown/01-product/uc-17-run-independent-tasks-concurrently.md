---
id: CP-017
type: capability
title: UC-17 Run independent tasks concurrently
summary: independent tasks inside one campaign run at the same time; the campaign returns only once every task has finished
date: 2026-10-14
status: current
---

# UC-17 Run independent tasks concurrently

## Scenario

- Six simulations, each 0.15 s of work. The campaign must run them at once, not in series.
- Each simulation is independent: none needs another's result.
- The campaign must not return while any of its work is still running.

## Acceptance

- Wall time for six parallel 0.15 s tasks stays under 0.6 s; sequential needs at least 0.9 s.
- A concurrency limit of one serializes: two 0.1 s tasks take at least 0.2 s.
- Each attempt's record names the worker that ran it.
- The campaign returns only after every task it launched has finished.

## Evidence

- `tests/flow/test_task.py::test_submit_runs_concurrently`
- `tests/flow/test_flow.py::test_flow_max_workers_bounds_concurrency`
- `tests/flow/test_flow.py::test_flow_drains_pending_tasks_before_returning`
- `tests/flow/test_acceptance.py` — parallelism assertion on the campaign.

## Owns

- The concurrent-independent-tasks need and its wall-time acceptance.

## Excludes

- How the need is met: `INFO-002` (shipped surface), `INFO-011` (engine design).
- Concurrency limits and shared-context ownership: `CP-021`.
- Dependency ordering: `CP-018`.
