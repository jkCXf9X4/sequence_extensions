---
id: INFO-011
type: info
title: Flow engine — decorators over the graph substrate
summary: The flow layer wraps plain functions with @task policy and @flow wiring; futures as arguments are dependency edges; the run log is the executed truth of a run
date: 2026-10-13
status: current
---

# Flow engine — decorators over the graph substrate

The flow layer (`sequence_extensions.flow`) is the audit-first engine, built on `graph.graph_future` unchanged. Locked in by `DR-005`.

## Shape

- `@task` wraps a function: plain call runs inline (sequential); `.submit()` schedules on the run's pool.
- `@flow` wraps a function: run identity, a `GraphPool` (owned or caller-supplied), and a JSON-lines run log.
- `runlog` writes one record per event: `run_start`, one per task attempt, `run_end`.
- `_context` carries the run (identity, log, pool, submitted nodes) in a `ContextVar`; workers and attempt threads restore it — `ContextVar` values do not cross threads on their own.

## Semantics

- Retry: attempt loop inside the task wrapper; `retries` extra attempts, `retry_delay_seconds` backoff. A retrying task holds its pool worker through the sleep.
- Timeout: `timeout` bounds one attempt; the attempt runs in its own thread joined with the budget. Threads cannot be preempted — a timed-out attempt is abandoned as a daemon, its late result discarded.
- `TaskTimeoutError` (a `TimeoutError` naming the task) surfaces once attempts are exhausted.
- Edges: futures passed as submit arguments resolve to results before the body runs. General DAGs; cycles raise `ValueError` at submit.
- Serialization: paths log as path plus sha256; `summary=True` logs counts, not items.
- A `BaseException` from a task body is wrapped to `RuntimeError` — `GraphFuture` carries `Exception`s only, and the node must settle.

## Lifecycle

- A flow returns only after every submitted task settles (drain), so the log is complete on return.
- A failed flow cancels its own pool's pending tasks (recorded `skipped`), waits for running ones, records `run_end` error.
- A caller-owned pool is never settled: success and failure both drain; the owner owns the lifecycle.
- Default log: `runs/<run_id>.jsonl` under the working directory; `log=` picks a directory; `log=None` disables.

## Accepted limits

- Flows run sequentially per process: pool exit cancels pending nodes process-wide (substrate `GraphPool.__exit__` walks all live nodes).
- Drain waits for every submitted task; a task that can hang needs `timeout=`.
- Python threads cannot be preempted (see Timeout above).

## Owns
- The flow layer's execution model, policy semantics, and run-log record kinds.

## Excludes
- The substrate: `graph.graph_future`.
- The use-case catalog: `INFO-010`.
- Why the workflow layer was superseded: `DR-005`.
