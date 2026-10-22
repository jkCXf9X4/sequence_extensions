---
id: CP-029
type: capability
title: UC-29 Keep a run log byte-stable for reference storage
summary: reference mode: fixed_clock pins run id, timing, worker, and record order — identical runs produce byte-identical log files
date: 2026-10-19
status: current
---

# UC-29 Keep a run log byte-stable for reference storage

## Scenario

- A pipeline or test suite stores run logs as reference files — golden files committed to git.
- Every run rewrites the same node; wall-clock timestamps, durations, worker names, and completion order must not dirty the tree.
- An operator still needs real timestamps in normal runs; the mode is opt-in.

## Acceptance

- `fixed_clock` is off by default; `RunOptions(fixed_clock=True)` enables it for the top-level run.
- The run id pins to `<node>-fixed`: a sequential run overwrites the same file, no accumulation; a concurrent fixed writer raises.
- Engine-written timing pins to `1970-01-01T00:00:00+00:00`, `duration_ms` to `0`, `worker` to a constant.
- Records are written at close in canonical order — `run_start`, nodes by path / parent attempt / attempt / inputs, `run_end` — with `seq` assigned in that order.
- Nested mapping keys are sorted, mixed-type sets are ordered, and lines are strict JSON; a lone surrogate cannot break a write.
- Two identical runs produce byte-identical log files, thread and process mode alike.
- Execution facts stay real: what ran, where in the node tree, on which inputs, with which outcome.
- A fixed run rejects run-level retries; nested node fan-out is ordered by `path`, `parent_attempt`, attempt, and inputs, so the single log stays byte-identical.

## Evidence

- `tests/flow/test_runlog.py`
- `tests/flow/test_run.py`
- `tests/flow/test_hardening.py`
- `tests/e2e/test_flows.py`

## Owns

- The reference-storage need: byte-stable run logs without giving up normal-run timing.

## Excludes

- Semantic comparison of two runs: `CP-025`.
- The decision and its trade-offs: `DR-016`.
