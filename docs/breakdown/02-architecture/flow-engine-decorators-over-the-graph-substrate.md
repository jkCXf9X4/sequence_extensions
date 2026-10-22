---
id: INFO-011
type: info
title: Flow engine — one node primitive over the graph substrate
summary: The flow layer wraps plain functions with @node policy; execute_flow opens a run; futures as arguments are dependency edges; the run log is the executed truth of a run
date: 2026-10-13
status: current
---

# Flow engine — one node primitive over the graph substrate

The flow layer (`sequence_extensions.flow`) is the audit-first engine, built on `graph.graph_future`. Locked in by `DR-005`; the substrate follow-ups (`bind`, pool-scoped cancellation) applied per `DR-007`; the process pool added per `DR-008`; the 3.0 composition model replaces the `@task`/`@flow` split and the global configuration. `DR-017` introduced the one-node run boundary; `DR-018` replaced its child-run mechanism with future-first node composition (`CP-030`).

## Shape

- `@node` wraps a function with policy (`retries`, `retry_delay_seconds`, `timeout`, `name`) and `.submit()`.  A plain call runs inline (sequential); `.submit()` schedules on the run's pool.
- `execute_flow(node, ..., options=RunOptions(...))` opens a top-level run: identity, a `GraphPool` (owned or caller-supplied), and a JSON-lines run log.  It returns a `Run` (`result`, `run_id`, `node`, `status`, `log`, `duration_ms`, `attempt`, `started`, `ended`, `error`, `failed_nodes`); a failure raises with `.run` attached.
- `failed_nodes` lists submitted node paths whose settled future carries an exception, including work the root never gathered; `status` remains the root verdict.
- Leaf vs composite is not declared: a node body that calls or submits other nodes is composite.  A composite may return a value or a future; a returned future settles the attempt by callback, so the worker is freed.  The whole tree is one run, one pool, and one log.
- Undecorated helpers stay plain functions; fan-in, gates, and drivers are user code.
- `runlog` writes one record per event: `run_start`, one per node attempt, `run_end`.  Schema 2 carries `path` (the node-name chain) and `parent_attempt`.  `fixed_clock` reference mode (`CP-029`, `DR-016`) is root-only and rejects run-level retries; it buffers and flushes at close — pinned timing, constant worker, canonical record and nested-key order, strict JSON — for byte-identical reference files.  A fixed path is exclusive; POSIX adds a process-level lock.
- `_context` carries the run, node path, parent attempt, attempt token (with its ancestor chain), and worker markers in `ContextVar`s; workers and deferred-attempt callbacks restore them — `ContextVar` values do not cross threads on their own.
- `process_pool` — `ProcessGraphPool`, a `GraphPool` subclass on a `ProcessPoolExecutor` (`CP-022`): same bind/result/exit surface, worker processes instead of threads.
- Internal seams: `_futures` (deferred result types), `_gather` (container planning), `_attempt` (the attempt loop), `_serialize` (JSON policy), `_diff` (semantic comparison).  The public `flow` surface is unchanged.

## Run options (`DR-015`, `CP-026`, 3.0 revision)

- There is no global configuration.  `RunOptions` travels with the call: `name`, `max_workers`, `log`, `summary`, `fixed_clock`, `pool`, run `retries` / `retry_delay_seconds` / `timeout`, and `node_defaults`.  Fields left `UNSET` take the built-in default; nothing is inherited from an enclosing run (there is none).
- `NodePolicy` is the per-run default for nodes whose decorator left `retries` / `retry_delay_seconds` / `timeout` unset.  Precedence: explicit `@node` keyword > `RunOptions.node_defaults` > built-in default.
- `pool=` accepts a caller-owned `GraphPool` or `ProcessGraphPool`; a caller-owned pool is never settled by the run.
- Pool construction takes `max_workers` explicitly (`None` means the process executor's CPU-count default); the substrate and `ext` stay config-free.
- Option values never enter run-log records; the one option that shapes the log is `fixed_clock`.

## Semantics

- Decoration validates an explicit policy: negative `retries`, negative `retry_delay_seconds`, or non-positive `timeout` raise `ValueError`.
- Retry: one iterative attempt loop; `retries` extra attempts, `retry_delay_seconds` backoff (a timer; no worker is held).  A zero delay never nests a retry on the stack.
- A failed run-log write settles the attempt as an error; it never leaves the drain waiting.
- Timeout: `timeout` bounds one attempt; the body runs in its own thread joined with the budget, and a returned future gets the remaining budget as a timer.  Threads cannot be preempted — a timed-out attempt is abandoned as a daemon, its late records (and its subtree's) are dropped, and its late result discarded.
- `NodeTimeoutError` (a `TimeoutError` naming the node) surfaces once attempts are exhausted.
- Run retries: one run file per attempt; the raised exception carries the last attempt's `Run`.
- Run timeout: bounds the whole attempt; on expiry the run's pool is cancelled, the log is abandoned, `run_end` records `timeout`, and `NodeTimeoutError` is raised.
- Edges: futures (graph or plain) passed as submit arguments resolve to results before the body runs.  General DAGs; cycles raise `ValueError` at submit.
- Futures first: a node may return a value or a future; the attempt record, retry, and timeout settle on completion.  A node body may submit; it returns the future and does not wait.  `.result()` on an incomplete future inside a node body (root or worker) raises with guidance.  `gather` resolves futures inside a value, preserving its shape.
- Serialization: paths log as path plus sha256; `summary=True` logs counts, not items.
- `jsonable` marks cyclic containers and over-deep containers; it maps non-finite floats to `{"float": ...}` and disambiguates colliding dict keys.
- The writer emits strict JSON (`allow_nan=False`) and UTF-8 bytes that survive lone surrogates.
- A `BaseException` from a node body is wrapped to `RuntimeError` — the node and the graph substrate settle instead of leaving a pending future.
- Settle-time records (replayed process records, skip records) are written by the run thread before `run_end`, never from done-callbacks: `set_result` wakes drain waiters before callbacks finish, so a callback-side write could race the log closing.

## Lifecycle

- A run returns only after every submitted node settles (drain), so the log is complete on return.
- Drain waits on a settled outcome even when a previous finalization error occurred: attempt settlement is unconditional.
- A failed run cancels its own pool's pending nodes (recorded `skipped`), waits for running ones, records `run_end` error, and re-raises.
- `failed_nodes` and `run_end.failed_nodes` expose child failures the root did not gather; `status` stays the root verdict.
- A caller-owned pool is never settled: success and failure both drain; the owner owns the lifecycle.
- Concurrent binds on one shared pool serialize; the graph walk keeps pool-level state.
- A node belongs to one pool: binding it to a second pool raises `ValueError`.
- Default log: `runs/<run_id>.jsonl` under the working directory; `RunOptions.log` picks a directory; `None` disables.
- Concurrent runs in one process are safe: pool exit cancels only that pool's own nodes (`DR-007`).
- A fixed-clock path is exclusive: a second concurrent writer raises; on POSIX an advisory lock covers separate processes.

## Process-pool semantics

- Nodes and arguments must be picklable; module-level `@node` functions pickle (each raw function is aliased under a unique private module name at decoration, so lambdas and factory closures do not collide).
- Worker attempt records buffer in the worker and replay in the run thread before `run_end`; a dispatch or transport failure settles the node with `ProcessDispatchError` and a `skipped` record, reason `dispatch failed`.
- Dependencies resolve in the parent: a failed dependency skips the dependent without a process round-trip.
- A node called directly inside a process worker still resolves unset policy from `RunOptions.node_defaults`; only `.submit()` and returning a live future are process-worker restrictions.
- `NodeTimeoutError` crosses the boundary intact (custom `__reduce__`).
- Process workers cannot submit or return live futures; process-mode fan-out is built in the parent process.  `execute_flow` inside a process worker is rejected in 3.0.

## Reading the log

- `RunLog.records` reads a log back; `filter` selects records (`record`, `node`, `status`, `attempt`, `path`); `summarize` is the compact per-path account (`CP-024`); `diff` compares two runs (`CP-025`).  All three accept a log path or a record list; the report is jsonable and stably ordered.  `run_start` also has a `node` field, so `filter(node=...)` matches it too; pass `record="node"` for attempts only.
- Diff identifies node records by path, parent attempt, attempt, and inputs (run records by kind) — never by position.  Repeated identical executions form a multiset; the nth copy carries `occurrence: n` (the first omits it), so a changed fan-out count is visible.
- `DIFF_EXCLUDE` drops record order, run identity, and wall-clock/worker fields before comparing — wall time is not a determinism claim; a future argument's `done` snapshot is ignored for the same reason.

## Accepted limits

- Drain waits for every submitted node; a node that can hang needs `timeout=`.
- `gather` accepts `dict`/`Mapping` values and orderable tuple subclasses; a custom mapping resolves to a plain dict.
- A thread a node body starts does not inherit the run `ContextVar`; calling `execute_flow` there opens a second run.  Use the same thread or propagate the context.
- `filter(node=...)` also matches `run_start`; use `record="node"` for attempts.
- The fixed-clock cross-process lock uses POSIX `flock`; on Windows only the in-process lock applies.
- Python threads cannot be preempted (see Timeout above); on a process pool, a timed-out attempt is abandoned as a daemon thread in the worker process.
- A node body running in a process worker cannot return a live future; the root body runs on the driver, where a returned future is bound in the parent.
- `node.submit()` inside a process worker is unsupported; errors must be picklable to cross the boundary.
- Nested fan-out shares the run's pool; size it with `RunOptions.max_workers`.
- Records from a timed-out attempt, including its subtree, are dropped in the parent.

## Owns
- The flow layer's execution model, policy semantics, and run-log record kinds.

## Excludes
- The substrate: `graph.graph_future`.
- The use-case catalog: `INFO-010`.
- Why the workflow layer was superseded: `DR-005`.
