---
id: CP-023
type: capability
title: UC-23 Run flows concurrently in one process
summary: pool-scoped cancellation - a pool's exit cancels only its own nodes, so flows run side by side in one process
date: 2026-10-14
status: current
---

# UC-23 Run flows concurrently in one process

## Scenario

- A driver or server embeds the engine and runs two campaigns at the same time, in one process.
- Each flow owns its pool by default; a caller may share one caller-owned pool across flows.

## API

```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=2) as ex:  # two flows, side by side
    f1 = ex.submit(flow_a)
    f2 = ex.submit(flow_b)
```

- A pool's exit cancels only the nodes bound to that pool (`DR-007`).
- A shared caller-owned pool serializes binds; the owner owns the lifecycle (`CP-021`).

## Acceptance

- Two flows running concurrently in one process both complete; both logs close clean.
- Exiting one pool spares another pool's pending nodes; the spared node still completes.

## Evidence

- `tests/flow/test_flow.py::test_concurrent_flows_in_one_process`
- `tests/flow/test_process_pool.py::test_concurrent_flows_one_process_pool_per_flow`
- `tests/graph/test_graph_future.py::test_pool_exit_spares_other_pools_nodes`

## Owns

- Pool-scoped cancellation semantics and concurrent-flow safety.

## Excludes

- Pool sizing and ownership rules: `CP-021`.
- The substrate scheduler and unbound-node semantics: `INFO-011`.
