---
id: INFO-006
type: info
title: Test strategy
summary: How the pytest suite verifies the package — run commands, per-area coverage, and claim verification
date: 2026-10-13
status: current
---

# Test strategy

The suite is pytest (>= 8, < 9) with pytest-cov. `pytest` runs it as-is: `pyproject.toml` sets `pythonpath = ["src"]` and `testpaths = ["tests", "e2e"]`. `xfail_strict = true` makes a passing xfail a failure. The coverage floor is 90% (`fail_under = 90`); the suite holds 95.8%.

## Run

- `pytest` — full suite
- `pytest --cov=sequence_extensions --cov-report=term-missing` — suite with the coverage floor enforced
- `UPDATE_REF=1 pytest tests/e2e` — regenerate the e2e reference (after intended changes only)
- CI runs the same suite with coverage on Python 3.9 to 3.13; the routine steps live in `INFO-007`

## Areas

The suite collects 267 tests.

- `tests/test_package.py` — package-level smoke tests: root re-exports, ext methods, `GraphFuture`/`GraphPool` basics (30)
- `tests/ext/` — `list_ext` (51), `dict_ext` (44), `gen_ext` (6)
- `tests/graph/test_graph_future.py` — DAG execution, pool lifecycle, bind, pool-scoped exit, timeouts, cycle detection (27)
- `tests/flow/test_runlog.py` — serialization policy, writer thread safety (20)
- `tests/flow/test_runlog_tools.py` — reading toolkit: selection, compact account, the two-run determinism check over synthetic and real logs (25)
- `tests/flow/test_task.py` — decoration, inline execution, retry, backoff, timeout, submit semantics (28)
- `tests/flow/test_flow.py` — run identity, drain, failure handling, skipped records, caller-owned pool, concurrent flows (21)
- `tests/flow/test_process_pool.py` — process dispatch, record replay, skip and dispatch-failure records, timeout transport, exit cancellation, CPU-bound wall gain (12)
- `tests/flow/test_acceptance.py` — the benchmark campaign end to end (1)
- `tests/e2e/test_flows.py` — version comparison: two mock flows against the committed reference (`tests/e2e/ref`), logs via `RunLog.diff`, artifacts byte-for-byte (2)

## Fixtures and claim verification

- The acceptance test builds its own case files (six CSVs) and its own flake (module-state marker, reset per run)
- The e2e harness commits its reference: logs and artifact trees in `tests/e2e/ref`, regenerated with `UPDATE_REF=1`; a failure means behavior changed between versions — the diff report pinpoints where
- The e2e flows are deterministic by construction: repo-relative paths (they end up in the logs), per-run retry markers under the flow's cleaned scratch subtree, and a failing flow that drains before it raises, so no timing-dependent cancellations reach the record
- The e2e run id is pinned per flow, and its scratch (`tests/e2e/out`, one stable subtree per flow) is versioned: repeated runs leave only timing-field differences in the logs, never file churn
- Vision claims (`INFO-001`) verify by test: parallelism by wall-clock assertion, audit by 15-record log assertions, retry by attempt counts
- Use cases (`INFO-010`) each cite their evidence file in this suite
- The engine under test is `INFO-011`; the product claims it verifies are `INFO-002`
