---
id: CP-022
type: capability
title: UC-22 Run CPU-bound tasks in parallel
summary: ProcessGraphPool behind the pool= seam swaps worker threads for processes; picklable tasks parallelize past the GIL, records replay in the parent
date: 2026-10-14
status: current
---

# UC-22 Run CPU-bound tasks in parallel

## Scenario

- A campaign of pure-Python computations sees no speedup from `submit()` on the default thread pool: the GIL serializes CPU-bound bodies.
- The author swaps the executor, not the code: `@flow(pool=ProcessGraphPool())` runs the same tasks in worker processes.

## API

```python
from sequence_extensions.flow import ProcessGraphPool, flow, task


@task
def crunch(n: int) -> int: ...


with ProcessGraphPool(max_workers=4) as pool:

    @flow(pool=pool, log="runs")
    def campaign(counts: list) -> list:
        futures = [crunch.submit(n) for n in counts]
        return [f.result() for f in futures]
```

- Same bind/result/exit surface as `GraphPool` (`DR-008`); `max_workers` defaults to the CPU count.
- Tasks and arguments must be picklable: module-level functions, plain data. An unpicklable payload settles its node with `ProcessDispatchError` and one `skipped` record, reason `dispatch failed`.

## Acceptance

- Two CPU-bound tasks on two processes beat the GIL-serialized wall (wall-time test with generous margin).
- Worker attempt records are buffered in the worker and written by the flow before `run_end`; the log is complete on return.
- A failed dependency skips the dependent in the parent — no process round-trip.
- `TaskTimeoutError` crosses the process boundary intact (task, timeout, attempt preserved).

## Evidence

- `tests/flow/test_process_pool.py` — results, retry and error record replay, dependency skip, dispatch failure, timeout transport, exit cancellation, wall-time gain.

## Owns
- The process-pool capability and its pickling contract.

## Excludes
- Thread-pool semantics: `CP-017`, `CP-021`.
- The recipe pattern for cluster jobs: `INFO-012`.
- Engine limits: `INFO-011`.
