"""
workflow_stubs — the seven library functions of the V&V workflow paper.

Test resource (not part of the installed package): the functions are
specified by the paper "Automation Nation: Taming Complex V&V Workflows"
(16th International Modelica & FMI Conference, September 2025, Lucerne,
Switzerland; DOI 10.3384/ecp12076741).  They are deterministic,
stdlib-only placeholders that let the paper's example workflows
(Listing 5, Listing 9, Listing 10) run end-to-end against the workflow
engine:

* ``find_files`` — file discovery and dynamic-adaptation driver (Listing
  5): returns one ``simulate`` + ``evaluate_results`` pair per found file.
* ``simulate`` — a placeholder simulation that echoes its parameters.
* ``evaluate_results`` — a deterministic summary of one simulation's
  upstream results.
* ``find_test_cases`` — discovery of the test-case files under a path.
* ``parameter_sweep`` — dynamic-adaptation driver (Listing 9): returns one
  ``simulate`` action per sweep value.
* ``compare_parameter_sweep`` — a deterministic summary of a sweep's
  results.
* ``compare_results`` — a deterministic summary of the final results.

Every function tolerates extra keyword arguments: the engine passes global
parameters (e.g. ``model``) and upstream results alongside each action's
own parameters, and the stubs ignore what they do not need.

The test suite registers these stubs into a ``FunctionRegistry`` (the
package's ``DEFAULT_REGISTRY`` is empty by default).
"""

from __future__ import annotations

from pathlib import Path

from sequence_extensions.workflow.schema import Action, Sequential

__all__ = [
    "find_files",
    "simulate",
    "evaluate_results",
    "find_test_cases",
    "parameter_sweep",
    "compare_parameter_sweep",
    "compare_results",
]


# --------------------------------------------------------------------------- #
# Public stubs (the paper's seven library functions)
# --------------------------------------------------------------------------- #


def find_files(path: str | Path, pattern: str = "*.csv", **kwargs: object) -> list[Sequential]:
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


def simulate(**params: object) -> dict[str, object]:
    """
    Run a placeholder simulation.

    Deterministic: the result is ``{"simulate": <params>}`` where
    ``<params>`` is exactly the set of keyword arguments the engine passed
    (the action's own parameters, global parameters, and any upstream
    results).
    """
    return {"simulate": dict(params)}


def evaluate_results(**params: object) -> dict[str, dict[str, int]]:
    """
    Summarize the upstream results of one simulation.

    Consumes the upstream results the engine passes in (typically the
    ``simulate`` result) and returns a small deterministic summary: the
    item count of each upstream result, keyed by the name the engine used
    for it.
    """
    return {"evaluate_results": _summary(_upstream_results(params))}


def find_test_cases(path: str | Path, **kwargs: object) -> list[str]:
    """
    Find the test-case files (``*.csv``) directly under ``path``.

    ``path`` may be a string or a ``pathlib.Path``.  Returns the file paths
    as strings in sorted order (deterministic); empty if no file matches.
    """
    return sorted(str(p) for p in Path(path).glob("*.csv"))


def parameter_sweep(
    parameter_name: str | None = None,
    parameter: str | None = None,
    values: str | list | tuple | None = None,
    **kwargs: object,
) -> list[Action]:
    """
    Drive one downstream ``simulate`` per sweep value.

    This is the dynamic-adaptation driver of the paper's Listing 9: the
    returned actions are spliced into the workflow in place of the
    downstream group, so each sweep value gets its own ``simulate`` action.

    The parameter name is accepted under either spelling: ``parameter_name``
    (the XML form) or ``parameter`` (the Python API form).  ``values`` is
    accepted either as a comma-separated string (``"5, 10, 15"``) or as a
    list (``[5, 10, 15]``); string items are stripped, empty items are
    dropped, and numeric strings are converted to ``int`` (or ``float``).

    Returns one ``Action("simulate", <name>=<value>)`` per value, in order.

    Raises ``ValueError`` if neither ``parameter_name`` nor ``parameter``
    is given.
    """
    name = parameter_name if parameter_name is not None else parameter
    if name is None:
        raise ValueError("parameter_sweep requires 'parameter_name' or 'parameter'")
    return [Action("simulate", **{name: v}) for v in _normalize_values(values)]


def compare_parameter_sweep(**params: object) -> dict[str, dict[str, int]]:
    """
    Summarize the results of a parameter sweep.

    Consumes the upstream ``simulate`` results (one per sweep value) and
    returns a small deterministic summary: the item count of each upstream
    result, keyed by the name the engine used for it.
    """
    return {"compare_parameter_sweep": _summary(_upstream_results(params))}


def compare_results(**params: object) -> dict[str, dict[str, int]]:
    """
    Summarize the final results of a workflow.

    Consumes the upstream results the engine passes in (typically the
    ``compare_parameter_sweep`` result) and returns a small deterministic
    summary: the item count of each upstream result, keyed by the name the
    engine used for it.
    """
    return {"compare_results": _summary(_upstream_results(params))}


# --------------------------------------------------------------------------- #
# Private helpers
# --------------------------------------------------------------------------- #


def _upstream_results(params: dict[str, object]) -> dict[str, object]:
    """
    Collect the upstream results from an action's keyword parameters.

    The engine passes the results of upstream actions (and of a
    ``Parallel`` group's children) to a downstream action as keyword
    arguments.  A value is treated as a result when it is a dict, list, or
    tuple; scalar parameters (file names, model paths, sweep values) are
    not results and are ignored.
    """
    return {k: v for k, v in params.items() if isinstance(v, (dict, list, tuple))}


def _summary(results: dict[str, object]) -> dict[str, int]:
    """A small deterministic summary: each upstream result's item count."""
    return {k: len(v) for k, v in sorted(results.items())}


def _coerce_value(item: object) -> object:
    """
    Normalize one sweep value.

    Strings are stripped and converted to ``int`` (then ``float``) when
    possible; other values are returned unchanged.
    """
    if isinstance(item, str):
        text = item.strip()
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return float(text)
        except ValueError:
            return text
    return item


def _normalize_values(values: str | list | tuple | None) -> list:
    """
    Normalize sweep values to a list.

    A string is split on commas; a list or tuple is used as-is; ``None``
    yields an empty list.  Each item is stripped (if a string), empty items
    are dropped, and numeric strings are converted to ``int`` (or
    ``float``).
    """
    if values is None:
        return []
    items = values.split(",") if isinstance(values, str) else list(values)
    normalized = []
    for item in items:
        if isinstance(item, str) and not item.strip():
            continue
        normalized.append(_coerce_value(item))
    return normalized
