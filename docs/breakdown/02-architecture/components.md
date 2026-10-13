---
id: INFO-003
type: info
title: Components
summary: Component decomposition of ext/, graph/, flow/ — responsibilities, data flow, and interface contracts
date: 2026-10-13
status: current
---

# Components

The package decomposes into three subpackages with a strict dependency order: `flow` depends on `graph`; `ext` is self-contained.

## `ext` — sequence helpers

- **`list_ext`** — a `list` subclass; functional helpers return new `list_ext` values.
- **`dict_ext`** — a `dict` subclass; helpers operate on `(key, value)` pairs.
- **`gen_ext`** — static methods for generators and iterables.

## `graph` — the execution substrate

- **`graph_future`** — `GraphFuture`: one DAG node — a function, its arguments, and its dependencies.
  - Arguments may be other `GraphFuture` nodes; they resolve to results at run time.
  - `GraphPool` — owns a bounded `ThreadPoolExecutor`; wires, schedules, and evaluates a graph.
  - Context manager; `result(gf, timeout)` blocks on one node; cycle detection raises at bind time.

## `flow` — the audit-first engine

- **`task`** — `@task` decorator and `TaskFunction`: attempt loop (retry, backoff), per-attempt timeout, `submit()`, `TaskTimeoutError`.
- **`flow`** — `@flow` decorator: run identity, pool (owned or caller-supplied), drain, failure handling.
- **`runlog`** — `RunLog` JSON-lines writer (thread-safe) and `jsonable` serialization policy.
- **`_context`** — `RunContext` plus `ContextVar` plumbing; workers and attempt threads restore the run.

## Data flow

- Input: a decorated Python function (the flow) calling tasks directly or via `.submit()`.
- `submit()` creates a `GraphFuture` whose runner carries the attempt loop; the pool binds the reachable graph.
- Results flow along edges; the flow gathers and returns.
- Output: the flow's return value, plus `runs/<run_id>.jsonl`.

## Interface contracts

- `ext`: the three classes; methods return extended types or plain values.
- `graph`: `GraphFuture(function, *args, **kwargs)`, `result()`, `done()`; `GraphPool(max_workers)`, `result(gf)`.
- `flow`: `@task(retries, retry_delay_seconds, timeout, name)`, `task.submit(...)`, `@flow(name, max_workers, log, summary, pool)`.

Engine semantics: `INFO-011`. Scope: `INFO-001`.
