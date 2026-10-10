---
id: INFO-002
type: info
title: Deliverables
summary: "What sequence_extensions delivers: three subpackages, the public API surface, and explicit out-of-scope items"
date: 2026-10-09
status: current
---

# Deliverables

`sequence_extensions` is a Python library (>=3.9, no runtime dependencies) that delivers three subpackages, all re-exported from the package root.

## Subpackages

- **`ext`** — functional helpers for built-in sequences.
  - `list_ext` extends `list` with `map`, `filter`, `reduce`, `window`, `first`/`last`, `to_string`, and set-like operations.
  - `dict_ext` extends `dict` with the same helpers over `(key, value)` pairs, plus `inverse` and `KeyValueTuple`.
  - `gen_ext` holds static helpers for generators: `to_list`, `recursive_gen`.
- **`graph`** — a dependency-graph execution substrate.
  - `GraphFuture` nodes form a DAG; each node runs a function once its dependencies complete.
  - `GraphPool` drives scheduling on a bounded thread pool (default 16 workers).
- **`workflow`** — a V&V workflow layer built on `graph`, per the scope in `INFO-001`.
  - XML schema parsing (`parse_workflow`) and a Python API: `Action`, `Sequential`, `Parallel`, `Template`.
  - A named function registry (`FunctionRegistry`, `workflow_function`, `DEFAULT_REGISTRY`).
  - An execution engine (`run_workflow`, `Test_Framework`) with global parameter propagation and scope-restricted dynamic adaptation.

## API surface at a glance

- `ext`: `list_ext`, `dict_ext`, `gen_ext`, `KeyValueTuple`.
- `graph`: `GraphFuture`, `GraphPool`.
- `workflow`: `Action`, `Sequential`, `Parallel`, `Template`, `FunctionRegistry`, `DEFAULT_REGISTRY`, `workflow_function`, `parse_workflow`, `run_workflow`, `Test_Framework`, `DAGHandle`, `AdaptationOp`, `check_splice_scope`.

## Out of scope

- Git-based change management inside model archives.
- STMD/SRMD traceability metadata.
- FMI/SSP model packaging.
- Distributed (HPC) execution; parallelism is local, via the thread pool.

Scope boundaries: `INFO-001`. Workflow engine internals: `INFO-004`.
