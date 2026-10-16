---
id: INFO-005
type: info
title: Implementation asset map
summary: File-by-file map of the sequence_extensions package, its key config, and its entry points
date: 2026-10-13
status: current
---

# Implementation asset map

The package `sequence-extensions` (v2.0.0) is a pure Python library plus one console script: src layout, Python >= 3.11, MIT, zero runtime dependencies. About 2,450 source lines. Component design lives in `INFO-003`; the flow engine design in `INFO-011`.

## Layout

- `pyproject.toml` — build (setuptools >= 61), version read from `__version__` in `src/sequence_extensions/__init__.py`, dev extras (pytest, pytest-cov, ruff), pytest/coverage/ruff config, `[project.scripts] flow-runner`
- `src/sequence_extensions/__init__.py` — re-exports `ext` and `graph` from the package root
- `ext/list_ext.py` — `list_ext(list)`: map, filter, reduce, window, conversions, predicates
- `ext/dict_ext.py` — `dict_ext(dict)` and `KeyValueTuple` over (key, value) pairs
- `ext/gen_ext.py` — `gen_ext` static helpers: `to_list`, `recursive_gen`
- `graph/graph_future.py` — `GraphFuture` DAG node and `GraphPool` (bounded thread pool, event-driven); unchanged substrate
- `config.py` — `Config` dataclasses, `from_toml` / `from_dict`, `configure` / `active_config` / `reset_config` / `use_config`, `UNSET` sentinel, `validate_task_policy` (`DR-015`)
- `flow/__init__.py` — public surface of the flow layer
- `flow/task.py` — `@task`, `TaskFunction` (attempt loop, timeout join, per-call policy resolution), `TaskTimeoutError`
- `flow/flow.py` — `@flow` (run identity, pool ownership, drain, failure handling, `__flow__` marker, `last_run`)
- `flow/runlog.py` — `RunLog` writer/reader, `jsonable` serialization policy, `SCHEMA_VERSION`
- `flow/_context.py` — `RunContext` and the `ContextVar` current-run plumbing
- `flow/process_pool.py` — `ProcessGraphPool` (process executor, parent-side record replay), `ProcessDispatchError`
- `flow_runner/__init__.py` — the `flow-runner` CLI: selection, discovery, inputs, exit codes
- `flow_runner/__main__.py` — `python -m sequence_extensions.flow_runner` entry

## Entry points

- CLI: `flow-runner config.toml` (console script) and `python -m sequence_extensions.flow_runner config.toml`
- Public surface: root re-exports (`ext`, `graph`) plus `from sequence_extensions.flow import task, flow, RunLog, Config, configure`
- Flow input: decorated Python functions; a TOML config sets defaults, selects the flow, and supplies its inputs (`CP-026`)
- Run output: the flow's return value plus `runs/<run_id>.jsonl` (default directory)
- Key config: `pyproject.toml` (pytest `pythonpath = ["src"]`, coverage `fail_under = 90`, ruff line-length 100); run-time config: one TOML file per run (`[flow]`, `[task]`, `[pool]`, `[run]`, `[inputs]`)
