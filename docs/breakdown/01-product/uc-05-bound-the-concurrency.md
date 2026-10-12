---
id: CP-005
type: capability
title: UC-05 Bound the concurrency
summary: max_workers sizes the pool; a caller-owned executor wins and is never shut down
date: 2026-10-13
status: current
---

# UC-05 Bound the concurrency

## Scenario

- A license agreement permits at most 4 concurrent simulations.
- The engineer sizes the run's pool at 4; a test barrier of 5 must then time out, proving the bound holds.

## Workflow

```python
from sequence_extensions import GraphPool, run_workflow

result = run_workflow(xml, max_workers=4)

pool = GraphPool(max_workers=4)          # caller-owned
result = run_workflow(xml, executor=pool)
# the run never shuts down a caller-owned pool
```

Related per-run knobs on `run_workflow` / `Test_Framework`:

- `max_workers` — the `GraphPool` worker count; default 16.
- `executor` — a caller-owned `GraphPool`; wins over `max_workers`, survives the run.
- `adaptation_bound` — the dynamic-node bound; default 10 000.

## Acceptance

Requirement:

- No more than `max_workers` actions are in flight at any moment.
- A caller-owned `executor` wins over `max_workers`, and the run never shuts it down.
- Threads give no speed-up for GIL-bound code; the executor seam exists for a process-pool variant (documented, not shipped).

## Evidence

- `tests/workflow/test_engine.py` — `test_max_workers_sizes_the_pool`.
- `tests/workflow/test_action_timeout.py` — `test_caller_owned_executor_is_not_shut_down_by_a_timeout`.

## Owns
- The UC-05 concretization: the concurrency bound and resource knobs.

## Excludes
- Why threads versus processes: `IMP-012`.
- Concurrency proof itself: `CP-004`.
