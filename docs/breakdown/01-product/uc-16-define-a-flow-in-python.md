---
id: CP-016
type: capability
title: UC-16 Define a flow in Python
summary: A campaign is decorated functions — @flow and @task; no schema, no XML, plain calls run sequential
date: 2026-10-13
status: current
---

# UC-16 Define a flow in Python

## Scenario

- An engineer authors a sweep campaign as ordinary Python: discover cases, simulate each, aggregate one verdict.
- No schema, no registry, no XML. The module is the workflow; functions are the actions.

## API

```python
from pathlib import Path
from sequence_extensions.flow import flow, task


@task(retries=2, retry_delay_seconds=0.1, timeout=30.0)
def simulate(case: Path) -> dict: ...


def aggregate(evaluations: list) -> dict: ...  # plain function


@flow
def campaign(cases_dir: Path) -> dict:
    cases = sorted(cases_dir.glob("*.csv"))  # plain call: sequential
    sims = [simulate.submit(c) for c in cases]  # concurrent map
    return aggregate([s.result() for s in sims])
```

- `@task` wraps a function; called directly it runs inline in the caller's thread.
- `@flow` wraps the campaign function; it adds run identity, pool, and run log.
- Undecorated helpers stay plain functions — fan-in, gates, and drivers are user code.

## Acceptance

- A flow call returns the campaign function's return value.
- A task called outside a flow runs and returns its value, unlogged.
- Decoration validates policy: negative `retries`, negative delay, or non-positive `timeout` raise `ValueError`.

## Evidence

- `tests/flow/test_task.py` — decoration forms, inline execution, validation.
- `tests/flow/test_flow.py` — flow return value, metadata, default log.
- `tests/flow/test_acceptance.py` — the campaign end to end.

## Owns
- Authoring shape: decorators, plain calls, plain helpers.

## Excludes
- Concurrency semantics: `CP-017`.
- Retry and timeout policy: `CP-019`.
- The audit log: `CP-020`.
