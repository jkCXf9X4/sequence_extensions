"""
The V&V workflow library: the paper's library functions, shipped.

This module is the concrete home of the deterministic library functions
specified by the paper "Automation Nation: Taming Complex V&V Workflows"
(16th International Modelica & FMI Conference, September 2025, Lucerne,
Switzerland; DOI 10.3384/ecp12076741).  It is the embodiment of the
package's design principle that *complexity lives in the library, not the
schema*: the schema (``Action`` / ``Sequential`` / ``Parallel``) stays
minimal, and the reusable, deterministic building blocks of a V&V workflow
ship here, ready to be addressed by name from XML or the Python API.

The functions
-------------

* :func:`find_files` — file discovery and dynamic-adaptation driver
  (paper Listing 5, objective 1): clones the declared downstream scope
  once per found file.
* :func:`simulate` — a placeholder simulation that echoes its parameters.
* :func:`evaluate_results` — a deterministic summary of one simulation's
  upstream results.
* :func:`find_test_cases` — discovery of the test-case files under a path.
* :func:`parameter_sweep` — dynamic-adaptation driver (paper Listing 9,
  objective 1): clones the declared downstream scope once per sweep value.
* :func:`compare_parameter_sweep` — a deterministic summary of a sweep's
  results.
* :func:`compare_results` — a deterministic summary of the final results.
* :func:`evaluate_goal` — branching driver (paper objective 2): selects the
  named alternative of the declared downstream alternatives scope based on
  an upstream result field; the unselected alternatives never run.
* :func:`check_convergence` — iteration driver (paper objective 2): while
  the upstream result field is not converged, appends a copy of the
  iteration body at the scope end (the paper's section 5 copy-to-end
  workaround); returns a plain-data summary when converged.

Every function is deterministic (no randomness, no I/O beyond the file
discovery the paper's examples require) and stdlib-only.  Every function
tolerates extra keyword arguments: the engine passes global parameters
(e.g. ``model``) and upstream results alongside each action's own
parameters, and the functions ignore what they do not need.

The four adaptation drivers (``find_files``, ``parameter_sweep``,
``evaluate_goal``, ``check_convergence``) declare a ``dag`` parameter: the
engine injects a scoped :class:`~.adaptation.DAGHandle` into them, and they
adapt the workflow by cloning the DECLARED downstream scope (they never
build nodes themselves).  Their own return value (a plain file/value list,
an alternative name, or a convergence summary) is what flows downstream as
their result.

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

from pathlib import Path
from typing import Any, Callable

from .adaptation import DAGHandle
from .params import normalize_values
from .registry import DEFAULT_REGISTRY, FunctionRegistry
from .schema import Action, Parallel, Sequential

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
    **kwargs: Any,
) -> list[str]:
    """
    Find files under ``path`` matching ``pattern`` and drive the declared
    downstream scope once per file.

    This is the dynamic-adaptation driver of the paper's Listing 5
    (objective 1: adaptation to unknown factors).  The action must be
    followed by the scope it adapts (the declared downstream group, e.g.
    the ``simulate`` + ``evaluate_results`` pair); the function CLONES that
    declared scope once per found file (``dag.copy(body, file=f)``) and
    splices the clones in place of the declared scope (``dag.replace``), so
    each found file gets its own copy of the declared actions.  The
    function never builds nodes itself — it adapts the declared ones.

    ``path`` may be a string or a ``pathlib.Path``; ``pattern`` is a glob
    pattern matched directly under ``path`` (default ``"*.csv"``).  Files
    are processed in sorted order for determinism.

    Returns the list of found file paths (the plain result that flows
    downstream as this action's result).  When no file matches, nothing is
    adapted and the declared scope runs once, as declared.
    """
    files = sorted(str(p) for p in Path(path).glob(pattern))
    if files:
        body = dag.following_group()
        dag.replace(body, [dag.copy(body, file=f) for f in files])
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
    **kwargs: Any,
) -> list[Any]:
    """
    Drive the declared downstream scope once per sweep value.

    This is the dynamic-adaptation driver of the paper's Listing 9
    (objective 1: adaptation to unknown factors).  The action must be
    followed by the scope it adapts (the declared downstream group, e.g. a
    single ``simulate`` action); the function CLONES that declared scope
    once per sweep value (``dag.copy(body, <name>=<value>)``) and splices
    the clones in place of the declared scope (``dag.replace``), so each
    sweep value gets its own copy of the declared actions.  The function
    never builds nodes itself — it adapts the declared ones.

    ``parameter_name`` is the name of the parameter to sweep.  ``values`` is
    accepted either as a comma-separated string (``"5, 10, 15"``) or as a
    list (``[5, 10, 15]``); string items are stripped, empty items are
    dropped, and numeric strings are converted to ``int`` (or ``float``).

    Returns the list of sweep values (the plain result that flows
    downstream as this action's result).  When there are no values, nothing
    is adapted and the declared scope runs once, as declared.

    Raises ``ValueError`` if ``parameter_name`` is not given.
    """
    if parameter_name is None:
        raise ValueError("parameter_sweep requires 'parameter_name'")
    sweep_values = normalize_values(values)
    if sweep_values:
        body = dag.following_group()
        dag.replace(body, [dag.copy(body, **{parameter_name: v}) for v in sweep_values])
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
    place of the alternatives scope (``dag.replace``), so the unselected
    alternatives never run.

    When the selected name matches no alternative, the ``default``
    alternative (a named child) is used instead; when there is no default
    (or the default name matches no alternative either), a ``ValueError``
    is raised.

    Returns the name of the alternative that was selected (the plain result
    that flows downstream as this action's result).
    """
    alternatives = dag.following_group()
    selected = _upstream_field(kwargs, upstream, field)
    chosen = _select_alternative(alternatives, selected, default)
    dag.replace(alternatives, [chosen])
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
    itself — at the scope end, so the next iteration runs strictly
    downstream.  The iteration count is unknown a priori; a runaway
    workflow is terminated deterministically by the engine's dynamic-node
    bound (``ADAPTATION_BOUND``).

    ``upstream`` should be an action that is part of the iteration body (it
    runs once per iteration), so that the number of its results equals the
    iteration count.

    Returns ``{"converged": True, "iterations": <n>}`` where ``<n>`` is the
    number of times the body has run (including the current iteration) —
    the plain result that flows downstream as this action's result.
    """
    value = _upstream_field(kwargs, upstream, field)
    iterations = _upstream_count(kwargs, upstream)
    if value:
        return {"converged": True, "iterations": iterations}
    body = dag.preceding()
    if not body:
        raise ValueError(
            "check_convergence: the check action must be preceded by the "
            "iteration body in its scope"
        )
    check = dag.scope.children[dag.index]
    check_copy = Action(check.function, **check.params)
    copies = [dag.copy(node) for node in body]
    copies.append(check_copy)
    dag.append(copies)
    return {"converged": False, "iterations": iterations}


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

#: The library functions, in the paper's order (the seven paper functions
#: first, then the two objective-2 drivers).  ``register_library``
#: registers exactly these, under their own names.
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
    for fn in LIBRARY_FUNCTIONS:
        target.register(fn.__name__, fn)
    return target


# --------------------------------------------------------------------------- #
# Private helpers
# --------------------------------------------------------------------------- #


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
    best_key: str | None = None
    best_suffix = 0
    for key in kwargs:
        if key == upstream or key.startswith(upstream + "_"):
            suffix = 1 if key == upstream else int(key.rsplit("_", 1)[1])
            if suffix > best_suffix:
                best_key, best_suffix = key, suffix
    if best_key is None:
        raise ValueError(
            f"check/evaluate: no upstream result named {upstream!r} is "
            f"available to this action"
        )
    result = kwargs[best_key]
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
    this count is the number of iterations so far.
    """
    return sum(
        1
        for key in kwargs
        if key == upstream or key.startswith(upstream + "_")
    )


def _select_alternative(
    alternatives: Any,
    selected: Any,
    default: str | None,
) -> Any:
    """
    Select the named child of the alternatives scope.

    The alternatives scope's children are the named alternative branches
    (NAMED groups — the schema's optional ``name`` attribute; actions have
    no name).  The child whose name equals ``selected`` is returned.  When
    no child matches, the ``default`` child is used; when there is no
    default (or it matches no child either), a ``ValueError`` is raised.
    """
    if not isinstance(alternatives, (Sequential, Parallel)):
        raise ValueError(
            "evaluate_goal: the following sibling must be the alternatives "
            "scope (a group of named alternatives)"
        )
    names = [child.name for child in alternatives.children if child.name]
    if selected in names:
        return next(child for child in alternatives.children if child.name == selected)
    if default is not None:
        if default in names:
            return next(child for child in alternatives.children if child.name == default)
        raise ValueError(
            f"evaluate_goal: the default alternative {default!r} is not a "
            f"named child of the alternatives scope (named alternatives: "
            f"{names})"
        )
    raise ValueError(
        f"evaluate_goal: no alternative named {selected!r} in the "
        f"alternatives scope (named alternatives: {names}) and no default "
        f"alternative was given"
    )
