---
id: INFO-006
type: info
title: Test strategy
summary: How the pytest suite verifies the package — run commands, per-area coverage, and claim verification
date: 2026-10-13
status: current
---

# Test strategy

The suite is pytest (>= 8, < 9) with pytest-cov. `pytest` runs it as-is: `pyproject.toml` sets `pythonpath = ["src"]` and `testpaths = ["tests"]`. `xfail_strict = true` makes a passing xfail a failure. The coverage floor is 90% (`fail_under = 90`); the suite holds about 92%.

## Run

- `pytest` — full suite
- `pytest --cov=sequence_extensions --cov-report=term-missing` — suite with the coverage floor enforced
- `UPDATE_REF=1 pytest tests/e2e` — regenerate the e2e reference (after intended changes only); regeneration skips rather than passes, so it cannot self-approve
- CI runs the same suite with coverage on Python 3.11 to 3.13; the routine steps live in `INFO-007`

## Areas

The suite collects 428 tests. Every test carries exactly one level marker
(`level_unit`, `level_component`, `level_integration`, `level_system`); the
timing-sensitive set carries `flaky_timing` and is excluded from the default
gate.

- `tests/test_package.py` — package-level smoke tests: root re-exports, ext methods, `GraphFuture`/`GraphPool` basics (30)
- `tests/ext/` — `list_ext` (51), `dict_ext` (44), `gen_ext` (6)
- `tests/graph/test_graph_future.py` — DAG execution, pool lifecycle, bind, pool-scoped exit, timeouts, cycle detection, concurrent binds, cancellation before execution (33)
- `tests/flow/test_node.py` — decoration, inline execution, retry, backoff, timeout, submit semantics, worker fan-out, root-and-worker blocking guard, plain-future return/dependency, exports, policy type validation, argument-name collisions, node defaults (43)
- `tests/flow/test_run.py` — run identity, drain, failure handling, skipped records, caller-owned pool, concurrent runs, run-level retries, run timeout, fixed ids (29)
- `tests/flow/test_nested.py` — three-level node nesting, future-first fan-out at one worker, inline fan-out, gather forms, shape-preserving gather (dict/nested/tuple/set/namedtuple) + dependency, composite retry/timeout/failure, drain of a pending subtree, fixed-clock determinism (16)
- `tests/flow/test_options.py` — `RunOptions`/`NodePolicy` validation and resolution (7)
- `tests/flow/test_runlog.py` — serialization policy, writer thread safety, schema 2, abandon, reference mode, reserved fields (25)
- `tests/flow/test_runlog_tools.py` — reading toolkit: selection, compact account, two-run determinism, synthetic and real logs (25)
- `tests/flow/test_process_pool.py` — process dispatch, record replay, skip and dispatch-failure records, timeout transport, exit cancellation, execute_flow/submit/future rejection in workers, node defaults on direct calls, gather template pickling, CPU-bound wall gain (17)
- `tests/flow/test_acceptance.py` — the benchmark campaign end to end (1)
- `tests/flow/test_hardening.py` — stress regressions: hang-free settlement, iterative retries, unique process aliases, BaseException settlement, hash-seed-stable fixed logs, fixed-log locking, diff occurrence counting, strict JSON, `failed_nodes`, cross-pool rejection, runner `options`, ordered `intersect`/`union`, log key collisions, mapping gather (40)
- `tests/flow/test_settle.py` — outcome drain: deferred outcome keeps the run open, fast/slow/late nodes all recorded, deferred retry attempts preserved (3)
- `tests/flow/test_process_failure.py` — worker exit, unpicklable payload, submit failure, cancelled worker future, timeout-vs-process behaviour (5)
- `tests/flow/test_cancellation.py` — submit after abandon, cancel before attempt, abandoned parent settlement, cancelled-run submit (4)
- `tests/flow/test_position.py` — root-vs-wrapped position independence, moved out of e2e (1)
- `tests/runner/test_runner.py` — TOML selection, strict validation, node discovery, exit codes (20)
- `tests/e2e/test_flows.py` — version comparison: two mock runs against the committed reference (`tests/e2e/ref`), validated by a hand-written oracle that imports nothing from the package; artifacts byte-for-byte; regeneration is a separate phase (9)

## Fixtures and claim verification

- The acceptance test builds its own case files (six CSVs) and its own flake (module-state marker, reset per run)
- The e2e harness commits its reference: logs and artifact trees in `tests/e2e/ref`, regenerated with `UPDATE_REF=1`; a failure means behavior changed between versions — the diff report pinpoints where
- The e2e flows are deterministic by construction: repo-relative paths (they end up in the logs), per-run retry markers under the flow's cleaned scratch subtree, and a failing flow that drains before it raises, so no timing-dependent cancellations reach the record
- The e2e run id and clock are pinned per root node; its scratch (`tests/e2e/out`, one stable subtree per run) is git-ignored, so a repeated run or a crash mid-run never modifies tracked files
- The e2e oracle is independent of the engine under test: it parses the JSON log itself, checks `seq` contiguity, record kinds and status vocabulary, and compares artifact bytes; `RunLog.diff` is kept only as a second, weaker gate
- Vision claims (`INFO-001`) verify by test: parallelism by an in-flight counter (peak equals `max_workers`), audit by node-record assertions, retry by attempt counts
- Use cases (`INFO-010`) each cite their evidence file in this suite
- Stress-hardening findings (`INFO-014`) each cite a regression test in `tests/flow/test_hardening.py`
- The engine under test is `INFO-011`; the product claims it verifies are `INFO-002`
