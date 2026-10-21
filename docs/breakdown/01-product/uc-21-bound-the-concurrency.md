---
id: CP-021
type: capability
title: UC-21 Bound the concurrency
summary: concurrent nodes never exceed a limit the caller chooses; a caller may instead supply one shared pool that serves several runs
date: 2026-10-14
status: current
---

# UC-21 Bound the concurrency

## Scenario

- A licence server allows eight simulators; the run must not exceed eight concurrent nodes.
- A caller may bring one pool and share it across runs; the runs must leave it usable.

## Acceptance

- A limit of one serializes two 0.1 s nodes to at least 0.2 s.
- Two sequential runs share one caller-supplied pool; it stays usable after each.
- A shared-pool value the run cannot use is rejected by `RunOptions` before the run starts.

## Evidence

- `tests/flow/test_run.py::test_max_workers_bounds_concurrency`
- `tests/flow/test_run.py::test_caller_owned_pool_is_reused_and_not_settled`
- `tests/flow/test_run.py::test_caller_owned_pool_is_drained_not_settled_on_error`

## Owns

- The bounded-concurrency need and shared-context ownership.

## Excludes

- How the need is met: `INFO-002` (shipped surface), `INFO-011` (engine design).
- Independent tasks at the same time: `CP-017`.
