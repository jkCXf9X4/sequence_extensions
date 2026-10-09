"""
The V&V workflow library: the paper's seven library functions, shipped.

This module is the concrete home of the seven deterministic library
functions specified by the paper "Automation Nation: Taming Complex V&V
Workflows" (16th International Modelica & FMI Conference, September 2025,
Lucerne, Switzerland; DOI 10.3384/ecp12076741).  It is the embodiment of
the package's design principle that *complexity lives in the library, not
the schema*: the schema (``Action`` / ``Sequential`` / ``Parallel``) stays
minimal, and the reusable, deterministic building blocks of a V&V workflow
ship here, ready to be addressed by name from XML or the Python API.

The seven functions
-------------------

* :func:`find_files` — file discovery and dynamic-adaptation driver
  (paper Listing 5): returns one ``simulate`` + ``evaluate_results`` pair
  per found file.
* :func:`simulate` — a placeholder simulation that echoes its parameters.
* :func:`evaluate_results` — a deterministic summary of one simulation's
  upstream results.
* :func:`find_test_cases` — discovery of the test-case files under a path.
* :func:`parameter_sweep` — dynamic-adaptation driver (paper Listing 9):
  returns one ``simulate`` action per sweep value.
* :func:`compare_parameter_sweep` — a deterministic summary of a sweep's
  results.
* :func:`compare_results` — a deterministic summary of the final results.

Every function is deterministic (no randomness, no I/O beyond the file
discovery the paper's examples require) and stdlib-only.  Every function
tolerates extra keyword arguments: the engine passes global parameters
(e.g. ``model``) and upstream results alongside each action's own
parameters, and the functions ignore what they do not need.

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

from .params import normalize_values
from .registry import DEFAULT_REGISTRY, FunctionRegistry
from .schema import Action, Sequential

__all__ = [
    "find_files",
    "simulate",
    "evaluate_results",
    "find_test_cases",
    "parameter_sweep",
    "compare_parameter_sweep",
    "compare_results",
    "register_library",
]

# --------------------------------------------------------------------------- #
# The seven library functions
# --------------------------------------------------------------------------- #


def find_files(path: str | Path, pattern: str = "*.csv", **kwargs: Any) -> list[Sequential]:
    """
    Find files under ``path`` matching ``pattern`` and drive one
    ``simulate`` + ``evaluate_results`` pair per file.

    This is the dynamic-adaptation driver of the paper's Listing 5: the
    returned nodes are spliced into the workflow in place of the downstream
    group, so each found file gets its own ``simulate`` and
    ``evaluate_results`` action.

    ``path`` may be a string or a ``pathlib.Path``; ``pattern`` is a glob
    pattern matched directly under ``path`` (default ``"*.csv"``).  Files
    are processed in sorted order for determinism.

    Returns a list with one ``Sequential(Action("simulate", file=f),
    Action("evaluate_results", file=f))`` per found file (empty if no file
    matches).
    """
    files = sorted(str(p) for p in Path(path).glob(pattern))
    return [
        Sequential(Action("simulate", file=f), Action("evaluate_results", file=f)) for f in files
    ]


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
    **kwargs: Any,
) -> list[Action]:
    """
    Drive one downstream ``simulate`` per sweep value.

    This is the dynamic-adaptation driver of the paper's Listing 9: the
    returned actions are spliced into the workflow in place of the
    downstream group, so each sweep value gets its own ``simulate`` action.

    ``parameter_name`` is the name of the parameter to sweep.  ``values`` is
    accepted either as a comma-separated string (``"5, 10, 15"``) or as a
    list (``[5, 10, 15]``); string items are stripped, empty items are
    dropped, and numeric strings are converted to ``int`` (or ``float``).

    Returns one ``Action("simulate", <name>=<value>)`` per value, in order.

    Raises ``ValueError`` if ``parameter_name`` is not given.
    """
    if parameter_name is None:
        raise ValueError("parameter_sweep requires 'parameter_name'")
    return [Action("simulate", **{parameter_name: v}) for v in normalize_values(values)]


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


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

#: The seven library functions, in the paper's order.  ``register_library``
#: registers exactly these, under their own names.
LIBRARY_FUNCTIONS: tuple[Callable[..., Any], ...] = (
    find_files,
    simulate,
    evaluate_results,
    find_test_cases,
    parameter_sweep,
    compare_parameter_sweep,
    compare_results,
)


def register_library(registry: FunctionRegistry | None = None) -> FunctionRegistry:
    """
    Register the seven library functions into a registry.

    ``registry`` defaults to :data:`.registry.DEFAULT_REGISTRY`.  Each
    function is registered under its own name (``find_files``, ``simulate``,
    ...).  The call is idempotent: re-registering the same function objects
    is a silent no-op, so it is safe to call more than once.

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
