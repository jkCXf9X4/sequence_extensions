---
id: INFO-003
type: info
title: Components
summary: Component decomposition of ext/, graph/, flow/ — responsibilities, data flow, and interface contracts
date: 2026-10-13
status: current
---

# Components

The package decomposes into three subpackages plus two standalone modules with a strict dependency order: `flow` depends on `graph` and `config`; `flow_runner` depends on `config` and `flow`; `graph` and `ext` are config-free (stdlib only, no package imports); `config` imports nothing from the package.

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

- **`task`** — `@task` decorator and `TaskFunction`: attempt loop (retry, backoff), per-attempt timeout, `submit()`, `TaskTimeoutError`.
- **`flow`** — `@flow` decorator: run identity, pool (owned or caller-supplied), drain, failure handling.
- **`runlog`** — `RunLog` JSON-lines writer (thread-safe) and `jsonable` serialization policy.
- **`_context`** — `RunContext` plus `ContextVar` plumbing; workers and attempt threads restore the run.
- **`process_pool`** — `ProcessGraphPool`: a `GraphPool` subclass on a `ProcessPoolExecutor` (`CP-022`); workers buffer records, the parent replays them at settle time.

## `config` — external configuration

- **`config`** — `Config` frozen dataclasses (`[flow]`, `[task]`, `[pool]`, `[run]`, `[inputs]`), `from_toml` / `from_dict` loaders, `configure` / `active_config` / `reset_config` on a `ContextVar`, and the `UNSET` sentinel.
- Strict loading: unknown sections and keys are errors; values type-checked and range-checked; every constructor validates (`DR-015`).
- Precedence per parameter: explicit decorator keyword > active config > built-in default.

## `flow_runner` — the CLI

- `flow-runner` console script and `python -m` entry: load config, `configure`, import `[run] module`, scan for the `__flow__` marker, validate `[inputs]` against the flow signature, call (`CP-026`).
- Exit codes: 0 ok, 1 flow failure, 2 usage or config error.

## Data flow

- Input: a decorated Python function (the flow) calling tasks directly or via `.submit()`.
- `submit()` creates a `GraphFuture` whose runner carries the attempt loop; the pool binds the reachable graph.
- Results flow along edges; the flow gathers and returns.
- Output: the flow's return value, plus `runs/<run_id>.jsonl`.

## Interface contracts

- `ext`: the three classes; methods return extended types or plain values.
- `graph`: `GraphFuture(function, *args, **kwargs)`, `result()`, `done()`; `GraphPool(max_workers)`, `result(gf)`, `bind(gf)`.
- `flow`: `@task(retries, retry_delay_seconds, timeout, name)`, `task.submit(...)`, `@flow(name, max_workers, log, summary, pool)`; `pool=` accepts `GraphPool` or `ProcessGraphPool`.
- `config`: `Config.from_toml(path)`, `configure(config)`, `active_config()`; unset `@task` / `@flow` keywords resolve per call from the active config (`DR-015`).
- `flow_runner`: `flow-runner config.toml [--flow NAME] [--list]`.

Engine semantics: `INFO-011`. Scope: `INFO-001`.
