---
id: IMP-003
type: imp
title: Tier 1 workflow library functions: aggregate, guard, while_condition
summary: Three new library functions close the M3 aggregation, C1 guard, and I2 numeric-tolerance iteration gaps from the dynamic-scenarios analysis
date: 2026-10-10
status: current
---

# Tier 1 workflow library functions: aggregate, guard, while_condition

## What changed

`workflow/library.py` gains three functions, registered by `register_library`:

- **`aggregate(upstream, field, op, key=None, **kwargs)`** — pure function, no `dag`.
  - Reads all collision-suffixed upstream results named `upstream`.
  - Reduces each result's `field` with `op` (`sum|max|min|count|mean|all|any`).
  - `key` groups results by their `key` field first; each group is reduced separately.
  - Returns `{"aggregate": {"op", "count", "value"}}`; with `key`, a per-group `groups` dict.
  - Zero values: `count` is 0 and `value` is `None`; `all`/`any` of zero values are `True`/`False`.
- **`guard(upstream, field, op, value, on_fail="skip", *, dag, **kwargs)`** — driver.
  - Predicate `latest_upstream_result[field] op value`; ops `eq|ne|lt|le|gt|ge|in|not_in|contains`.
  - Holds: the following group runs unchanged.
  - Fails with `on_fail="skip"`: the following group is replaced with an empty `Sequential()`; the body never runs.
  - Fails with `on_fail="fail"`: raises `ValueError`.
  - Returns `{"guard": {"passed", "op"}}`.
- **`while_condition(upstream, field, op, threshold, max_iterations=None, *, dag, **kwargs)`** — driver, copy-to-end.
  - Repeats the preceding body while `field` fails `op threshold` (numeric ops `lt|le|gt|ge|eq|ne`).
  - Condition satisfied: returns `{"converged": True, "iterations": n}`, adapts nothing.
  - Not satisfied: appends a copy of the body plus a fresh copy of the check at the scope end.
  - `max_iterations` caps body runs; at the cap it returns `{"converged": False, "iterations": n, "max_iterations": cap}` and adapts nothing.
  - `iterations` counts completed body runs (the collision-suffixed upstream results).

`docs/API.md` — the workflow library section documents all three; the adaptation driver count is six.

## Why

`docs/dynamic_scenarios_analysis.md` §5 Tier 1 — build first, no prerequisites, high value:

- **M3 (aggregation gap)** — `compare_parameter_sweep`/`compare_results` return item counts only; every loop/map needs a real reduction downstream. `aggregate` closes it; no `dag` needed.
- **C1 (guard gap)** — no way to run a body only when a predicate on an upstream result holds. `guard` closes it; the most common conditional in V&V, cheap to build.
- **I2 (numeric-tolerance iteration gap)** — `check_convergence` handles a truthy field only; no comparison, no cap. `while_condition` closes it; the single most important gap in the existing four.

The functions extend the dynamic adaptation capability of `INFO-001` principle 2 under the agreed design (`IMP-001`, `DR-001`, `DR-002`): scoped `DAGHandle`, strictly downstream, at-most-once, bounded by `ADAPTATION_BOUND`.

## Verification

- `tests/workflow/test_library.py` — unit tests for the three functions: ops, grouping, `on_fail` modes, the cap, error cases.
- `pb check --strict` — passes on this change.
