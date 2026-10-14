---
id: CP-023
type: capability
title: UC-23 Run flows concurrently in one process
summary: several campaigns run at the same time in one process without interfering with each other
date: 2026-10-14
status: current
---

# UC-23 Run flows concurrently in one process

## Scenario

- A program runs two campaigns at the same time, in one process — for example a server handling two requests.
- Each campaign manages its own work by default; a caller may also share one execution context across campaigns.

## Acceptance

- Both campaigns complete; each leaves a complete record of its run.
- Stopping one campaign's work does not stop the other's; the spared work still completes.

## Evidence

- `tests/flow/test_flow.py::test_concurrent_flows_in_one_process`
- `tests/flow/test_process_pool.py::test_concurrent_flows_one_process_pool_per_flow`
- `tests/graph/test_graph_future.py::test_pool_exit_spares_other_pools_nodes`

## Owns

- The concurrent-campaign need and its interference-freedom acceptance.

## Excludes

- How the need is met: `INFO-002` (shipped surface), `INFO-011` (engine design).
- Concurrency limits and shared-context ownership: `CP-021`.
