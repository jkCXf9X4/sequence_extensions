---
id: CP-021
type: capability
title: UC-21 Bound the concurrency
summary: max_workers sizes the run pool; a caller-owned GraphPool is accepted and never settled by the flow
date: 2026-10-13
status: current
---

# UC-21 Bound the concurrency

## Scenario

- A licence server allows eight simulators; the campaign must not exceed eight concurrent tasks.

## API

```python
@flow(max_workers=8)
def campaign(cases_dir): ...


# or: supply the pool yourself
from sequence_extensions.graph import GraphPool

with GraphPool(max_workers=8) as shared:
    campaign_a = flow_a(pool=shared)
    campaign_b = flow_b(pool=shared)
```

- `max_workers` sizes the run's thread pool (default 16).
- A caller-owned `GraphPool` is accepted: the flow submits on it and never settles it — the owner owns its lifecycle.
- On failure, a caller-owned pool is drained, not cancelled; the flow cancels only its own pool's pending nodes.

## Acceptance

- `max_workers=1` serializes two 0.1 s tasks to at least 0.2 s.
- Two sequential flows share one caller-owned pool; it stays usable after each.
- A non-pool `pool=` value raises `TypeError` at decoration.

## Evidence

- `tests/flow/test_flow.py::test_flow_max_workers_bounds_concurrency`
- `tests/flow/test_flow.py::test_flow_accepts_caller_owned_pool`
- `tests/flow/test_flow.py::test_caller_owned_pool_is_drained_not_settled_on_error`

## Owns
- Pool sizing and ownership rules.

## Excludes
- The substrate pool itself: `INFO-011`.
- Sequential-flows limitation: `INFO-011` accepted limits.
