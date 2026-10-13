---
id: CP-017
type: capability
title: UC-17 Run independent tasks concurrently
summary: task.submit() maps a list comprehension onto the run pool; default 16 workers; flow returns only after drain
date: 2026-10-13
status: current
---

# UC-17 Run independent tasks concurrently

## Scenario

- Six simulations, each 0.15 s of work. The campaign must run them at once, not in series.

## API

```python
sims = [simulate.submit(c) for c in cases]  # concurrent map
verdict = aggregate([s.result() for s in sims])
```

- `submit()` schedules the task on the run's pool and returns a `GraphFuture`.
- Pool default is 16 workers; `@flow(max_workers=...)` sizes it.
- Drain-on-return: the flow returns only after every submitted task settles, so the log is complete.

## Acceptance

- Wall time for six parallel 0.15 s tasks stays under 0.6 s; sequential needs at least 0.9 s.
- `max_workers=1` serializes: two 0.1 s tasks take at least 0.2 s.
- Task records carry the pool worker name.

## Evidence

- `tests/flow/test_task.py::test_submit_runs_concurrently`
- `tests/flow/test_flow.py::test_flow_max_workers_bounds_concurrency`
- `tests/flow/test_flow.py::test_flow_drains_pending_tasks_before_returning`
- `tests/flow/test_acceptance.py` — parallelism assertion on the campaign.

## Owns
- Concurrent submission and drain semantics.

## Excludes
- Pool sizing and ownership: `CP-021`.
- Dependency edges: `CP-018`.
