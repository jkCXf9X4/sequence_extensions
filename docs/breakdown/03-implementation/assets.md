---
id: INFO-005
type: info
title: Implementation asset map
summary: File-by-file map of the sequence_extensions package, its key config, and its entry points
date: 2026-11-13
status: current
---

# Implementation asset map

The package `sequence-extensions` (v3.1.0) is a pure Python library plus one console script: src layout, Python >= 3.11, MIT, zero runtime dependencies. About 4,000 source lines. Component design lives in `INFO-003`; the flow engine design in `INFO-011`.

## Layout

- `pyproject.toml` — build (setuptools >= 61), version read from `__version__` in `src/sequence_extensions/__init__.py`, dev extras (pytest, pytest-cov, ruff, jsonschema — test-time only), package data `schemas/*.json`, pytest/coverage/ruff config, `[project.scripts] flow-runner`
- `src/sequence_extensions/__init__.py` — re-exports `ext` and `graph` from the package root
- `ext/list_ext.py` — `list_ext(list)`: map, filter, reduce, window, conversions, predicates
- `ext/dict_ext.py` — `dict_ext(dict)` and `KeyValueTuple` over (key, value) pairs
- `ext/gen_ext.py` — `gen_ext` static helpers: `to_list`, `recursive_gen`
- `graph/graph_future.py` — `GraphFuture` DAG node and `GraphPool` (bounded thread pool, event-driven, per-pool bind lock); accepts graph and plain futures (`DR-018`); `is_dependency`, `iter_postorder`, `GraphFuture.set_exception_if_pending`, `_submit_node` pool-extension seam
- `flow/__init__.py` — public surface of the flow layer
- `flow/_config/options.py` — `RunOptions` (including `node_policies`), `NodePolicy`, `UNSET`, `bind_flow_inputs`, `fill_parameters`, `_signature_parameters`
- `flow/_config/context.py` — `RunContext`, one ContextVar holding node path/attempt/worker state, attempt tokens
- `flow/_planning/dag.py` — DAG plan pass internals: `_PlanPool`, scope guards, node lookup, argument-name map
- `flow/_planning/document.py` — `flow-plan/2` document interface: `plan_document`, `plan_manifest`, `apply_override`, `execute_plan`, `diff_plans`
- `flow/_planning/schema.py` — `plan_schema()`: the draft 2020-12 schema built from plain Python data
- `schemas/flow-plan-2.schema.json` — the checked-in normative plan schema; packaged in the wheel and sdist
- `flow/_execution/node.py` — `@node`, `NodeFunction` (policy resolution, `submit()`)
- `flow/_execution/attempt.py` — `_AttemptRunner` (iterative retry/backoff/timeout loop, settlement, attempt logging, future fan-out)
- `flow/_execution/futures.py` — `FlowOutcome`, `FlowFuture`, `NodeTimeoutError` (deferred results, blocking guard)
- `flow/_execution/gather.py` — `gather` template planning/filling, cycle/depth guards, mapping and tuple-subclass shapes
- `flow/_execution/pickle.py` — node-function pickle transport (`__reduce__`/rebuild), process-pool alias
- `flow/_execution/process_pool.py` — `ProcessGraphPool` (process executor, parent-side record replay), `ProcessDispatchError`
- `flow/_execution/settle.py` — drain, owned-pool settle, worker-record replay, skip records
- `flow/_execution/run.py` — `execute_flow`, `Run`, `_RunAttempt` (top-level run identity, pool ownership, settle delegation, retries/timeout)
- `flow/_execution/_timeout.py` — `_run_with_timeout` shared timeout-thread helper
- `flow/_recording/runlog.py` — `RunLog` writer/reader (schema 2), reading toolkit, `fixed_clock` reference mode, `abandon` for late records
- `flow/_recording/records.py` — run-log record construction (node/run/skip, error field, jsonable arguments), UTC clock, safe node names, run-id shape
- `flow/_recording/serialize.py` — `jsonable`, strict JSON bytes, deterministic sets/nested keys, fixed clock constants
- `flow/_recording/diff.py` — diff identity, occurrence multiset, record comparison
- `flow_runner/__init__.py` — the `flow-runner` CLI: plan JSON loading and schema check, module import, flow selection, `execute_plan` call, exit codes
- `flow_runner/_discovery.py` — node discovery via `find_nodes` (listing is internal)
- `flow_runner/__main__.py` — `python -m sequence_extensions.flow_runner` entry

## Entry points

- CLI: `flow-runner PLAN.json --module MODULE [--flow NAME] [--log DIR]` (console script) and `python -m sequence_extensions.flow_runner`
- Public surface: root re-exports (`ext`, `graph`) plus `from sequence_extensions.flow import node, execute_flow, gather, Run, RunOptions, NodePolicy, FlowFuture, FlowOutcome, RunLog, plan_document, apply_override, execute_plan, plan_manifest, diff_plans, plan_schema`
- Run input: a root `@node` plus `RunOptions`; a `flow-plan/2` JSON document supplies inputs, node parameters/policy, and options, with the module and root selected on the command line (`CP-026`)
- Run output: `Run.result` plus `runs/<run_id>.jsonl` (default directory)
- Key config: `pyproject.toml` (pytest `pythonpath = ["src"]`, coverage `fail_under = 90`, ruff line-length 100); run-time config: one `flow-plan/2` JSON document per runner invocation
