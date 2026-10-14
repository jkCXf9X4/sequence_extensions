---
id: CP-019
type: capability
title: UC-19 Retry, back off, and bound a task
summary: a flaky task is tried again after a pause; a hanging task is cut off by a per-attempt wall-clock budget
date: 2026-10-14
status: current
---

# UC-19 Retry, back off, and bound a task

## Scenario

- A simulator flakes once per case: the campaign must retry it, not crash.
- A hung simulator must not hang the campaign: a wall budget bounds it.
- A retrying task waits between attempts; the pause is part of the policy.

## Acceptance

- Two failures then success: the third attempt returns the result.
- When every attempt fails, the last error is raised.
- A 2 s sleeper under a 0.1 s budget fails within 0.5 s.
- The budget bounds each attempt separately; a later attempt gets a fresh budget.
- Work that outlives its budget is abandoned; its late result never appears.

## Evidence

- `tests/flow/test_task.py` — retry counts, backoff wall time, timeout promptness, per-attempt budget, wrapping.

## Owns

- The retry, backoff, and wall-budget need and its acceptance.

## Excludes

- How the need is met: `INFO-002` (shipped surface), `INFO-011` (engine design).
- What each attempt writes to the record: `CP-020`.
