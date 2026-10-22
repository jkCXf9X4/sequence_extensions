"""Node discovery and input binding for the runner.

Nodes are found by scanning a module for the ``__node__`` marker ``@node``
stamps on its wrapper — no registry, no registration call.  ``[inputs]``
are then bound against the decorated function's real signature.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping

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

    ``execute_flow`` reserves the keyword ``options`` for run options.  A root
    node with a parameter also named ``options`` therefore has to receive that
    input positionally; the runner builds the positional prefix up to and
    including it.  A keyword-only ``options`` (or one reached after
    ``*args``/``**kwargs``) is rejected with a config error instead of a
    confusing ``TypeError`` at call time.
    """
    target = getattr(fn, "__wrapped__", fn)
    sig = inspect.signature(target)
    kwargs = dict(inputs)
    args: list = []
    if "options" in kwargs:
        handled = False
        for name, param in sig.parameters.items():
            if name == "options":
                if param.kind in (
                    inspect.Parameter.KEYWORD_ONLY,
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                ):
                    raise RunnerConfigError(
                        "node parameter 'options' must be positional "
                        "(and precede *args/**kwargs) to be driven by flow-runner"
                    )
                args.append(kwargs.pop("options"))
                handled = True
                break
            if param.kind is inspect.Parameter.VAR_POSITIONAL:
                raise RunnerConfigError(
                    "node parameter 'options' cannot be reached positionally past *args"
                )
            if param.kind is inspect.Parameter.VAR_KEYWORD:
                raise RunnerConfigError(
                    "a parameter named 'options' captured only by **kwargs "
                    "cannot be driven by flow-runner"
                )
            if param.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ):
                if name in kwargs:
                    args.append(kwargs.pop(name))
                elif param.default is not inspect.Parameter.empty:
                    args.append(param.default)
                else:
                    raise RunnerConfigError(f"missing required input {name!r}")
        if not handled:
            raise RunnerConfigError("flow has no parameter named 'options'")
    sig.bind(*args, **kwargs)
    return tuple(args), kwargs
