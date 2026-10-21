---
id: INFO-005
type: info
title: Implementation asset map
summary: File-by-file map of the sequence_extensions package, its key config, and its entry points
date: 2026-10-13
status: current
---

# Implementation asset map

The package `sequence-extensions` (v3.0.0) is a pure Python library plus one console script: src layout, Python >= 3.11, MIT, zero runtime dependencies. About 3,800 source lines. Component design lives in `INFO-003`; the flow engine design in `INFO-011`.

## Layout

- `pyproject.toml` — build (setuptools >= 61), version read from `__version__` in `src/sequence_extensions/__init__.py`, dev extras (pytest, pytest-cov, ruff), pytest/coverage/ruff config, `[project.scripts] flow-runner`
- `src/sequence_extensions/__init__.py` — re-exports `ext` and `graph` from the package root
- `ext/list_ext.py` — `list_ext(list)`: map, filter, reduce, window, conversions, predicates
- `ext/dict_ext.py` — `dict_ext(dict)` and `KeyValueTuple` over (key, value) pairs
- `ext/gen_ext.py` — `gen_ext` static helpers: `to_list`, `recursive_gen`
- `graph/graph_future.py` — `GraphFuture` DAG node and `GraphPool` (bounded thread pool, event-driven); accepts graph and plain futures (`DR-018`)
- `flow/__init__.py` — public surface of the flow layer
- `flow/_options.py` — `RunOptions`, `NodePolicy`, `UNSET`, validation and default resolution
- `flow/node.py` — `@node`, `NodeFunction` (deferred attempt state machine, future-first fan-out, `gather`, blocking guard), `NodeTimeoutError`
- `flow/run.py` — `execute_flow`, `Run` (top-level run identity, pool ownership, drain, retries/timeout)
- `flow/runlog.py` — `RunLog` writer/reader (schema 2), `jsonable`, `filter`/`summarize`/`diff`; `fixed_clock` reference mode, `abandon` for late records
- `flow/_context.py` — `RunContext`, node path/attempt/worker `ContextVar` plumbing, attempt tokens
- `flow/process_pool.py` — `ProcessGraphPool` (process executor, parent-side record replay), `ProcessDispatchError`
- `flow_runner/__init__.py` — the `flow-runner` CLI: selection, discovery, inputs, exit codes
- `flow_runner/__main__.py` — `python -m sequence_extensions.flow_runner` entry

## Entry points

- CLI: `flow-runner config.toml` (console script) and `python -m sequence_extensions.flow_runner config.toml`
- Public surface: root re-exports (`ext`, `graph`) plus `from sequence_extensions.flow import node, execute_flow, gather, Run, RunOptions, NodePolicy, FlowFuture, FlowOutcome, RunLog`
- Run input: a root `@node` plus `RunOptions`; a TOML file selects the node and supplies its inputs (`CP-026`)
- Run output: `Run.result` plus `runs/<run_id>.jsonl` (default directory)
- Key config: `pyproject.toml` (pytest `pythonpath = ["src"]`, coverage `fail_under = 90`, ruff line-length 100); run-time config: one TOML file per runner invocation (`[run]`, `[node]`, `[inputs]`)
