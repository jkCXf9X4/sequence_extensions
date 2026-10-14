---
id: CP-021
type: capability
title: UC-21 Bound the concurrency
summary: concurrent tasks never exceed a limit the caller chooses; a caller may instead supply one shared execution context that serves several campaigns
date: 2026-10-14
status: current
---

# UC-21 Bound the concurrency

## Scenario

- A licence server allows eight simulators; the campaign must not exceed eight concurrent tasks.
- A caller may bring one execution context and share it across campaigns; the campaigns must leave it usable.

## Acceptance

- A limit of one serializes two 0.1 s tasks to at least 0.2 s.
- Two sequential campaigns share one caller-supplied execution context; it stays usable after each.
- A shared-context value the campaign cannot use is rejected when the campaign is defined.

## Evidence

- `tests/flow/test_flow.py::test_flow_max_workers_bounds_concurrency`
- `tests/flow/test_flow.py::test_flow_accepts_caller_owned_pool`
- `tests/flow/test_flow.py::test_caller_owned_pool_is_drained_not_settled_on_error`

## Owns

- The bounded-concurrency need and shared-context ownership.

## Excludes

- How the need is met: `INFO-002` (shipped surface), `INFO-011` (engine design).
- Independent tasks at the same time: `CP-017`.
