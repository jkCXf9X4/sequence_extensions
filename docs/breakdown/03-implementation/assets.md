---
id: INFO-005
type: info
title: Implementation asset map
summary: File-by-file map of the sequence_extensions package, its key config, and its entry points
date: 2026-10-09
status: current
---

# Implementation asset map

The package `sequence-extensions` (v0.2.0) is a pure Python library: src layout, Python >= 3.9, MIT, zero runtime dependencies. The component design lives in `INFO-003`; the workflow engine design in `INFO-004`.

## Layout

- `pyproject.toml` — build (setuptools >= 61), version read from `__version__` in `src/sequence_extensions/__init__.py`, dev extras (pytest, pytest-cov, ruff), pytest/coverage/ruff config
- `src/sequence_extensions/__init__.py` — re-exports the full public API from the package root
- `ext/list_ext.py` — `list_ext(list)`: map, filter, reduce, window, conversions, predicates
- `ext/dict_ext.py` — `dict_ext(dict)` and `KeyValueTuple` over (key, value) pairs
- `ext/gen_ext.py` — `gen_ext` static helpers: `to_list`, `recursive_gen`
- `graph/graph_future.py` — `GraphFuture` DAG node and `GraphPool` (bounded thread pool, event-driven)
- `workflow/schema.py` — `Action` / `Sequential` / `Parallel` / `Template` nodes and the `parse_workflow` XML parser
- `workflow/registry.py` — `FunctionRegistry`, `DEFAULT_REGISTRY`, `workflow_function` decorator
- `workflow/params.py` — normalizes XML string parameters to native Python types
- `workflow/engine.py` — `run_workflow` / `Test_Framework`; walks the node tree on the graph substrate
- `workflow/history.py` — `ExecutionRecord`, `RunHistory`, `replay` / `replay_records`
- `workflow/library.py` — the paper's seven library functions and `register_library`
- `workflow/adaptation.py` — `DAGHandle`: scoped DAG reads and the commit protocol

## Entry points

- No CLI: the package ships no console scripts; the entry point is the Python API
- Public surface: root re-exports plus `run_workflow` / `Test_Framework` for workflow execution
- Workflow input: XML documents parsed by `parse_workflow`, or node trees built in Python
- Key config: `pyproject.toml` (pytest `pythonpath = ["src"]`, coverage `fail_under = 90`, ruff line-length 100)
