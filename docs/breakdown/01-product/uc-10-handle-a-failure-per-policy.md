---
id: CP-010
type: capability
title: UC-10 Handle a failure per policy
summary: try_action captures an error as data; retry re-runs the body; fallback skips remaining alternatives
date: 2026-10-13
status: current
---

# UC-10 Handle a failure per policy

## Scenario

- A solver call fails intermittently; the campaign policy: retry it, then fall back to a second solver.
- The policy lives in the workflow definition, not in the functions.

## Workflow

```python
from sequence_extensions import Action, Sequential

retry_policy = Sequential(
    Action("try_action", name="flaky_solver", params={"case": 1}),
    Action("retry", upstream="try_action", max_attempts=3, delay=0.5, backoff="linear"),
)

alternatives = Sequential(
    Action("try_action", name="solver_a", params={"case": 1}),
    Action("fallback", upstream="try_action", field="ok", ok_value=True),
    Action("try_action", name="solver_b", params={"case": 1}),
    Action("fallback", upstream="try_action", field="ok", ok_value=True),
)
```

Behavior:

- `try_action(name, params)` calls the registered function and returns `{"ok": <bool>, "result": ..., "error": <str|None>}` — a failure becomes data, not an abort.
- `retry(upstream, max_attempts)` re-runs the preceding body while the latest result is unacceptable (copy-to-end), then returns `{"ok": ..., "attempts": <n>}`; `backoff` / `delay` control the pause.
- `fallback(upstream, field, ok_value)` evaluates `result[field] == ok_value` after each alternative; the first success replaces the remaining chain with an empty group — the later alternatives never run.
- An exception no policy captures propagates out of the run; an unresolvable registry name raises `ValueError`.

## Acceptance

- The policy is selected in the workflow definition; a failure is never silent.
- Captured outcomes are plain, comparable data — recordable in history.

## Evidence

- `tests/workflow/test_library.py` — `try_action`, `retry`, `fallback` behavior and edge rules.

## Owns
- The UC-10 concretization: failure policies.

## Excludes
- Iteration toward a numeric condition: `CP-008`.
- The hung-action wall-clock bound: `CP-012`.
