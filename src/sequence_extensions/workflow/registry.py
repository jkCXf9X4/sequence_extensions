"""
Function registry for the V&V workflow engine.

The registry maps action names (the ``<action function="...">`` attribute,
or the ``function`` argument of :class:`.schema.Action`) to the callables
the engine invokes for them.  Functions are called with keyword arguments
only (the engine passes globals, upstream results, and the action's own
parameters as kwargs).

:func:`workflow_function` is the decorator form of
:meth:`FunctionRegistry.register`: it marks a function for the workflow
schema so it can be addressed by name from XML and the Python API.
"""

from __future__ import annotations

from typing import Any, Callable

__all__ = [
    "DEFAULT_REGISTRY",
    "FunctionRegistry",
    "workflow_function",
]


class FunctionRegistry:
    """
    A name -> function registry for workflow actions.

    Functions are called with keyword arguments only (the engine passes
    globals, upstream results, and the action's own parameters as kwargs).
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._functions: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        """
        Register ``fn`` under ``name`` (replacing any earlier registration).

        Raises ``ValueError`` if ``name`` is empty or ``fn`` is not callable.
        """
        if not name:
            raise ValueError("function name must be a non-empty string")
        if not callable(fn):
            raise ValueError(f"function {name!r} must be callable")
        self._functions[name] = fn

    def get(self, name: str) -> Callable[..., Any]:
        """
        Return the function registered under ``name``.

        Raises ``ValueError`` naming the function if it is not registered.
        """
        try:
            return self._functions[name]
        except KeyError:
            raise ValueError(f"unknown function: {name!r}") from None

    def names(self) -> list[str]:
        """Return the registered function names in registration order."""
        return list(self._functions)

    def function(
        self,
        fn: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
    ) -> Any:
        """
        Return a decorator that registers a function in this registry.

        ``name`` is the registry name to use (defaults to the decorated
        function's own ``__name__``); the bare form
        (``@registry.function``) is equivalent to ``@registry.function()``::

            @registry.function()
            def simulate(**kwargs):
                ...

            @registry.function(name="run_model")
            def _run_model(**kwargs):
                ...

        The decorated function is returned unchanged; see
        :func:`workflow_function` for the module-level equivalent that
        targets ``DEFAULT_REGISTRY`` by default.
        """

        def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
            self.register(name if name is not None else getattr(f, "__name__", None), f)
            return f

        if fn is None:
            return decorator
        return decorator(fn)

    def __contains__(self, name: object) -> bool:
        """True if ``name`` is a registered function name."""
        return name in self._functions


#: The default function registry (empty).
#:
#: ``run_workflow`` / ``Test_Framework`` use it when no ``registry`` is
#: given; register your workflow functions on it (or pass your own
#: ``FunctionRegistry``).  The paper's seven library functions are not part
#: of the package — deterministic placeholder implementations live in the
#: test resources (``tests/resources/workflow_stubs.py``).
DEFAULT_REGISTRY = FunctionRegistry()


# --------------------------------------------------------------------------- #
# Function registration decorator
# --------------------------------------------------------------------------- #


def workflow_function(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    registry: FunctionRegistry | None = None,
) -> Any:
    """
    Register a function so the workflow schema can address it by name.

    Use it as a bare decorator to register ``fn`` under its own name
    (``fn.__name__``) in :data:`DEFAULT_REGISTRY`::

        @workflow_function
        def simulate(**kwargs):
            ...

    or with arguments to choose the registry name and/or the registry::

        @workflow_function(name="run_model", registry=my_registry)
        def _run_model(**kwargs):
            ...

    The function is returned unchanged: it stays directly callable and its
    behavior is not modified.  Once registered, it is addressable from the
    workflow schema — ``Action("simulate")`` via the Python API and
    ``<action function="simulate"/>`` in XML — and runs through
    :func:`.engine.run_workflow` / :func:`.engine.Test_Framework` (which
    default to ``DEFAULT_REGISTRY``).

    Raises ``ValueError`` if the resolved name is empty or ``fn`` is not
    callable (the same checks :meth:`FunctionRegistry.register` applies).
    """

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        target = registry if registry is not None else DEFAULT_REGISTRY
        target.register(name if name is not None else getattr(f, "__name__", None), f)
        return f

    if fn is None:
        return decorator
    return decorator(fn)
