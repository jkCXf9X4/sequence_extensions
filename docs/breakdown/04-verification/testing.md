---
id: INFO-006
type: info
title: Test strategy
summary: How the pytest suite verifies the package — run commands, per-area coverage, and claim verification
date: 2026-10-13
status: current
---

# Test strategy

The suite is pytest (>= 8, < 9) with pytest-cov. `pytest` runs it as-is: `pyproject.toml` sets `pythonpath = ["src"]` and `testpaths = ["tests"]`. `xfail_strict = true` makes a passing xfail a failure. The coverage floor is 90% (`fail_under = 90`); the suite holds 95.9%.

## Run

- `pytest` — full suite
- `pytest --cov=sequence_extensions --cov-report=term-missing` — suite with the coverage floor enforced
- CI runs the same suite with coverage on Python 3.9 to 3.13; the routine steps live in `INFO-007`

## Areas

The suite collects 240 tests.

- `tests/test_package.py` — package-level smoke tests: root re-exports, ext methods, `GraphFuture`/`GraphPool` basics (30)
- `tests/ext/` — `list_ext` (51), `dict_ext` (44), `gen_ext` (6)
- `tests/graph/test_graph_future.py` — DAG execution, pool lifecycle, bind, pool-scoped exit, timeouts, cycle detection (27)
- `tests/flow/test_runlog.py` — serialization policy, writer thread safety (20)
- `tests/flow/test_task.py` — decoration, inline execution, retry, backoff, timeout, submit semantics (28)
- `tests/flow/test_flow.py` — run identity, drain, failure handling, skipped records, caller-owned pool, concurrent flows (21)
- `tests/flow/test_process_pool.py` — process dispatch, record replay, skip and dispatch-failure records, timeout transport, exit cancellation, CPU-bound wall gain (12)
- `tests/flow/test_acceptance.py` — the benchmark campaign end to end (1)

## Fixtures and claim verification

- The acceptance test builds its own case files (six CSVs) and its own flake (module-state marker, reset per run)
- Vision claims (`INFO-001`) verify by test: parallelism by wall-clock assertion, audit by 15-record log assertions, retry by attempt counts
- Use cases (`INFO-010`) each cite their evidence file in this suite
- The engine under test is `INFO-011`; the product claims it verifies are `INFO-002`
