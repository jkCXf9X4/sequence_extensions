---
id: INFO-003
type: info
title: Components
summary: Component decomposition of ext/, graph/, flow/ — responsibilities, data flow, and interface contracts
date: 2026-10-13
status: current
---

# Components

The package decomposes into three subpackages plus one standalone CLI with a strict dependency order: `flow` depends on `graph`; `flow_runner` depends on `flow`; `graph` and `ext` are config-free (stdlib only, no package imports).

## `ext` — sequence helpers

- **`list_ext`** — a `list` subclass; functional helpers return new `list_ext` values.
- **`dict_ext`** — a `dict` subclass; helpers operate on `(key, value)` pairs.
- **`gen_ext`** — static methods for generators and iterables.

## `graph` — the execution substrate

- **`graph_future`** — `GraphFuture`: one DAG node — a function, its arguments, and its dependencies.
  - Arguments may be other `GraphFuture` nodes; they resolve to results at run time.
  - `GraphPool` — owns a bounded `ThreadPoolExecutor`; wires, schedules, and evaluates a graph.
  - Context manager; `result(gf, timeout)` blocks on one node; `bind(gf)` binds without touching results; cycle detection raises at bind time.
  - Pool exit cancels only the pool's own nodes (pool-scoped, `DR-007`); `_submit_node` is the dispatch seam pool subclasses redirect.

## `flow` — the audit-first engine

- **`node`** — `@node` decorator and `NodeFunction`: policy resolution, `submit()`, `__node__` marker, process alias.
- **`_futures`** — `FlowOutcome`, `FlowFuture`, `NodeTimeoutError`: deferred results, the blocking guard, and pickle transport.
- **`_gather`** — `gather`: template planning and filling; cycle/depth guards; mapping and tuple-subclass shapes.
- **`_attempt`** — `_AttemptRunner`: one iterative attempt loop (retry, backoff, per-attempt timeout), settlement, logging, and future fan-out.
- **`run`** — `execute_flow(node, ..., options=RunOptions(...))`: top-level run identity, owned or caller-supplied pool, drain, failure/retry/timeout handling, `Run`.
- **`_options`** — `RunOptions` (per-call run knobs), `NodePolicy` (per-run node defaults), `UNSET`, validation and resolution.
- **`runlog`** — `RunLog` JSON-lines writer (thread-safe, schema 2), reading toolkit (`filter`, `summarize`, `diff`), reference mode.
- **`_serialize`** — `jsonable` policy, strict JSON bytes, deterministic sets/nested keys, fixed clock constants.
- **`_diff`** — diff identity, occurrence multiset, and record comparison.
- **`_context`** — `RunContext` plus `ContextVar` plumbing: run, node path, parent attempt, attempt token, worker markers. Workers and attempt threads restore the context.
- **`process_pool`** — `ProcessGraphPool`: a `GraphPool` subclass on a `ProcessPoolExecutor` (`CP-022`); workers buffer records, the parent replays them at settle time; process workers cannot submit or return live futures.

## `flow_runner` — the CLI

- `flow-runner` console script and `python -m` entry: load and validate a TOML file, import `[run] module`, scan for the `__node__` marker, validate `[inputs]` against the node signature, call `execute_flow` (`CP-026`).
- `[run]` carries selection and run options; `[node]` becomes `RunOptions.node_defaults`; `[inputs]` are the root node's keyword arguments.
- Exit codes: 0 ok, 1 run failure, 2 usage or config error.

## Data flow

- Input: a decorated Python function (the root node) calling nodes directly or via `.submit()`; `execute_flow` opens the run.
- `submit()` creates a `GraphFuture` whose runner carries the attempt loop; the pool binds the reachable graph.
- Results flow along edges; the run gathers and returns a `Run`.
- A node body composes nodes by calling or submitting them; a returned future is awaited by the attempt, so the worker is freed and one run/log covers the tree.
- Output: the root node's return value in `Run.result`, plus `runs/<run_id>.jsonl`.

## Interface contracts

- `ext`: the three classes; methods return extended types or plain values.
- `graph`: `GraphFuture(function, *args, **kwargs)`, `result()`, `done()`; `GraphPool(max_workers)`, `result(gf)`, `bind(gf)`.
- `flow`: `@node(retries, retry_delay_seconds, timeout, name)`, `node.submit(...)`, `execute_flow(node, *args, options=RunOptions(...), **kwargs)`, `RunOptions` / `NodePolicy`.
- `flow_runner`: `flow-runner config.toml [--flow NAME] [--list]`.

Engine semantics: `INFO-011`. Scope: `INFO-001`.
