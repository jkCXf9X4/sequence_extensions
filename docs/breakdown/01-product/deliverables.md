---
id: INFO-002
type: info
title: Deliverables
summary: What sequence_extensions delivers — three subpackages, the public API surface, and explicit out-of-scope items
date: 2026-10-13
status: current
---

# Deliverables

`sequence_extensions` is a Python library (>= 3.9, no runtime dependencies) that delivers three subpackages; `ext` and `graph` re-export from the package root, `flow` is imported as its own package.

## Subpackages

- **`ext`** — functional helpers for built-in sequences.
  - `list_ext` extends `list` with `map`, `filter`, `reduce`, `window`, `first`/`last`, `to_string`, and set-like operations.
  - `dict_ext` extends `dict` with the same helpers over `(key, value)` pairs, plus `inverse` and `KeyValueTuple`.
  - `gen_ext` holds static helpers for generators: `to_list`, `recursive_gen`.
- **`graph`** — the dependency-graph execution substrate.
  - `GraphFuture` nodes form a DAG; each node runs a function once its dependencies complete.
  - `GraphPool` drives scheduling on a bounded thread pool.
- **`flow`** — the flow engine: parallel, deterministic, audited (`INFO-011`).
  - `@task` — retry (`retries`), backoff (`retry_delay_seconds`), and `timeout` policy around a function.
  - `@flow` — run identity, bounded or caller-owned pool, JSON-lines run log.
  - `RunLog` — writer and reader for the run log; `jsonable` serialization policy.
  - `ProcessGraphPool` — a `GraphPool` subclass running tasks in worker processes (`CP-022`); `ProcessDispatchError` — a payload could not reach a worker.
  - `TaskTimeoutError` — a `TimeoutError` naming the task.

## API surface at a glance

Root re-exports (`sequence_extensions.__all__`):

- `ext`: `list_ext`, `dict_ext`, `gen_ext`, `KeyValueTuple`.
- `graph`: `GraphFuture`, `GraphPool`, `graph_future`.

The `flow` package: `from sequence_extensions.flow import task, flow, RunLog, TaskTimeoutError, ProcessGraphPool, ProcessDispatchError`.

## Out of scope

- Git-based change management inside model archives.
- STMD/SRMD traceability metadata beyond the run-log record.
- FMI/SSP model packaging.
- Distributed (HPC) execution: parallelism is local (threads or processes); HPC is recipes.
- Plan-before-execution and replay: out of scope.

Scope boundaries: `INFO-001`. Flow engine internals: `INFO-011`.
