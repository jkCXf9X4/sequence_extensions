"""Node discovery and input binding for the runner.

Nodes are found by scanning a module for the ``__node__`` marker ``@node``
stamps on its wrapper — no registry, no registration call.  ``[inputs]``
are then bound against the decorated function's real signature.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping

from sequence_extensions.flow._config.options import bind_flow_inputs
from sequence_extensions.flow_runner._config import RunnerConfigError

__all__ = ["find_nodes", "list_nodes"]


def find_nodes(module) -> dict[str, Callable]:
    """Every ``@node``-decorated callable in ``module``, keyed by node name.

    Scans module attributes for the ``__node__`` marker the decorator
    stamps; duplicate names for different objects are an error (the
    runner could only guess which to call).
    """
    nodes: dict[str, Callable] = {}
    for attr in dir(module):
        obj = getattr(module, attr)
        node_name = getattr(obj, "__node__", None)
        if isinstance(node_name, str):
            existing = nodes.get(node_name)
            if existing is not None and existing is not obj:
                raise RunnerConfigError(
                    f"node name {node_name!r} is defined twice in module {module.__name__!r}"
                )
            nodes[node_name] = obj
    return dict(sorted(nodes.items()))


def list_nodes(module) -> list[tuple[str, str]]:
    """One ``(node_name, first docstring line)`` pair per node in ``module``."""
    entries = []
    for node_name, fn in find_nodes(module).items():
        doc = (inspect.getdoc(fn) or "").strip()
        entries.append((node_name, doc.splitlines()[0] if doc else ""))
    return entries


def _bind_flow_inputs(fn, inputs: Mapping) -> tuple[tuple, dict]:
    """Split ``[inputs]`` into positional args and keyword args.

    The reserved-``options`` rule (``execute_flow`` takes ``options`` as its
    own keyword; a node parameter of that name must be passed positionally)
    lives in :func:`sequence_extensions.flow._config.options.bind_flow_inputs`.
    Its ``ValueError`` violations surface as config errors so the CLI keeps
    its exit-code contract; a ``TypeError`` from the final signature bind
    (inputs that do not match at all) passes through unchanged.
    """
    try:
        return bind_flow_inputs(fn, inputs)
    except ValueError as e:
        raise RunnerConfigError(str(e)) from None
