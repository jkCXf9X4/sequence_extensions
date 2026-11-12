"""Node discovery for the runner: one module scan, no registry.

Nodes are found by scanning a module for the ``__node__`` marker ``@node``
stamps on its wrapper — no registry, no registration call.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable

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
                raise ValueError(
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
