---
id: INFO-011
type: info
title: Flow engine — decorators over the graph substrate
summary: The flow layer wraps plain functions with @task policy and @flow wiring; futures as arguments are dependency edges; the run log is the executed truth of a run
date: 2026-10-13
status: current
---

# Flow engine — decorators over the graph substrate

The flow layer (`sequence_extensions.flow`) is the audit-first engine, built on `graph.graph_future`. Locked in by `DR-005`; the substrate follow-ups (`bind`, pool-scoped cancellation) applied per `DR-007`; the process pool added per `DR-008`.

## Shape

- `@task` wraps a function: plain call runs inline (sequential); `.submit()` schedules on the run's pool.
- `@flow` wraps a function: run identity, a `GraphPool` (owned or caller-supplied), and a JSON-lines run log.
- `runlog` writes one record per event: `run_start`, one per task attempt, `run_end`.
- `_context` carries the run (identity, log, pool, submitted nodes) in a `ContextVar`; workers and attempt threads restore it — `ContextVar` values do not cross threads on their own.
- `process_pool` — `ProcessGraphPool`, a `GraphPool` subclass on a `ProcessPoolExecutor` (`CP-022`): same bind/result/exit surface, worker processes instead of threads.

## Semantics

- Retry: attempt loop inside the task wrapper; `retries` extra attempts, `retry_delay_seconds` backoff. A retrying task holds its pool worker through the sleep.
- Timeout: `timeout` bounds one attempt; the attempt runs in its own thread joined with the budget. Threads cannot be preempted — a timed-out attempt is abandoned as a daemon, its late result discarded.
- `TaskTimeoutError` (a `TimeoutError` naming the task) surfaces once attempts are exhausted.
- Edges: futures passed as submit arguments resolve to results before the body runs. General DAGs; cycles raise `ValueError` at submit.
- Serialization: paths log as path plus sha256; `summary=True` logs counts, not items.
- A `BaseException` from a task body is wrapped to `RuntimeError` — `GraphFuture` carries `Exception`s only, and the node must settle.
- Settle-time records (replayed process records, skip records) are written by the flow thread before `run_end`, never from done-callbacks: `set_result` wakes drain waiters before callbacks finish, so a callback-side write could race the log closing.

## Lifecycle

- A flow returns only after every submitted task settles (drain), so the log is complete on return.
- A failed flow cancels its own pool's pending tasks (recorded `skipped`), waits for running ones, records `run_end` error.
- A caller-owned pool is never settled: success and failure both drain; the owner owns the lifecycle.
- Default log: `runs/<run_id>.jsonl` under the working directory; `log=` picks a directory; `log=None` disables.
- Concurrent flows in one process are safe: pool exit cancels only that pool's own nodes (`DR-007`).

## Process-pool semantics

- Tasks and arguments must be picklable; module-level `@task` functions pickle (the raw function is aliased under a private module name at decoration).
- Worker attempt records buffer in the worker and replay in the flow thread before `run_end`; a dispatch or transport failure settles the node with `ProcessDispatchError` and a `skipped` record, reason `dispatch failed`.
- Dependencies resolve in the parent: a failed dependency skips the dependent without a process round-trip.
- `TaskTimeoutError` crosses the boundary intact (custom `__reduce__`).

## Accepted limits

- Drain waits for every submitted task; a task that can hang needs `timeout=`.
- Python threads cannot be preempted (see Timeout above); on a process pool, a timed-out attempt is abandoned as a daemon thread in the worker process.
- A task returning a `GraphFuture` (graph chaining) works in thread mode only.
- `task.submit()` inside a process worker is unsupported; errors must be picklable to cross the boundary.

## Owns
- The flow layer's execution model, policy semantics, and run-log record kinds.

## Excludes
- The substrate: `graph.graph_future`.
- The use-case catalog: `INFO-010`.
- Why the workflow layer was superseded: `DR-005`.
