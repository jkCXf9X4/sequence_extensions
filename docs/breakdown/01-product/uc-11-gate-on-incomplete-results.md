---
id: CP-011
type: capability
title: UC-11 Gate on incomplete results
summary: regression_gate compares against baseline; incomplete or deviating results never pass silently
date: 2026-10-13
status: current
---

# UC-11 Gate on incomplete results

## Scenario

- Every `evaluate_results` output must score `0.42` within `0.01` of the reference baseline.
- A result outside tolerance is a regression; a missing result is an incomplete outcome.

## Workflow

```xml
<action function="regression_gate">
  <argument key="upstream" value="evaluate_results"/>
  <argument key="baseline" value="0.42"/>
  <argument key="field" value="score"/>
  <argument key="tolerance" value="0.01"/>
  <argument key="on_regression" value="report"/>
</action>
```

## Acceptance

Requirement:

- `on_regression="fail"` (the default) raises `ValueError` naming the worst deviation — a fail-fast gate; the run aborts with a clear message.
- `on_regression="report"` returns `{"regression_gate": {"passed": False, "count": <n>, "deviations": {...}}}` — deviating results are marked, keyed by the engine's result name, never reported as a pass.
- Numeric gates compare numerically: XML string forms of `baseline` and `tolerance` are coerced.
- Zero results pass trivially (`count: 0`) — the plain-function convention; the summary itself never fails the run.

## Evidence

- `tests/workflow/test_library.py` — `regression_gate` over both modes, coercion, and the empty case.

## Owns
- The UC-11 concretization: the regression gate.

## Excludes
- Reduction into one value: `CP-009`.
- The engine's exception contract: `INFO-004`.
