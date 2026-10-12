---
id: INFO-002
type: info
title: Deliverables
summary: "What sequence_extensions delivers: three subpackages, the public API surface, and explicit out-of-scope items"
date: 2026-10-12
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
  - `GraphPool` drives scheduling on a bounded thread pool (default 16 workers; `run_workflow` sizes it per run).
- **`workflow`** — a V&V workflow layer built on `graph`, per the scope in `INFO-001`.
  - XML schema parsing (`parse_workflow`) and a Python API: `Action`, `Sequential`, `Parallel`, `Template`.
  - A named function registry (`FunctionRegistry`, `workflow_function`, `DEFAULT_REGISTRY`).
  - An execution engine (`run_workflow`, `Test_Framework`, `run_python_workflow`) with global parameter propagation and scope-restricted dynamic adaptation.
  - Opt-in execution history and deterministic replay (`RunHistory`, `replay`, in `workflow.history`).
  - Opt-in by-reference artifact store (`ArtifactStore`; design in `INFO-008`).
  - A shipped function library, registered via `register_library` (`workflow.library`).
  - Per-run resource configuration: `max_workers`, `adaptation_bound`, caller-owned `executor`; `dry_run` plan mode; `action_timeout` per action.

## API surface at a glance

Root re-exports (`sequence_extensions.__all__`):

- `ext`: `list_ext`, `dict_ext`, `gen_ext`, `KeyValueTuple`.
- `graph`: `GraphFuture`, `GraphPool`, `Node`, `Group`, `TreeHandle`, `graph_future`.
- `workflow`: `Action`, `Sequential`, `Parallel`, `Template`, `FunctionRegistry`, `DEFAULT_REGISTRY`, `workflow_function`, `parse_workflow`, `run_workflow`, `run_python_workflow`, `Test_Framework`, `ArtifactStore`, `ArtifactHandle`, `WalkContext`.

The `workflow` subpackage additionally exports `DAGHandle`, `AdaptationOp`, `ADAPTATION_BOUND`, `ReplayArtifacts`, `check_splice_scope`; its modules expose `RunHistory` / `replay` (`workflow.history`) and `register_library` (`workflow.library`).

## Out of scope

- Git-based change management inside model archives.
- STMD/SRMD traceability metadata.
- FMI/SSP model packaging.
- Distributed (HPC) execution; parallelism is local, via the thread pool.

Scope boundaries: `INFO-001`. Workflow engine internals: `INFO-004`.
