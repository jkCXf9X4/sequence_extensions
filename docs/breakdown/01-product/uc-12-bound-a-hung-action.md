---
id: CP-012
type: capability
title: UC-12 Bound a hung action
summary: action_timeout raises ActionTimeoutError naming the action; the default stays unbounded
date: 2026-10-13
status: current
---

# UC-12 Bound a hung action

## Scenario

- A simulator hang would deadlock an unattended campaign — the engine waits on the action's future.
- The run sets a per-action wall-clock budget; the hung action is cut off with a contextual error.

## Workflow

```python
from sequence_extensions import run_workflow

result = run_workflow(xml, action_timeout=5.0)
```

- `action_timeout` is a run option on `run_workflow` / `Test_Framework`, in seconds.
- Default `None`: the wait is unbounded, nothing changes.

## Acceptance

Requirement:

- A timed-out action raises `ActionTimeoutError` (catchable as builtin `TimeoutError`) naming the action, the timeout, and the option.
- The bound composes: parallel scope, nested parallel branches, history recording, caller-owned executors.
- A non-positive timeout is rejected at run setup.
- The tests are the suite's only wall-clock tests: they assert error type and message content, never exact timings.

## Evidence

- `tests/workflow/test_action_timeout.py` — the full timeout surface (17 tests).

## Owns
- The UC-12 concretization: the per-action time bound.

## Excludes
- Failure-as-data policies: `CP-010`.
- The substrate's `BaseException` caveat: `IMP-012`.
