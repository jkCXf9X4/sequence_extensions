---
id: CP-016
type: capability
title: UC-16 Define a flow in Python
summary: an engineer authors a campaign as ordinary Python — functions, calls, returns; no schema, no XML
date: 2026-10-14
status: current
---

# UC-16 Define a flow in Python

## Scenario

- An engineer authors a sweep campaign as ordinary Python: discover cases, simulate each, aggregate one verdict.
- No schema, no registry, no XML. The module is the workflow; functions are the actions.
- A task must also work alone, outside any campaign, like any other function.

## Acceptance

- Calling the campaign runs it and returns the campaign's own result.
- A task used outside a campaign still runs and returns its value; it leaves no record.
- An impossible policy choice is rejected when the task is defined, before any run starts.

## Evidence

- `tests/flow/test_task.py` — decoration forms, inline execution, validation.
- `tests/flow/test_flow.py` — flow return value, metadata, default log.
- `tests/flow/test_acceptance.py` — the campaign end to end.

## Owns

- The author-in-Python need and its acceptance.

## Excludes

- How the need is met: `INFO-002` (shipped surface), `INFO-011` (engine design).
- Running tasks at the same time: `CP-017`.
- Retry and wall-budget policy: `CP-019`.
- The run's record: `CP-020`.
