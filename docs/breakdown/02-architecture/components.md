---
id: INFO-003
type: info
title: Components
summary: Component decomposition of ext/, graph/, workflow/ — responsibilities, data flow, and interface contracts
date: 2026-10-09
status: current
---

# Components

The package decomposes into three subpackages with a strict dependency order: `workflow` depends on `graph`; `ext` is self-contained.

## `ext` — sequence helpers

- **`list_ext`** — a `list` subclass; functional helpers return new `list_ext` values.
- **`dict_ext`** — a `dict` subclass; helpers operate on `(key, value)` pairs.
- **`gen_ext`** — static methods for generators and iterables.

## `graph` — execution substrate

- **`GraphFuture`** — one DAG node: a function, its arguments, and its dependencies.
  - Arguments may be other `GraphFuture` nodes; they resolve to results at run time.
- **`GraphPool`** — owns a bounded `ThreadPoolExecutor`; wires, schedules, and evaluates a graph.
  - Context manager; `result(gf, timeout)` blocks on one node.

## `workflow` — V&V workflow layer

- **`schema`** — node classes `Action`, `Sequential`, `Parallel`, `Template`; `parse_workflow` turns XML into a node tree.
- **`registry`** — `FunctionRegistry` maps names to callables; `workflow_function` registers; `DEFAULT_REGISTRY` is the default.
- **`params`** — normalizes XML string parameters to Python values.
- **`engine`** — walks the node tree, submits each `Action` as a `GraphFuture`, and returns the final result; enforces splice scope.
- **`adaptation`** — `DAGHandle` gives a function a scoped view of the tree; writes are recorded as `AdaptationOp` and committed transactionally.
- **`history`** — opt-in `RunHistory` records per-action evidence; `replay` re-runs it deterministically.

## Data flow

- Input: workflow XML or a Python node tree.
- `parse_workflow` builds the tree; `params` normalizes values.
- The engine walks the tree and submits each `Action` as a `GraphFuture` to a `GraphPool`.
- The pool runs functions on the thread pool as dependencies complete.
- Output: the return value of the last action in the root group.

## Interface contracts

- `ext`: the three classes; methods return extended types or plain values.
- `graph`: `GraphFuture(function, *args, **kwargs)`, `result()`, `done()`; `GraphPool(max_workers)`, `result(gf)`.
- `workflow`: `Action(function, **params)`, `Sequential`/`Parallel(*children)`, `parse_workflow(xml)`, `run_workflow(xml, registry, parameters, history)`, `Test_Framework(seq, parameters, registry, history)`.

Engine internals: `INFO-004`. Scope: `INFO-001`.
