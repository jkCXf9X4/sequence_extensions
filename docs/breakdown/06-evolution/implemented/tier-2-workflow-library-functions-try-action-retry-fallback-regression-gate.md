---
id: IMP-004
type: imp
title: Tier 2 workflow library functions: try_action, retry, fallback, regression_gate
summary: Four new library functions close the I4 retry, M5/C4 fallback, and V2 regression-gate gaps from the dynamic-scenarios analysis; try_action unblocks all error-reactive scenarios
date: 2026-10-10
status: current
---

# Tier 2 workflow library functions: try_action, retry, fallback, regression_gate

## What changed

`workflow/library.py` gains four functions, registered by `register_library`:

- **`try_action(name, params=None, registry=None, **kwargs)`** — primitive, no `dag`.
  - Resolves `name` from `registry` (default `DEFAULT_REGISTRY`), calls `fn(**params)`.
  - Success: `{"ok": True, "result": <ret>, "error": None}`.
  - Failure: `{"ok": False, "result": None, "error": str(exc)}` — exception not propagated.
  - `params` is a dict (XML `<argument>` gives strings only; a dict carries structured call params).
  - Extra kwargs (globals, upstream results) ignored — deterministic, plain history.
  - Unregistered name: raises `ValueError` (workflow error, not captured failure).
- **`retry(upstream, max_attempts, on="error", field=None, op="eq", value=None, backoff="fixed", delay=0.0, sleep=None, *, dag, **kwargs)`** — driver, copy-to-end.
  - Body = `dag.preceding()` (everything before the check in its scope).
  - Reads the latest upstream result (highest collision suffix).
  - `on="error"`: unacceptable iff the result is a `try_action` outcome with falsy `ok`. Non-`try_action` results always acceptable.
  - `on="field"`: unacceptable iff `result[field] op value` holds (the predicate describes the unacceptable result; `field` required).
  - Acceptable: returns `{"ok": True, "attempts": n}`, adapts nothing.
  - Unacceptable, attempts < `max_attempts`: appends a copy of the body plus a fresh copy of the check at the scope end; returns `{"ok": False, "attempts": n}`.
  - Unacceptable, attempts >= `max_attempts`: returns `{"ok": False, "attempts": n, "max_attempts": cap}`, adapts nothing.
  - Backoff: default `delay=0.0` pauses nothing; `delay > 0` with `backoff="fixed"` pauses `delay`, `"linear"` pauses `delay * attempts`; a `sleep` hook (callable of one float) is invoked instead of `time.sleep` — no real sleep by default.
- **`fallback(upstream, field, ok_value, *, dag, **kwargs)`** — driver, first-success.
  - Reads the latest upstream result, evaluates `result[field] == ok_value`.
  - Success: replaces **every** following sibling with an empty `Sequential()` — the rest of the chain (next alternative + its check + all later alternatives) never runs.
  - Failure: adapts nothing; the next alternative runs, its own `fallback` check re-evaluates.
  - Chain convention: one `fallback` after each alternative, each reading the alternative's own result.
  - Returns `{"fallback": {"ok": <bool>}}`.
- **`regression_gate(upstream, baseline, field, tolerance=0.0, on_regression="fail", **kwargs)`** — pure function, no `dag`.
  - Reads all collision-suffixed upstream results named `upstream`, extracts `field` from each.
  - Numeric: pass iff `abs(value - baseline) <= tolerance`; non-numeric: pass iff `==`.
  - All pass: `{"regression_gate": {"passed": True, "count": n, "deviations": {}}}`.
  - Any fail: `on_regression="fail"` raises `ValueError` naming the worst deviation; `on_regression="report"` returns `{"regression_gate": {"passed": False, "count": n, "deviations": {<result key>: <value>}}}` — deviations keyed by the engine result name (`name`, `name_2`, ...).
  - Zero results: passes trivially (`count` 0).

`docs/API.md` — the workflow library section documents all four; the adaptation driver count is eight.

## Deviations from `docs/dynamic_scenarios_analysis.md` §5

Eight deviations, all justified (each verified by repro):

- `try_action` param `function` → `name` — `function` is reserved by `Action` (kwarg collision); `dag.copy` re-instantiates `Action(node.function, **node.params)`, so a `function` param breaks cloning.
- `try_action` calls with exactly `params`, ignores other kwargs (spec: "with the given kwargs") — forwarding globals/upstream results breaks determinism and plain-data history; XML `<argument>` gives strings only, so a dict is the only structured-params route.
- `try_action` adds `registry` param (default `DEFAULT_REGISTRY`) — enables custom registries via global-parameter injection.
- `retry` adds `op="eq"` (spec's `on="field"` names only `field`) — reuses `guard`'s predicate vocabulary.
- `retry` adds `value=None` — the operand for `op`.
- `retry` `sleep` hook invoked instead of `time.sleep` — default path still really sleeps; the hook is the test seam.
- `fallback` replaces **all** following siblings (remaining alternatives AND their checks), not just "the remaining alternatives" — emptying the whole rest of the chain is the only way to guarantee "the rest never run" (a surviving next check would re-evaluate stale upstream).
- `regression_gate` `on_regression="report"` returns a `deviations` dict `{<engine result name>: <raw value>}` — spec says "return the verdict" without a shape; the dict names the producing result per deviation.

## Why

`docs/dynamic_scenarios_analysis.md` §5 Tier 2 — high value, one shared prerequisite:

- **`try_action` (root unblocker)** — the engine propagates a per-node exception out of the run; no error-reactive scenario works without a call site that turns an exception into data. `try_action` closes it; unlocks I4, M5 (error case), C4.
- **I4 (retry gap)** — flaky FMI toolchains are a real V&V pain; no way to re-run a body on failure. `retry` closes it; depends on `try_action` for `on="error"`.
- **M5/C4 (fallback gap)** — robustness is essential for V&V; no way to stop an alternatives chain on first success. `fallback` closes it; depends on `try_action` for error-triggered chains.
- **V2 (regression gate gap)** — bread and butter of V&V; no gate comparing results to a baseline within tolerance. `regression_gate` closes it.

The functions extend the dynamic adaptation capability of `INFO-001` principle 2 under the agreed design (`IMP-001`, `DR-001`, `DR-002`), following the Wave 1 precedent (`IMP-003`): scoped `DAGHandle`, strictly downstream, at-most-once, bounded by `ADAPTATION_BOUND`.

## Verification

- `tests/workflow/test_library.py` — unit tests for the four functions: capture, `on` modes, the cap, the backoff hook, the chain convention, the gate modes, error cases.
- `pb check --strict` — passes on this change.
