---
id: CP-020
type: capability
title: UC-20 Audit a run
summary: One JSON-lines file per run records run_start, every task attempt, skipped nodes, and run_end; paths log as path plus sha256
date: 2026-10-13
status: current
---

# UC-20 Audit a run

## Scenario

- A verdict must be defensible: which case ran, which failed on which attempt, what value each produced, and when.

## API

```python
@flow(log="runs")  # default: runs/<run_id>.jsonl under cwd
def campaign(cases_dir): ...
```

- One JSON-lines file per run; every record gets a monotonic `seq` and `schema`.
- `run_start`: identity, flow name, package version, flow arguments.
- One `task` record per attempt: status `ok` (with result), `error`, `timeout` (with error), or `skipped` (attempt 0 — dependency failed, or cancelled by the failed flow).
- `run_end`: status, duration, result or error.
- Paths log as `{"path": ..., "sha256": ...}` — bulky payloads return a `Path` by convention, never inlined.
- `summary=True` logs counts for long containers.
- The log is complete the moment the flow returns: drain precedes `run_end`.

## Acceptance

- The campaign run log holds 15 records: 2 bookends, 7 simulate attempts (6 cases plus one retry), 6 evaluations.
- Attempt numbering per case is correct; a failed first attempt records `error` then `ok`.
- A node whose dependency failed gets one `skipped` record.
- The log is diffable, greppable JSON; readable with `RunLog.records(path)`.

## Evidence

- `tests/flow/test_runlog.py` — serialization policy, writer thread safety.
- `tests/flow/test_flow.py` — skipped records, bookends, summary mode.
- `tests/flow/test_acceptance.py` — full log assertions.

## Owns
- The run-log record kinds and serialization policy.

## Excludes
- Retry semantics that produce the attempts: `CP-019`.
- Replay of a run: out of scope (`DR-005`).
