"""
The V&V workflow library: the paper's library functions, shipped.

This module is the concrete home of the deterministic library functions
specified by the paper "Automation Nation: Taming Complex V&V Workflows"
(16th International Modelica & FMI Conference, September 2025, Lucerne,
Switzerland; DOI 10.3384/ecp218751).  It is the embodiment of the
package's design principle that *complexity lives in the library, not the
schema*: the schema (``Action`` / ``Sequential`` / ``Parallel``) stays
minimal, and the reusable, deterministic building blocks of a V&V workflow
ship here, ready to be addressed by name from XML or the Python API.

The functions
-------------

* :func:`find_files` — file discovery and dynamic-adaptation driver
  (paper Listing 5, objective 1): clones the declared downstream scope
  once per found file (``dag.fan_out``).
* :func:`simulate` — a placeholder simulation that echoes its parameters.
* :func:`evaluate_results` — a deterministic summary of one simulation's
  upstream results.
* :func:`find_test_cases` — discovery of the test-case files under a path.
* :func:`parameter_sweep` — dynamic-adaptation driver (paper Listing 9,
  objective 1): clones the declared downstream scope once per sweep value
  (``dag.fan_out``).
* :func:`compare_parameter_sweep` — a deterministic summary of a sweep's
  results.
* :func:`compare_results` — a deterministic summary of the final results.
* :func:`evaluate_goal` — branching driver (paper objective 2): selects the
  named alternative of the declared downstream alternatives scope based on
  an upstream result field (``dag.select``); the unselected alternatives
  never run.
* :func:`check_convergence` — iteration driver (paper objective 2): while
  the upstream result field is not converged, appends a copy of the
  iteration body plus a fresh copy of the check at the scope end
  (``dag.repeat()``, the paper's section 5 copy-to-end workaround);
  returns a plain-data summary when converged.
* :func:`aggregate` — pure function (no ``dag``): reduces the ``field``
  value of every collision-suffixed upstream result named ``upstream``
  with an operation (``sum``/``max``/``min``/``count``/``mean``/``all``/
  ``any``), optionally grouped by a key field.
* :func:`guard` — conditional driver: runs the declared downstream scope
  only when a predicate on the latest upstream result holds; otherwise
  skips it via ``dag.skip()`` (the body never runs) or raises.
* :func:`while_condition` — iteration driver: repeats the preceding body
  while the latest upstream result's ``field`` fails a threshold
  comparison (the numeric-tolerance generalization of
  :func:`check_convergence`), with a user-facing ``max_iterations`` cap;
  iterates via ``dag.repeat()``.
* :func:`try_action` — error-capturing primitive (no ``dag``): invokes a
  named registered function and returns ``{"ok": bool, "result", "error"}``
  instead of propagating the exception — the root unblocker for
  error-reactive scenarios (the engine itself propagates per-node
  exceptions).
* :func:`retry` — iteration driver: re-runs the preceding body up to
  ``max_attempts`` when the latest upstream result is unacceptable (an
  error captured by :func:`try_action`, or a result-field predicate),
  with an optional backoff hook between attempts (``dag.repeat()``).
* :func:`fallback` — conditional driver: after each alternative in the
  following chain, when the latest upstream result's ``field`` equals
  ``ok_value``, skips every following sibling via ``dag.skip_following()``
  (first-success).
* :func:`regression_gate` — pure function (no ``dag``): compares each
  collision-suffixed upstream result's ``field`` to a ``baseline`` within
  ``tolerance`` and raises on regression (a V&V gate).
* :func:`randomize_scenarios` — pure function (no ``dag``): generates
  ``count`` randomized scenario values from a dedicated stdlib RNG seeded
  with ``seed`` (the paper's P16 / UC2 randomization with stored
  recreation metadata — the ``method`` and ``seed`` are declared
  parameters, so they are recorded in the run history and the campaign
  is repeatable).

Every function is deterministic (no unseeded randomness, no I/O beyond
the file discovery the paper's examples require) and stdlib-only.
:func:`randomize_scenarios` is the one seeded-randomness exception: it
is deterministic FOR A GIVEN SEED (the same ``(method, seed, count,
options)`` always yields the same list, in the same process or a fresh
interpreter), which is exactly the reproducibility contract the paper's
UC2 requires — the seed is the declared parameter, not hidden state.
Every function tolerates extra keyword arguments: the engine passes
global parameters (e.g. ``model``) and upstream results alongside each
action's own parameters, and the functions ignore what they do not need.

The eight adaptation drivers (``find_files``, ``parameter_sweep``,
``evaluate_goal``, ``check_convergence``, ``guard``, ``while_condition``,
``retry``, ``fallback``)
declare a ``dag`` parameter: the
engine injects a scoped :class:`~.adaptation.DAGHandle` into them, and they
adapt the workflow through the handle's intent-level combinators
(``fan_out`` / ``select`` / ``skip`` / ``skip_following`` / ``repeat``) —
they never build nodes themselves.  Their own return value (a plain
file/value list, an alternative name, or a convergence summary) is what
flows downstream as their result.

Registration
------------

The functions are **not** registered into :data:`.registry.DEFAULT_REGISTRY`
at import time.  Importing this module has no side effects on the default
registry, so a fresh interpreter still sees an empty ``DEFAULT_REGISTRY``
(the pinned contract asserted by ``tests/workflow/test_registry.py``).
Instead, call :func:`register_library` to opt in::

    from sequence_extensions.workflow import register_library
    register_library()          # into DEFAULT_REGISTRY
    register_library(my_reg)    # into your own FunctionRegistry

``register_library`` is idempotent: re-registering the same function
objects is a silent no-op, so calling it more than once (or importing the
module and then registering) never emits a replacement warning.  The
functions are also directly importable and callable without any
registration, for use outside the engine.
"""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any, Callable

from .adaptation import DAGHandle
from .params import coerce_value, normalize_values
from .registry import DEFAULT_REGISTRY, FunctionRegistry

__all__ = [
    "find_files",
    "simulate",
    "evaluate_results",
    "find_test_cases",
    "parameter_sweep",
    "compare_parameter_sweep",
    "compare_results",
    "evaluate_goal",
    "check_convergence",
    "aggregate",
    "guard",
    "while_condition",
    "try_action",
    "retry",
    "fallback",
    "regression_gate",
    "randomize_scenarios",
    "register_library",
]

# --------------------------------------------------------------------------- #
# The library functions
# --------------------------------------------------------------------------- #


def find_files(
    path: str | Path,
    pattern: str = "*.csv",
    *,
    dag: DAGHandle,
    parallel: bool | str = False,
    **kwargs: Any,
) -> list[str]:
    """
    Find files under ``path`` matching ``pattern`` and drive the declared
    downstream scope once per file.

    This is the dynamic-adaptation driver of the paper's Listing 5
    (objective 1: adaptation to unknown factors).  The action must be
    followed by the scope it adapts (the declared downstream group, e.g.
    the ``simulate`` + ``evaluate_results`` pair); the function CLONES that
    declared scope once per found file and splices the clones in place of
    the declared scope (``dag.fan_out``), so each found file gets its own
    copy of the declared actions.  The function never builds nodes
    itself — it adapts the declared ones.

    ``path`` may be a string or a ``pathlib.Path``; ``pattern`` is a glob
    pattern matched directly under ``path`` (default ``"*.csv"``).  Files
    are processed in sorted order for determinism.

    ``parallel`` (default ``False``) runs the per-file clones
    concurrently: the declared downstream scope must then be a
    ``<scope type="parallel">`` group, and each of its declared children
    is replaced by one clone per file (``dag.fan_out_parallel``), so the
    clones run as direct children of the parallel group.  XML strings
    ``"true"`` / ``"false"`` (any case) are accepted and normalized, so
    the option can be set from an ``<argument>``.  With ``parallel=True``
    the per-file clones run concurrently; with the default they run one
    after another, in sorted file order.

    Returns the list of found file paths (the plain result that flows
    downstream as this action's result).  When no file matches, nothing is
    adapted and the declared scope runs once, as declared.
    """
    files = sorted(str(p) for p in Path(path).glob(pattern))
    if files:
        if _as_bool(parallel, "find_files"):
            dag.fan_out_parallel([{"file": f} for f in files])
        else:
            dag.fan_out([{"file": f} for f in files])
    return files


def simulate(**params: Any) -> dict[str, Any]:
    """
    Run a placeholder simulation.

    Deterministic: the result is ``{"simulate": <params>}`` where
    ``<params>`` is exactly the set of keyword arguments the engine passed
    (the action's own parameters, global parameters, and any upstream
    results).
    """
    return {"simulate": dict(params)}


def evaluate_results(**params: Any) -> dict[str, dict[str, int]]:
    """
    Summarize the upstream results of one simulation.

    Consumes the upstream results the engine passes in (typically the
    ``simulate`` result) and returns a small deterministic summary: the
    item count of each upstream result, keyed by the name the engine used
    for it.
    """
    return {"evaluate_results": _summary(_upstream_results(params))}


def find_test_cases(path: str | Path, **kwargs: Any) -> list[str]:
    """
    Find the test-case files (``*.csv``) directly under ``path``.

    ``path`` may be a string or a ``pathlib.Path``.  Returns the file paths
    as strings in sorted order (deterministic); empty if no file matches.
    """
    return sorted(str(p) for p in Path(path).glob("*.csv"))


def parameter_sweep(
    parameter_name: str | None = None,
    values: str | list | tuple | None = None,
    *,
    dag: DAGHandle,
    parallel: bool | str = False,
    **kwargs: Any,
) -> list[Any]:
    """
    Drive the declared downstream scope once per sweep value.

    This is the dynamic-adaptation driver of the paper's Listing 9
    (objective 1: adaptation to unknown factors).  The action must be
    followed by the scope it adapts (the declared downstream group, e.g. a
    single ``simulate`` action); the function CLONES that declared scope
    once per sweep value and splices the clones in place of the declared
    scope (``dag.fan_out``), so each sweep value gets its own copy of the
    declared actions.  The function never builds nodes itself — it adapts
    the declared ones.

    ``parameter_name`` is the name of the parameter to sweep.  ``values`` is
    accepted either as a comma-separated string (``"5, 10, 15"``) or as a
    list (``[5, 10, 15]``); string items are stripped, empty items are
    dropped, and numeric strings are converted to ``int`` (or ``float``).

    ``parallel`` (default ``False``) runs the per-value clones
    concurrently: the declared downstream scope must then be a
    ``<scope type="parallel">`` group, and each of its declared children
    is replaced by one clone per value (``dag.fan_out_parallel``), so the
    clones run as direct children of the parallel group.  XML strings
    ``"true"`` / ``"false"`` (any case) are accepted and normalized, so
    the option can be set from an ``<argument>``.  With ``parallel=True``
    the per-value clones run concurrently; with the default they run one
    after another, in sweep order.

    Returns the list of sweep values (the plain result that flows
    downstream as this action's result).  When there are no values, nothing
    is adapted and the declared scope runs once, as declared.

    Raises ``ValueError`` if ``parameter_name`` is not given.
    """
    if parameter_name is None:
        raise ValueError("parameter_sweep requires 'parameter_name'")
    sweep_values = normalize_values(values)
    if sweep_values:
        if _as_bool(parallel, "parameter_sweep"):
            dag.fan_out_parallel([{parameter_name: v} for v in sweep_values])
        else:
            dag.fan_out([{parameter_name: v} for v in sweep_values])
    return sweep_values


def compare_parameter_sweep(**params: Any) -> dict[str, dict[str, int]]:
    """
    Summarize the results of a parameter sweep.

    Consumes the upstream ``simulate`` results (one per sweep value) and
    returns a small deterministic summary: the item count of each upstream
    result, keyed by the name the engine used for it.
    """
    return {"compare_parameter_sweep": _summary(_upstream_results(params))}


def compare_results(**params: Any) -> dict[str, dict[str, int]]:
    """
    Summarize the final results of a workflow.

    Consumes the upstream results the engine passes in (typically the
    ``compare_parameter_sweep`` result) and returns a small deterministic
    summary: the item count of each upstream result, keyed by the name the
    engine used for it.
    """
    return {"compare_results": _summary(_upstream_results(params))}


def evaluate_goal(
    upstream: str,
    field: str,
    default: str | None = None,
    *,
    dag: DAGHandle,
    **kwargs: Any,
) -> str:
    """
    Branch to the named alternative of the declared downstream alternatives
    scope based on an upstream result field (paper objective 2: adaptation
    to intermediate results).

    The action must be followed by the alternatives scope: a group whose
    children are the named alternative branches (each a NAMED group — the
    schema's optional ``name`` attribute; actions have no name).  The
    function reads ``field`` from the LATEST upstream result (the result of
    the action named ``upstream``, or the collision-suffixed variant the
    engine keys it under when the name repeats) and selects the alternative
    whose name matches that value.  The chosen alternative is moved into
    place of the alternatives scope (``dag.select``), so the unselected
    alternatives never run.

    When the selected name matches no alternative, the ``default``
    alternative (a named child) is used instead; when there is no default
    (or the default name matches no alternative either), a ``ValueError``
    is raised.

    Returns the name of the alternative that was selected (the plain result
    that flows downstream as this action's result).
    """
    selected = _upstream_field(kwargs, upstream, field)
    chosen = dag.select(selected, default)
    return chosen.name


def check_convergence(
    upstream: str,
    field: str,
    *,
    dag: DAGHandle,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Iterate the declared body until the upstream result field converges
    (paper objective 2: adaptation to intermediate results; the paper's
    section 5 copy-to-end workaround).

    The action is preceded by the iteration body in its scope (the copy-to-
    end pattern places it at the scope end).  The function reads
    ``field`` from the LATEST upstream result (the result of the action
    named ``upstream``, or the collision-suffixed variant the engine keys it
    under when the name repeats across iterations).  When the value is
    converged (truthy), the function returns a plain-data summary and
    nothing is adapted.  When it is not converged, the function appends a
    copy of the iteration body — plus a fresh copy of this check action
    itself — at the scope end (``dag.repeat()``), so the next iteration
    runs strictly downstream.  The iteration count is unknown a priori; a
    runaway workflow is terminated deterministically by the engine's
    dynamic-node bound (``ADAPTATION_BOUND``).

    ``upstream`` should be an action that is part of the iteration body (it
    runs once per iteration), so that the number of its results equals the
    iteration count.

    Returns ``{"converged": True, "iterations": <n>}`` where ``<n>`` is the
    number of times the body has run (including the current iteration) —
    the plain result that flows downstream as this action's result.

    Raises ``ValueError`` when the check action has no preceding iteration
    body in its scope.
    """
    value = _upstream_field(kwargs, upstream, field)
    iterations = _upstream_count(kwargs, upstream)
    if value:
        return {"converged": True, "iterations": iterations}
    dag.repeat()
    return {"converged": False, "iterations": iterations}


def try_action(
    name: str,
    params: dict[str, Any] | None = None,
    registry: FunctionRegistry | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Invoke the registered function ``name`` and capture any exception.

    .. deprecated:: finding 3c
       Prefer the engine-level per-scope error policy
       ``on_error="capture"`` (see :func:`.engine.run_workflow`): a scope
       declaring ``<scope on_error="capture">`` turns an exception from
       any of its direct action children into that action's result — a
       :class:`.engine.CapturedError` record with the same ``ok`` /
       ``error`` keys this wrapper returns — so the SAME driver
       vocabulary (:func:`retry` with ``on="error"``, :func:`fallback`)
       reads it unchanged.  The engine policy wraps a REAL body (upstream
       results, globals, adaptation, any number of actions); this wrapper
       is limited to one named function with exactly static ``params``
       (no upstream data, no adaptation), which is why the review's
       finding 3c prescribes the engine policy over it.

       Migration: replace ``<action function="try_action"><argument
       key="name" value="simulate"/></action>`` with the action itself
       inside a capture scope — ``<scope on_error="capture"><action
       function="simulate"/></scope>`` — and read the failure from the
       action's own result (``ok`` falsy, ``error`` the exception string)
       instead of from the wrapper's ``result`` field.

    This is the error-capturing primitive (no ``dag``): the engine
    propagates a per-node exception out of the run, so an error-reactive
    scenario (retry, fallback) needs one call site that turns an exception
    into data.  The function named ``name`` is resolved from ``registry``
    (default :data:`.registry.DEFAULT_REGISTRY`) and invoked with exactly
    ``params`` (a mapping of its own parameters); the call's outcome is
    returned as plain data instead of propagating:

    * success — ``{"ok": True, "result": <return value>, "error": None}``;
    * failure — ``{"ok": False, "result": None, "error": "<exception
      string>"}`` (the ``str()`` of the exception, so the outcome is
      plain, comparable data).

    ``name`` (not ``function`` — that would collide with
    :class:`.schema.Action`'s reserved ``function`` keyword, breaking
    ``Action("try_action", function=...)`` and ``dag.copy`` on a
    ``try_action`` body) is the registry name, the same vocabulary
    :meth:`.registry.FunctionRegistry.get` uses.  ``params`` defaults to
    an empty mapping.  Extra keyword arguments (globals, upstream
    results) are ignored: the wrapped call receives exactly ``params``,
    so the wrapper is deterministic and the recorded history stays plain
    data.  To target a registry other than ``DEFAULT_REGISTRY`` from a
    workflow, pass ``registry`` as a global parameter (globals reach
    every action's keyword arguments).

    Raises ``ValueError`` when ``name`` is not registered in ``registry``
    (an unresolvable name is a workflow error, not a captured failure).
    """
    target = registry if registry is not None else DEFAULT_REGISTRY
    fn = target.get(name)
    call_params = dict(params) if params else {}
    try:
        result = fn(**call_params)
    except Exception as exc:  # noqa: BLE001 — capture is the point
        return {"ok": False, "result": None, "error": str(exc)}
    return {"ok": True, "result": result, "error": None}


def retry(
    upstream: str,
    max_attempts: int,
    on: str = "error",
    field: str | None = None,
    op: str = "eq",
    value: Any = None,
    backoff: str = "fixed",
    delay: float = 0.0,
    sleep: Callable[[float], Any] | None = None,
    *,
    dag: DAGHandle,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Re-run the preceding body while the latest upstream result is
    unacceptable, up to ``max_attempts`` (an iteration driver, copy-to-end).

    The action is preceded by the body in its scope (the copy-to-end
    pattern places it at the scope end).  The function reads the LATEST
    upstream result (the result of the action named ``upstream``, or the
    collision-suffixed variant the engine keys it under when the name
    repeats across attempts) and decides whether it is acceptable:

    * ``on="error"`` (the default) — the result is unacceptable when it
      is a :func:`try_action` outcome with ``ok`` falsy (the body's
      action is a ``try_action`` wrapper, so a failure is data, not an
      abort).  A result that is not a ``try_action`` outcome is always
      acceptable.    * ``on="field"`` — the result is unacceptable when
      ``result[field] <op> value`` holds (the same predicate vocabulary
      as :func:`guard`; e.g. ``op="eq", value=False`` retries until the
      field equals ``True``... precisely: retries while the predicate
      HOLDS, so use the predicate that describes the unacceptable
      result).

    When the latest result is acceptable, the function returns a
    plain-data summary and nothing is adapted.  When it is unacceptable
    and the body has run fewer than ``max_attempts`` times, the function
    appends a copy of the body — plus a fresh copy of this check action
    itself — at the scope end (``dag.repeat()``; the paper's section 5
    copy-to-end workaround; every action still executes at most once).
    When the body has already run ``max_attempts`` times, the function
    returns the exhausted summary and adapts nothing.

    ``backoff`` / ``delay`` / ``sleep`` control the pause between
    attempts.  The default (``backoff="fixed"``, ``delay=0.0``) pauses
    nothing.  With ``delay > 0`` and no ``sleep`` hook given, the
    function sleeps ``delay`` seconds between attempts (``backoff=
    "linear"`` multiplies the pause by the attempt number); a ``sleep``
    hook (any callable of one float) is invoked instead — the
    test-friendly seam, so a workflow can inject a recorder instead of
    a real pause.  A driver that pauses blocks one pool worker, which
    is acceptable for a sequential retry.

    ``upstream`` should be an action that is part of the body (it runs
    once per attempt), so the number of its results equals the attempt
    count.

    Returns ``{"ok": <bool>, "attempts": <n>}`` where ``<n>`` is the
    number of times the body has run — plus ``"max_attempts"`` when the
    cap stopped the retry — the plain result that flows downstream as
    this action's result.

    Raises ``ValueError`` when no upstream result named ``upstream`` is
    available, when ``on`` is unknown, or when the check action has no
    preceding body in its scope.
    """
    if on not in ("error", "field"):
        raise ValueError(
            f"retry: unknown on {on!r} (expected 'error' or 'field')"
        )
    result = _upstream_latest(kwargs, upstream)
    attempts = _upstream_count(kwargs, upstream)
    acceptable = _acceptable(result, on, field, op, value, upstream)
    if acceptable:
        return {"ok": True, "attempts": attempts}
    cap = coerce_value(max_attempts) if max_attempts is not None else None
    if cap is not None and attempts >= cap:
        return {"ok": False, "attempts": attempts, "max_attempts": cap}
    _pause(backoff, delay, sleep, attempts)
    dag.repeat()
    return {"ok": False, "attempts": attempts}


def fallback(
    upstream: str,
    field: str,
    ok_value: Any,
    *,
    dag: DAGHandle,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Stop the alternatives chain once one alternative succeeds
    (a conditional driver, first-success).

    The action is followed by the alternatives chain: the following
    siblings (each one an alternative body, e.g. solver A, solver B,
    solver C).  The function reads ``field`` from the LATEST upstream
    result (the result of the action named ``upstream``, or the
    collision-suffixed variant the engine keys it under when the name
    repeats across alternatives) and evaluates the success predicate
    ``result[field] == ok_value``.  ``ok_value`` is coerced from its XML
    string form (the same normalization :func:`guard` applies to its
    comparison operand), so a boolean success flag driven from XML
    (``ok_value="True"``) compares against a real boolean field:

    * success — every following sibling (the remaining alternatives and
      their checks) is replaced with an empty group
      (``dag.skip_following()``) — a valid node that runs nothing — so
      none of them ever runs;
    * failure — nothing is adapted; the next alternative runs, and its
      own ``fallback`` check (declared after it) re-evaluates.

    The chain convention: place one ``fallback`` action after EACH
    alternative (the check-after-each-alternative pattern), each reading
    the alternative's own result.  The first check whose predicate holds
    empties the rest of the chain; the later checks never run (they were
    replaced).  An error-triggered chain uses :func:`try_action` as the
    alternative body, so a failure is data (``ok`` falsy) rather than an
    abort.

    Returns ``{"fallback": {"ok": <bool>}}`` — the plain result that
    flows downstream as this action's result.

    Raises ``ValueError`` when no upstream result named ``upstream`` is
    available or the result is not a mapping.
    """
    result = _upstream_latest(kwargs, upstream)
    field_value = _result_field(result, upstream, field)
    if field_value == _coerce_operand(ok_value):
        dag.skip_following()
        return {"fallback": {"ok": True}}
    return {"fallback": {"ok": False}}


def regression_gate(
    upstream: str,
    baseline: Any,
    field: str,
    tolerance: float = 0.0,
    on_regression: str = "fail",
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Compare every upstream result's ``field`` to a ``baseline`` within
    ``tolerance`` and gate the workflow on regression (a pure function —
    no ``dag``).

    The engine keys upstream results by the producing action's function
    name, with collision suffixes (``name``, ``name_2``, ...) when the
    name repeats (e.g. one result per test case in a campaign).  This
    function reads ALL of them, extracts ``field`` from each result, and
    compares it to ``baseline``: a value passes when it is equal to
    ``baseline`` (for non-numeric values) or within ``tolerance`` of it
    (for numbers: ``abs(value - baseline) <= tolerance``).  ``baseline``
    and ``tolerance`` are coerced from their XML string forms (the same
    normalization :func:`guard` applies to its comparison operands), so a
    numeric gate driven from XML compares numerically.

    The verdict is the ``all`` aggregation of the per-result outcomes:

    * every value within tolerance — ``{"regression_gate": {"passed":
      True, "count": <n>, "deviations": {}}}``;
    * any value outside tolerance — a regression.  With
      ``on_regression="fail"`` (the default) the function raises
      ``ValueError`` naming the worst deviation (a fail-fast gate: the
      run aborts with a clear message); with ``on_regression="report"``
      the function returns the verdict with the per-result deviations
      (keyed by the engine's result name) instead of raising.

    With zero results the gate passes trivially (``count`` ``0``) — the
    plain-function convention: a summary never fails a run.

    Raises ``ValueError`` when an upstream result named ``upstream`` is
    not a mapping or lacks ``field``, or when ``on_regression`` is
    unknown.
    """
    if on_regression not in ("fail", "report"):
        raise ValueError(
            f"regression_gate: unknown on_regression {on_regression!r} "
            f"(expected 'fail' or 'report')"
        )
    base = _coerce_operand(baseline)
    results = _upstream_all(kwargs, upstream)
    deviations: dict[str, Any] = {}
    for name, result in zip(_upstream_keys(kwargs, upstream), results):
        value = _result_field(result, upstream, field)
        if not _within_tolerance(value, base, tolerance):
            deviations[name] = value
    if not deviations:
        return {"regression_gate": {"passed": True, "count": len(results), "deviations": {}}}
    if on_regression == "fail":
        worst = max(deviations.values(), key=lambda v: _deviation(v, base))
        raise ValueError(
            f"regression_gate: regression detected — {upstream!r}[{field!r}] "
            f"deviates from baseline {base!r} (worst: {worst!r}, "
            f"{len(deviations)} of {len(results)} results outside tolerance "
            f"{tolerance!r})"
        )
    return {
        "regression_gate": {
            "passed": False,
            "count": len(results),
            "deviations": deviations,
        }
    }


def randomize_scenarios(
    method: str,
    seed: int,
    count: int,
    options: str | list | tuple | None = None,
    **kwargs: Any,
) -> list[Any]:
    """
    Generate ``count`` randomized scenario values from a seeded RNG
    (a plain function — no ``dag``; the paper's P16 / UC2 randomization
    with stored recreation metadata).

    The function draws ``count`` values from a dedicated
    :class:`random.Random` instance seeded with ``seed`` (the stdlib RNG,
    explicitly seeded — no global RNG state is touched, so the campaign
    is reproducible regardless of what else ran in the process).  The
    same ``(method, seed, count, options)`` always yields the same
    scenario list, in the same order, in the same process or a fresh
    interpreter (the Mersenne Twister stream is stable across runs and
    platforms for the same seed); different seeds yield different lists
    (statistically — a given item is not guaranteed to differ).

    ``method`` selects the generator (the recreation metadata the paper
    requires to be stored alongside the seed, §3.1.2):

    * ``"uniform"`` (the default) — ``count`` independent draws from the
      unit interval ``[0.0, 1.0)`` (``rng.random()``);
    * ``"choice"`` — ``count`` draws from ``options`` (``rng.choice``);
      ``options`` is accepted as a comma-separated string (``"a, b, c"``,
      the XML form) or a list/tuple (the Python API form);
    * ``"permutation"`` — a random ordering of ``options``
      (``rng.sample`` without replacement); ``count`` is ignored (the
      result has ``len(options)`` items) and ``options`` is required.

    ``method`` and ``seed`` are DECLARED parameters, so the engine
    records them in the action's history record (``record.params``) —
    the recreation metadata that makes a randomized run auditable and
    repeatable.  For run-level traceability, the caller may also stamp
    the seed on the run history (``history.seed = seed``); the run-level
    field is the campaign's identity, the record-level params are the
    per-action evidence.

    The returned list is the plain result that flows downstream as this
    action's result; to fan a campaign out over the generated values,
    compose with a map-style driver (e.g. feed the list to
    :func:`parameter_sweep`'s ``values`` parameter, or iterate it in a
    user function) — this function itself never adapts the workflow.

    Raises ``ValueError`` when ``method`` is unknown, when ``count`` is
    not a positive integer, or when ``"choice"`` / ``"permutation"`` is
    used without a non-empty ``options``.
    """
    rng = random.Random(seed)
    if method == "uniform":
        return [rng.random() for _ in range(_positive_count(count, "randomize_scenarios"))]
    if method == "choice":
        pool = _option_pool(options, "randomize_scenarios")
        return [rng.choice(pool) for _ in range(_positive_count(count, "randomize_scenarios"))]
    if method == "permutation":
        pool = _option_pool(options, "randomize_scenarios")
        return list(rng.sample(pool, len(pool)))
    raise ValueError(
        f"randomize_scenarios: unknown method {method!r} "
        f"(expected 'uniform', 'choice' or 'permutation')"
    )


def _positive_count(count: Any, caller: str) -> int:
    """
    Normalize a ``count`` parameter to a positive int.

    XML arguments arrive as strings (``count="5"``), so numeric strings
    are coerced (the same normalization :func:`.params.coerce_value`
    applies to sweep values).  Raises ``ValueError`` when the value is
    not a positive integer.
    """
    value = coerce_value(count) if isinstance(count, str) else count
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(
            f"{caller}: 'count' must be a positive integer, got {count!r}"
        )
    return value


def _option_pool(options: Any, caller: str) -> list[Any]:
    """
    Normalize an ``options`` parameter to a non-empty list.

    A comma-separated string (the XML form, ``"a, b, c"``) is split and
    stripped; a list or tuple (the Python API form) is used as-is.
    Empty items are dropped.  Raises ``ValueError`` when the pool is
    empty (a draw from an empty pool is a workflow error, not a
    silent empty campaign).
    """
    if options is None:
        raise ValueError(f"{caller}: method requires a non-empty 'options'")
    items = options.split(",") if isinstance(options, str) else list(options)
    pool = [item.strip() if isinstance(item, str) else item for item in items]
    pool = [item for item in pool if item != "" and item is not None]
    if not pool:
        raise ValueError(f"{caller}: 'options' must not be empty")
    return pool


def aggregate(
    upstream: str,
    field: str,
    op: str,
    key: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Reduce the ``field`` value of every upstream result named ``upstream``
    into one summary (a pure function — no ``dag``).

    The engine keys upstream results by the producing action's function
    name, with collision suffixes (``name``, ``name_2``, ...) when the
    name repeats (e.g. across copied iterations).  This function reads
    ALL of them, extracts ``field`` from each result, and reduces the
    values with ``op``:

    * ``sum`` / ``max`` / ``min`` / ``mean`` — numeric reduction
      (``mean`` is the arithmetic mean);
    * ``count`` — the number of results (``field`` is still read from
      each result, so a result lacking ``field`` raises even for
      ``count``);
    * ``all`` / ``any`` — boolean reduction over the values.

    With ``key``, the results are first grouped by their ``key`` field and
    each group is reduced separately (e.g. a per-test-case verdict
    grouped by test-case name).

    Returns ``{"aggregate": {"op": ..., "count": <n>, "value": <reduced>}}``
    (with ``key``: ``{"aggregate": {"op": ..., "count": <n>, "groups":
    {<key value>: {"count": ..., "value": ...}, ...}}}``).  With zero
    values, ``count`` is ``0`` and ``value`` is ``None`` — except ``all``
    (``True``) and ``any`` (``False``), the empty boolean reductions.

    Raises ``ValueError`` when an upstream result named ``upstream`` is
    not a mapping, lacks ``field`` (or ``key``), or when ``op`` is
    unknown.  When NO upstream result named ``upstream`` is available,
    the function tolerates it (an empty aggregation, count ``0``) — the
    plain-function convention: a summary never fails a run.
    """
    results = _upstream_all(kwargs, upstream)
    if key is not None:
        keyed: dict[Any, list[Any]] = {}
        for result in results:
            group = _result_field(result, upstream, key)
            keyed.setdefault(group, []).append(
                _result_field(result, upstream, field)
            )
        return {
            "aggregate": {
                "op": op,
                "count": len(results),
                "groups": {
                    group: {
                        "count": len(group_values),
                        "value": _reduce(op, group_values),
                    }
                    for group, group_values in sorted(
                        keyed.items(),
                        # Sort groups by (type name, value): same-type
                        # groups sort naturally (ints numerically), and
                        # mixed-type groups never compare values across
                        # types (a str key and an int key do not raise a
                        # TypeError).
                        key=lambda item: (type(item[0]).__name__, item[0]),
                    )
                },
            }
        }
    values = [_result_field(result, upstream, field) for result in results]
    return {"aggregate": {"op": op, "count": len(results), "value": _reduce(op, values)}}


def guard(
    upstream: str,
    field: str,
    op: str,
    value: Any,
    on_fail: str = "skip",
    *,
    dag: DAGHandle,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Run the declared downstream scope only when a predicate on the latest
    upstream result holds (a conditional driver).

    The action must be followed by the scope it guards (the declared
    downstream group — ``dag.following_group()``).  The function reads
    ``field`` from the LATEST upstream result (the result of the action
    named ``upstream``, or the collision-suffixed variant the engine
    keys it under when the name repeats) and evaluates the predicate
    ``result[field] <op> value`` with ``op`` one of ``eq`` / ``ne`` /
    ``lt`` / ``le`` / ``gt`` / ``ge`` / ``in`` / ``not_in`` /
    ``contains``.

    When the predicate holds, nothing is adapted and the declared scope
    runs exactly as declared.  When it fails:

    * ``on_fail="skip"`` (the default) replaces the declared scope with
      an empty group (``dag.skip()``) — a valid node that runs nothing, so
      the body never runs and the group's result is an empty list;
    * ``on_fail="fail"`` raises ``ValueError`` (a fail-fast gate: the
      run aborts with a clear message instead of silently skipping).

    Returns ``{"guard": {"passed": <bool>, "op": <op>}}`` — the plain
    result that flows downstream as this action's result.

    Raises ``ValueError`` when no upstream result named ``upstream`` is
    available, when that result is not a mapping, or when ``op`` is
    unknown.
    """
    field_value = _upstream_field(kwargs, upstream, field)
    passed = _compare(field_value, op, _coerce_operand(value))
    if passed:
        return {"guard": {"passed": True, "op": op}}
    if on_fail == "fail":
        raise ValueError(
            f"guard: the predicate {upstream!r}[{field!r}] {op} {value!r} "
            f"does not hold (on_fail='fail')"
        )
    if on_fail != "skip":
        raise ValueError(
            f"guard: unknown on_fail {on_fail!r} (expected 'skip' or 'fail')"
        )
    dag.skip()
    return {"guard": {"passed": False, "op": op}}


def while_condition(
    upstream: str,
    field: str,
    op: str,
    threshold: float,
    max_iterations: int | None = None,
    *,
    dag: DAGHandle,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Iterate the declared body while the latest upstream result's ``field``
    fails a threshold comparison (the numeric-tolerance generalization of
    :func:`check_convergence`).

    The action is preceded by the iteration body in its scope (the
    copy-to-end pattern places it at the scope end).  The function reads
    ``field`` from the LATEST upstream result (the result of the action
    named ``upstream``, or the collision-suffixed variant the engine
    keys it under when the name repeats across iterations) and evaluates
    ``result[field] <op> threshold`` with ``op`` one of ``lt`` / ``le`` /
    ``gt`` / ``ge`` / ``eq`` / ``ne`` (e.g. ``op="lt"`` with
    ``threshold=1e-6`` iterates until the residual is below tolerance).

    When the comparison holds (the condition is satisfied), the function
    returns a plain-data summary and nothing is adapted.  When it fails,
    the function appends a copy of the iteration body — plus a fresh copy
    of this check action itself — at the scope end (``dag.repeat()``; the
    paper's section 5 copy-to-end workaround; every action still executes
    at most once).

    ``max_iterations`` (default ``None`` = no cap beyond the engine's
    dynamic-node bound) stops the iteration once the body has run
    ``max_iterations`` times: the function returns the not-converged
    summary with the cap recorded and adapts nothing, so a slow- or
    non-converging body terminates at a user-facing limit instead of the
    engine's ``ADAPTATION_BOUND``.

    ``upstream`` should be an action that is part of the iteration body
    (it runs once per iteration), so the number of its results equals the
    iteration count.

    Returns ``{"converged": <bool>, "iterations": <n>}`` where ``<n>`` is
    the number of times the body has run — plus ``"max_iterations"`` when
    the cap stopped the iteration — the plain result that flows
    downstream as this action's result.

    Raises ``ValueError`` when no upstream result named ``upstream`` is
    available, when that result is not a mapping, when ``op`` is unknown,
    or when the check action has no preceding body in its scope.
    """
    field_value = _upstream_field(kwargs, upstream, field)
    satisfied = _compare(field_value, op, _coerce_operand(threshold))
    iterations = _upstream_count(kwargs, upstream)
    if satisfied:
        return {"converged": True, "iterations": iterations}
    cap = coerce_value(max_iterations) if max_iterations is not None else None
    if cap is not None and iterations >= cap:
        return {
            "converged": False,
            "iterations": iterations,
            "max_iterations": cap,
        }
    dag.repeat()
    return {"converged": False, "iterations": iterations}


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

#: The library functions, in the paper's order (the seven paper functions
#: first, then the objective-2 drivers, then the Tier 1, Tier 2 and Tier 3
#: generic functions from ``docs/dynamic_scenarios_analysis.md`` §5).
#: ``register_library`` registers exactly these, under their own names.
LIBRARY_FUNCTIONS: tuple[Callable[..., Any], ...] = (
    find_files,
    simulate,
    evaluate_results,
    find_test_cases,
    parameter_sweep,
    compare_parameter_sweep,
    compare_results,
    evaluate_goal,
    check_convergence,
    aggregate,
    guard,
    while_condition,
    try_action,
    retry,
    fallback,
    regression_gate,
    randomize_scenarios,
)


def register_library(registry: FunctionRegistry | None = None) -> FunctionRegistry:
    """
    Register the library functions into a registry.

    ``registry`` defaults to :data:`.registry.DEFAULT_REGISTRY`.  Each
    function is registered under its own name (``find_files``, ``simulate``,
    ..., ``evaluate_goal``, ``check_convergence``).  The call is idempotent:
    re-registering the same function objects is a silent no-op, so it is
    safe to call more than once.

    Returns the registry the functions were registered into, so the call
    can be chained or inspected.

    This is the explicit opt-in path: importing :mod:`.library` does not
    touch ``DEFAULT_REGISTRY`` (a fresh interpreter still sees it empty),
    and this function is how a user opts the paper's library into the
    engine's default registry path (or into their own ``FunctionRegistry``).
    """
    target = registry if registry is not None else DEFAULT_REGISTRY
    # The library functions' reserved-name declarations (``dag`` on the
    # drivers, ``artifacts`` / ``walk_context`` on the store-integration
    # paths) are the documented injection contract, not a collision — the
    # registry's reserved-name warning is silenced for this batch
    # registration (pass warn_reserved=False for the same effect on your
    # own batch registrations).
    for fn in LIBRARY_FUNCTIONS:
        target.register(fn.__name__, fn, warn_reserved=False)
    return target


# --------------------------------------------------------------------------- #
# Private helpers
# --------------------------------------------------------------------------- #


def _as_bool(value: bool | str, caller: str) -> bool:
    """
    Normalize a boolean option that may arrive as an XML string.

    XML ``<argument>`` values are plain strings, so a ``parallel`` option
    set from XML arrives as ``"true"`` / ``"false"`` (any case); a real
    ``bool`` (the Python API) passes through.  Anything else raises
    ``ValueError`` — a mistyped option fails loudly instead of being
    silently treated as ``False``.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "1"):
            return True
        if lowered in ("false", "no", "0", ""):
            return False
    raise ValueError(
        f"{caller}: 'parallel' must be a boolean or 'true'/'false' "
        f"(any case), got {value!r}"
    )


def _upstream_results(params: dict[str, Any]) -> dict[str, Any]:
    """
    Collect the upstream results from an action's keyword parameters.

    The engine passes the results of upstream actions (and of a
    ``Parallel`` group's children) to a downstream action as keyword
    arguments.  A value is treated as a result when it is a dict, list, or
    tuple; scalar parameters (file names, model paths, sweep values) are
    not results and are ignored.
    """
    return {k: v for k, v in params.items() if isinstance(v, (dict, list, tuple))}


def _summary(results: dict[str, Any]) -> dict[str, int]:
    """A small deterministic summary: each upstream result's item count."""
    return {k: len(v) for k, v in sorted(results.items())}


def _upstream_field(kwargs: dict[str, Any], upstream: str, field: str) -> Any:
    """
    Read ``field`` from the LATEST upstream result named ``upstream``.

    The engine keys upstream results by the producing action's function
    name, with collision suffixes (``name``, ``name_2``, ...) when the name
    repeats (e.g. across copied iterations).  The latest result is the one
    with the highest suffix (the plain name is suffix 1).  The result must
    be a mapping for ``field`` to be read from it.
    """
    keys = _upstream_keys(kwargs, upstream)
    if not keys:
        raise ValueError(
            f"check/evaluate: no upstream result named {upstream!r} is "
            f"available to this action"
        )
    result = kwargs[keys[-1]]
    if not isinstance(result, dict):
        raise ValueError(
            f"check/evaluate: the upstream result {upstream!r} is not a "
            f"mapping, so field {field!r} cannot be read from it"
        )
    return result[field]


def _upstream_count(kwargs: dict[str, Any], upstream: str) -> int:
    """
    Count the upstream results named ``upstream`` (collision-suffixed).

    When the producing action runs once per iteration (the intended use),
    this count is the number of iterations so far.  Same-prefix kwargs that
    are not result names (a ``<name>_note`` parameter, e.g.) are not results
    and are not counted.
    """
    return len(_upstream_keys(kwargs, upstream))


def _upstream_keys(kwargs: dict[str, Any], upstream: str) -> list[str]:
    """
    The engine's result names for ``upstream``, in suffix order.

    The engine keys upstream results by the producing action's function
    name, with collision suffixes (``name``, ``name_2``, ...) when the
    name repeats (e.g. across copied iterations).  The results are
    returned oldest first (suffix 1, 2, ...), so a reduction over them is
    deterministic.  Unlike :func:`_upstream_field`, a missing name is not
    an error: the caller gets an empty list (an empty aggregation).
    """
    keys: list[str] = []
    suffix = 1
    while True:
        key = upstream if suffix == 1 else f"{upstream}_{suffix}"
        if key not in kwargs:
            break
        keys.append(key)
        suffix += 1
    return keys


def _upstream_all(kwargs: dict[str, Any], upstream: str) -> list[Any]:
    """
    Collect EVERY upstream result named ``upstream``, in suffix order.

    The engine keys upstream results by the producing action's function
    name, with collision suffixes (``name``, ``name_2``, ...) when the
    name repeats (e.g. across copied iterations).  The results are
    returned oldest first (suffix 1, 2, ...), so a reduction over them is
    deterministic.  Unlike :func:`_upstream_field`, a missing name is not
    an error: the caller gets an empty list (an empty aggregation).
    """
    return [kwargs[key] for key in _upstream_keys(kwargs, upstream)]


def _upstream_latest(kwargs: dict[str, Any], upstream: str) -> Any:
    """
    Return the LATEST upstream result named ``upstream`` (or raise).

    The same contract as :func:`_upstream_field` (the highest collision
    suffix wins; a missing name raises), but returning the whole result
    so a caller can inspect its shape (e.g. a :func:`try_action`
    outcome) before reading a field from it.
    """
    keys = _upstream_keys(kwargs, upstream)
    if not keys:
        raise ValueError(
            f"check/evaluate: no upstream result named {upstream!r} is "
            f"available to this action"
        )
    return kwargs[keys[-1]]


def _acceptable(
    result: Any,
    on: str,
    field: str | None,
    op: str,
    value: Any,
    upstream: str,
) -> bool:
    """
    Decide whether one upstream ``result`` is acceptable to :func:`retry`.

    ``on="error"`` — a :func:`try_action` outcome is acceptable when its
    ``ok`` is truthy; any other result shape is acceptable (the body did
    not wrap its action, so there is no failure signal to read).
    ``on="field"`` — acceptable when the predicate ``result[field] <op>
    value`` does NOT hold (the predicate describes the unacceptable
    result, the same vocabulary as :func:`guard`).
    """
    if on == "error":
        if isinstance(result, dict) and "ok" in result and "error" in result:
            return bool(result["ok"])
        return True
    if field is None:
        raise ValueError("retry: on='field' requires a 'field' parameter")
    field_value = _result_field(result, upstream, field)
    return not _compare(field_value, op, _coerce_operand(value))


def _pause(
    backoff: str,
    delay: float,
    sleep: Callable[[float], Any] | None,
    attempts: int,
) -> None:
    """
    Pause between retry attempts (the backoff hook).

    The default (``delay=0.0``) pauses nothing.  With ``delay > 0``:
    ``backoff="fixed"`` pauses ``delay`` seconds every attempt;
    ``backoff="linear"`` pauses ``delay * attempts`` (the attempt number).
    A ``sleep`` hook, when given, is invoked with the pause length
    instead of a real sleep — the test-friendly seam (no real sleeps in
    the default test path).
    """
    if delay is None or float(delay) <= 0.0:
        return
    if backoff == "fixed":
        pause = float(delay)
    elif backoff == "linear":
        pause = float(delay) * max(attempts, 1)
    else:
        raise ValueError(
            f"retry: unknown backoff {backoff!r} (expected 'fixed' or 'linear')"
        )
    if sleep is not None:
        sleep(pause)
        return
    time.sleep(pause)


def _within_tolerance(value: Any, baseline: Any, tolerance: Any) -> bool:
    """
    True when ``value`` matches ``baseline`` within ``tolerance``.

    Numbers (both operands numeric) compare by absolute difference:
    ``abs(value - baseline) <= tolerance``.  Anything else compares by
    equality (``value == baseline``), so strings and booleans gate
    exactly.  ``tolerance`` is coerced from its XML string form.
    """
    if isinstance(value, (int, float)) and isinstance(baseline, (int, float)):
        return abs(value - baseline) <= _coerce_operand(tolerance)
    return value == baseline


def _deviation(value: Any, baseline: Any) -> float:
    """The distance of ``value`` from ``baseline`` (for worst-deviation reporting)."""
    if isinstance(value, (int, float)) and isinstance(baseline, (int, float)):
        return abs(value - baseline)
    return float("inf")


def _result_field(result: Any, upstream: str, field: str) -> Any:
    """
    Read ``field`` from one upstream ``result`` (a mapping).

    Raises ``ValueError`` when the result is not a mapping or lacks the
    field — the same contract :func:`_upstream_field` applies to the
    latest result, applied here to each result of a multi-result read.
    """
    if not isinstance(result, dict):
        raise ValueError(
            f"aggregate/guard: the upstream result {upstream!r} is not a "
            f"mapping, so field {field!r} cannot be read from it"
        )
    if field not in result:
        raise ValueError(
            f"aggregate/guard: the upstream result {upstream!r} has no "
            f"field {field!r} (fields: {sorted(result)})"
        )
    return result[field]


def _reduce(op: str, values: list[Any]) -> Any:
    """
    Reduce ``values`` with ``op`` (one of the aggregate operations).

    With no values, ``count`` is ``0`` and every other operation returns
    its empty reduction: ``None`` for the numeric operations, ``True``
    for ``all`` and ``False`` for ``any``.
    """
    if op == "count":
        return len(values)
    if op == "sum":
        return sum(values) if values else None
    if op == "max":
        return max(values) if values else None
    if op == "min":
        return min(values) if values else None
    if op == "mean":
        return sum(values) / len(values) if values else None
    if op == "all":
        return all(values)
    if op == "any":
        return any(values)
    raise ValueError(
        f"aggregate: unknown op {op!r} (expected one of sum, max, min, "
        f"count, mean, all, any)"
    )


def _compare(left: Any, op: str, right: Any) -> bool:
    """
    Evaluate the comparison predicate ``left <op> right``.

    ``op`` is one of ``eq`` / ``ne`` / ``lt`` / ``le`` / ``gt`` / ``ge``
    (numeric or ordered comparison), ``in`` / ``not_in`` (membership of
    ``left`` in ``right``), or ``contains`` (membership of ``right`` in
    ``left``).  Raises ``ValueError`` for any other op.
    """
    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "lt":
        return left < right
    if op == "le":
        return left <= right
    if op == "gt":
        return left > right
    if op == "ge":
        return left >= right
    if op == "in":
        return left in right
    if op == "not_in":
        return left not in right
    if op == "contains":
        return right in left
    raise ValueError(
        f"guard/while_condition: unknown op {op!r} (expected one of eq, "
        f"ne, lt, le, gt, ge, in, not_in, contains)"
    )


def _coerce_operand(value: Any) -> Any:
    """
    Normalize one comparison operand from its XML string form.

    The XML form passes every argument as a string (``threshold="0.1"``,
    ``value="3"``), which would make a numeric comparison a
    ``TypeError`` (``10.0 < "0.1"``).  Numeric strings are therefore
    coerced to ``int`` (then ``float``) — the same normalization
    :func:`.params.coerce_value` applies to sweep values — while
    ``True`` / ``False`` are coerced to booleans (``coerce_value`` leaves
    them as strings, which would break ``eq`` against a real boolean
    field).  Anything else is returned unchanged.
    """
    if isinstance(value, str):
        text = value.strip()
        if text in ("True", "False"):
            return text == "True"
        return coerce_value(text)
    return value
