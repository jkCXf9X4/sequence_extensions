---
id: CP-006
type: capability
title: UC-06 Order dependent tasks
summary: Upstream results arrive as positional dependencies; a dependent action never starts early
date: 2026-10-13
status: current
---

# UC-06 Order dependent tasks

## Scenario

- `evaluate_results` follows `simulate` in a sequential scope and consumes its result.
- The engine passes upstream results into the function call as keyword arguments.

## Workflow

```xml
<scope type="sequential">
  <action function="simulate"/>
  <action function="evaluate_results"/>
</scope>
```

How results key:

- Keyed by the producing action's function name, with a collision suffix on repeat: `simulate`, `simulate_2`, ...
- A library function reads them by name: `aggregate(upstream="simulate", ...)`, `while_condition(upstream="simulate", ...)`.

## Acceptance

- Strict order in a sequential scope: a dependent action never starts before its upstream results exist.
- A `Parallel` group is an information barrier: a branch sees neither sibling results nor sibling artifacts.
- Results fan in after the group completes; a following action reads every branch result.

## Evidence

- `tests/workflow/test_engine.py` — ordering and concurrency tests.
- `tests/workflow/test_parallel_fanout.py` — the data plane: clone results flow downstream exactly as declared results do.

## Owns
- The UC-06 concretization: dependency ordering and result flow.

## Excludes
- The artifact-plane mirror of the barrier: `CP-014`.
- The walker invariants: `INFO-004`.
