---
id: CP-019
type: capability
title: UC-19 Retry, back off, and bound a task
summary: retries and retry_delay_seconds drive an attempt loop inside the task wrapper; timeout bounds one attempt; TaskTimeoutError names the task
date: 2026-10-13
status: current
---

# UC-19 Retry, back off, and bound a task

## Scenario

- A simulator flakes once per case: the campaign must retry it, not crash.
- A hung simulator must not hang the campaign: a wall budget bounds it.

## API

```python
@task(retries=2, retry_delay_seconds=0.1, timeout=30.0)
def simulate(case): ...
```

- `retries` adds attempts after a failed one; `retries=2` means up to three attempts.
- `retry_delay_seconds` sleeps between attempts; the task holds its pool worker through the sleep.
- `timeout` bounds ONE attempt, per attempt, measured from attempt start.
- Exhausted retries raise the last attempt's exception.
- A timeout raises `TaskTimeoutError` — a `TimeoutError` carrying `task`, `timeout`, `attempt`.

## Acceptance

- Two failures then success with `retries=2`: three attempts, result returned.
- Exhausted retries raise the last error; attempts equal `retries + 1`.
- A 2 s sleeper with `timeout=0.1` fails within 0.5 s.
- Threads cannot be preempted: a timed-out attempt thread is abandoned as a daemon; its late result is discarded.
- A `BaseException` from a task body is wrapped to `RuntimeError` so the node settles.

## Evidence

- `tests/flow/test_task.py` — retry counts, backoff wall time, timeout promptness, per-attempt budget, wrapping.

## Owns
- Retry, backoff, and timeout policy semantics.

## Excludes
- What each attempt writes to the log: `CP-020`.
