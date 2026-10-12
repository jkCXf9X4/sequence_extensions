---
id: CP-008
type: capability
title: UC-08 Iterate until a condition holds
summary: while_condition repeats the declared body until the check passes; strictly downstream, bounded
date: 2026-10-13
status: current
---

# UC-08 Iterate until a condition holds

## Scenario

- A solver iteration runs until its residual drops below `1e-6`.
- The body precedes the check in the same scope (the copy-to-end pattern); the check appends a fresh body copy plus a fresh check copy per iteration.

## Workflow

```xml
<scope type="sequential">
  <action function="simulate"/>
  <action function="while_condition">
    <argument key="upstream" value="simulate"/>
    <argument key="field" value="residual"/>
    <argument key="op" value="lt"/>
    <argument key="threshold" value="0.000001"/>
    <argument key="max_iterations" value="50"/>
  </action>
</scope>
```

Semantics:

- Post-test, by necessity: the check reads the residual the body just produced, so the body precedes it — a check placed before its body raises `ValueError` (no upstream result yet). This is the direction split between driver families: producers (`find_files`, `parameter_sweep`, `CP-007`) declare work first and adapt a following body; checks (`while_condition`, `check_convergence`, `retry`) read results and copy the preceding body to the scope end (`dag.repeat()`, the paper's section 5 copy-to-end workaround).
- The comparison `result[field] <op> threshold` uses `lt` / `le` / `gt` / `ge` / `eq` / `ne`; the comparison satisfied stops the loop (`op="lt"` iterates until the residual is below tolerance).
- The function reads the LATEST upstream result (the collision-suffixed key the engine uses when the name repeats per iteration).
- `max_iterations` caps the loop before the engine bound; a non-converging body terminates at the user-facing limit.

## Acceptance

- Every action still executes at most once; each iteration is a fresh copy.
- Iteration is strictly downstream — a DAG, no loops — so the run stays deterministic.
- Result is plain data: `{"converged": <bool>, "iterations": <n>}` plus `"max_iterations"` when the cap stopped it.

## Evidence

- `tests/workflow/test_library.py` — `while_condition`, `check_convergence`, `retry` copy-to-end behavior.

## Owns
- The UC-08 concretization: bounded iteration.

## Excludes
- Retry on failure (a specialization with an error predicate): `CP-010`.
- The DAG invariant: `INFO-004`.
