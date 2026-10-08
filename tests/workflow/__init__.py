"""
Tests for the V&V workflow layer (``Action`` / ``Sequential`` / ``Parallel`` /
``Test_Framework`` / ``FunctionRegistry`` / ``parse_workflow`` /
``run_workflow``), split by source module:

* ``test_schema.py``   — ``parse_workflow`` and the node structure it
  produces (including every rejection rule).
* ``test_registry.py`` — ``FunctionRegistry`` / ``DEFAULT_REGISTRY`` and the
  ``workflow_function`` / ``registry.function`` decorators.
* ``test_engine.py``   — ``run_workflow`` / ``Test_Framework`` and execution
  semantics (ordering, concurrency, globals, splicing, scope).

The workflow layer is specified by the paper "Automation Nation: Taming
Complex V&V Workflows" (16th International Modelica & FMI Conference,
September 2025, Lucerne, Switzerland; DOI 10.3384/ecp12076741).  The XML
fixtures are the example documents in ``tests/resources/workflows/``
(indexed by its README); they are re-exposed here as the ``LISTING_*``
constants.

The suite is written against the pinned public contract and is fully
deterministic: no network, no sleeps, no order dependence.  The paper's
library functions come from the test resources
(``tests/resources/workflow_stubs.py``), where they take the same path as
real library functions: the bare ``@workflow_function`` decorator
registers them in ``DEFAULT_REGISTRY`` at import time, and the paper's
workflows run through the engine's default registry path; file-backed
stubs (``find_files`` / ``find_test_cases``) are driven with real files
created under ``tmp_path``.

The ``_``-prefixed helpers below are shared introspection and recording
utilities used across the test modules.
"""

from __future__ import annotations

import threading

from resources import workflows
from sequence_extensions import Action, FunctionRegistry, Parallel, Sequential

__all__ = [
    "LISTING_5",
    "LISTING_7",
    "LISTING_9",
    "_children",
    "_function",
    "_globals",
    "_make_recorder",
    "_names_in_order",
    "_params",
]

# --------------------------------------------------------------------------- #
# Paper fixtures (example documents in tests/resources/workflows/)
# --------------------------------------------------------------------------- #

# Listing 9 — full use-case-1 workflow with global parameters.
LISTING_9 = workflows.load("eval_task_01.xml")

# Listing 5 — dynamic adaptation (find_files drives the downstream group).
LISTING_5 = workflows.load("dynamic_adaptation.xml")

# Listing 7 (dynamic-adaptation scope): outer_action_1 may alter everything
# downstream (including the inner actions); inner_action_1 may only alter
# actions downstream within its own grouping scope (inner_action_2).
LISTING_7 = workflows.load("adaptation_scope.xml")

# --------------------------------------------------------------------------- #
# Introspection helpers (robust to the exact attribute names the engine uses)
# --------------------------------------------------------------------------- #


def _children(node):
    """Return the direct children of a group node, whatever the engine calls them."""
    for attr in ("children", "_children", "nodes", "items", "actions", "steps", "elements"):
        value = getattr(node, attr, None)
        if isinstance(value, (list, tuple)) and value:
            return list(value)
    # Fall back to the first list/tuple attribute that holds Action/Sequential/Parallel.
    for value in vars(node).values():
        if (
            isinstance(value, (list, tuple))
            and value
            and all(isinstance(x, (Action, Sequential, Parallel)) for x in value)
        ):
            return list(value)
    raise AssertionError(f"cannot find children of {node!r}")


def _params(node):
    """Return the custom parameters of an Action, whatever the engine calls them."""
    for attr in ("params", "_params", "parameters", "kwargs", "arguments", "args"):
        value = getattr(node, attr, None)
        if isinstance(value, dict):
            return dict(value)
    for value in vars(node).values():
        if isinstance(value, dict) and value:
            return dict(value)
    return {}


def _function(node):
    """Return the function name of an Action, whatever the engine calls it."""
    for attr in ("function", "name", "fn", "func", "function_name"):
        value = getattr(node, attr, None)
        if isinstance(value, str):
            return value
    raise AssertionError(f"cannot find function name of {node!r}")


def _globals(node):
    """Return the global parameters attached to a parsed root, if any."""
    for attr in ("globals", "global_parameters", "global_params", "parameters", "params"):
        value = getattr(node, attr, None)
        if isinstance(value, dict):
            return dict(value)
    return {}


def _make_recorder(names):
    """Build a registry of recording stubs, one per name, sharing one call log."""
    calls = []
    lock = threading.Lock()

    def make(name):
        def stub(**kwargs):
            with lock:
                calls.append((name, dict(kwargs)))
            return name

        stub.__name__ = name
        return stub

    registry = FunctionRegistry()
    for name in names:
        registry.register(name, make(name))
    return registry, calls


def _names_in_order(calls):
    return [name for name, _ in calls]
