---
id: CP-004
type: capability
title: UC-04 Execute independent tasks concurrently
summary: A parallel group declares no dependency between its children; the engine runs them concurrently
date: 2026-10-13
status: current
---

# UC-04 Execute independent tasks concurrently

## Scenario

- A campaign holds one simulation per test case; 16 cases sit in one parallel group, each child carrying its own case.
- The author declares no dependency between them.
- Specifying `parallel` IS the independence declaration — the engine establishes concurrency from the grouping alone; the workflow never states scheduling.

## Workflow

XML, declared children — one child per test case, each with its own work item:

```xml
<scope type="parallel">
  <action function="simulate">
    <argument key="case" value="case_1.csv"/>
  </action>
  <action function="simulate">
    <argument key="case" value="case_2.csv"/>
  </action>
  <!-- ... one declared child per test case -->
</scope>
```

Python, the declared form:

```python
from sequence_extensions import Action, Parallel, Test_Framework

cases = [f"case_{i}.csv" for i in range(16)]
tree = Parallel(*[Action("simulate", case=c) for c in cases])
result = Test_Framework(tree)   # default pool: 16 workers
```

## Acceptance

- The engine holds no dependency between parallel children: all run concurrently, up to the pool size.
- Parallel wall time is under half the sequential baseline (2x speed-up margin; the pool's ideal is ~16x).
- Every action runs exactly once, at every size tested: N = 16, 64, 128, 192.
- Results stay deterministic and correct under scaling; nested parallel groups covered.

## Evidence

- `tests/workflow/test_scaling.py` — exactly-once, speed-up margin, nested parallel.
- Verification instrument, never a workflow construct: the test functions meet at a `threading.Barrier(16)` that only trips when a full wave is in flight — a sequential engine times the barrier out and fails.

## Owns
- The UC-04 concretization: concurrency declared by grouping.

## Excludes
- The pool size and its configuration: `CP-005`.
- Driver-driven cloning: `CP-007`.
- The walk mechanics: `INFO-004`.
