---
id: INFO-005
type: info
title: Implementation asset map
summary: File-by-file map of the sequence_extensions package, its key config, and its entry points
date: 2026-10-13
status: current
---

# Implementation asset map

The package `sequence-extensions` (v1.1.0) is a pure Python library: src layout, Python >= 3.9, MIT, zero runtime dependencies. About 2,160 source lines. Component design lives in `INFO-003`; the flow engine design in `INFO-011`.

## Layout

- `pyproject.toml` — build (setuptools >= 61), version read from `__version__` in `src/sequence_extensions/__init__.py`, dev extras (pytest, pytest-cov, ruff), pytest/coverage/ruff config
- `src/sequence_extensions/__init__.py` — re-exports `ext` and `graph` from the package root
- `ext/list_ext.py` — `list_ext(list)`: map, filter, reduce, window, conversions, predicates
- `ext/dict_ext.py` — `dict_ext(dict)` and `KeyValueTuple` over (key, value) pairs
- `ext/gen_ext.py` — `gen_ext` static helpers: `to_list`, `recursive_gen`
- `graph/graph_future.py` — `GraphFuture` DAG node and `GraphPool` (bounded thread pool, event-driven); unchanged substrate
- `flow/__init__.py` — public surface of the flow layer
- `flow/task.py` — `@task`, `TaskFunction` (attempt loop, timeout join), `TaskTimeoutError`
- `flow/flow.py` — `@flow` (run identity, pool ownership, drain, failure handling)
- `flow/runlog.py` — `RunLog` writer/reader, `jsonable` serialization policy, `SCHEMA_VERSION`
- `flow/_context.py` — `RunContext` and the `ContextVar` current-run plumbing
- `flow/process_pool.py` — `ProcessGraphPool` (process executor, parent-side record replay), `ProcessDispatchError`

## Entry points

- No CLI: the package ships no console scripts; the entry point is the Python API
- Public surface: root re-exports (`ext`, `graph`) plus `from sequence_extensions.flow import task, flow, RunLog`
- Flow input: decorated Python functions
- Run output: the flow's return value plus `runs/<run_id>.jsonl` (default directory)
- Key config: `pyproject.toml` (pytest `pythonpath = ["src"]`, coverage `fail_under = 90`, ruff line-length 100)
