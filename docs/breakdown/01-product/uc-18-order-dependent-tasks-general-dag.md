---
id: CP-018
type: capability
title: UC-18 Order dependent tasks — general DAG
summary: Futures passed as submit arguments are dependency edges; diamonds allowed; cycles raise at submit time
date: 2026-10-13
status: current
---

# UC-18 Order dependent tasks — general DAG

## Scenario

- Evaluate needs the simulation result; aggregate needs every evaluation. A join needs two independent upstreams.

## API

```python
a = simulate.submit(case)
b = evaluate.submit(a, tolerance=0.5)  # positional future = edge
c = combine.submit(x=10, y=a)  # keyword future = edge
diamond = join.submit(left, right)  # two edges, one join
```

- Futures resolve to results before the task body runs.
- Positional and keyword arguments both take futures.
- Any DAG shape the substrate walks; diamonds included.

## Acceptance

- A dependent task never starts before its dependency settles.
- A cycle raises `ValueError` ("dependency cycle detected") at submit time, not at deadlock.

## Evidence

- `tests/flow/test_task.py::test_submit_future_argument_becomes_dependency`
- `tests/flow/test_task.py::test_submit_future_as_keyword_argument`
- `tests/graph/test_graph_future.py` — substrate edge semantics and cycle detection.

## Owns
- Edge semantics of submit arguments.

## Excludes
- The substrate's scheduling: `INFO-011`.
- Failure propagation across an edge: `CP-020` (skipped records).
