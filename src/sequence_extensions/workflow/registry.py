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
Re-registering an existing name with a different function emits a
``UserWarning`` (the earlier registration is replaced).
"""

from __future__ import annotations

import inspect
import warnings
from typing import Any, Callable

__all__ = [
    "DEFAULT_REGISTRY",
    "FunctionRegistry",
    "wants_artifacts",
    "wants_context",
    "wants_dag",
    "workflow_function",
]


#: The engine's reserved kwarg names: for a function that declares one, the
#: engine injects its own value (the adaptation handle, the walk context, the
#: artifact handle) and it wins over any same-named parameter.  Declaring one
#: of these names emits a ``UserWarning`` at registration time (the warning
#: tells a registrant who meant the name as data).
_RESERVED_KWARGS = ("artifacts", "dag", "walk_context")


def _declared_reserved(fn: Callable[..., Any]) -> tuple[str, ...]:
    """The reserved kwarg names ``fn``'s signature declares, sorted."""
    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # non-introspectable callable: nothing declared
        return ()
    return sorted(_RESERVED_KWARGS & parameters.keys())


def wants_dag(fn: Callable[..., Any]) -> bool:
    """
    True when ``fn``'s signature declares an explicit ``dag`` parameter.

    The engine injects the scoped :class:`~.adaptation.DAGHandle` only into
    functions that ask for it (decision D4: signature inspection, cached at
    registration time).  ``dag`` is a reserved kwarg name for adapting
    functions — the injected handle wins over any same-named parameter.

    A bare ``**kwargs`` does NOT count: it would silently swallow the
    handle (and every legacy ``def fn(**kwargs)`` stub would suddenly
    receive one, changing recorded parameters).  Adaptation is opt-in by
    naming the parameter.
    """
    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # non-introspectable callable: never inject
        return False
    return "dag" in parameters


def wants_artifacts(fn: Callable[..., Any]) -> bool:
    """
    True when ``fn``'s signature declares an explicit ``artifacts``
    parameter.

    The engine injects a scoped
    :class:`~.artifacts.ArtifactHandle` (the by-reference artifact store's
    view) only into functions that ask for it, and only when the run was
    given an :class:`~.artifacts.ArtifactStore` — signature inspection is
    cached at registration time, mirroring :func:`wants_dag`.  ``artifacts``
    is then a reserved kwarg name (the injected handle wins over any
    same-named parameter); with no store configured it stays an ordinary
    parameter name and nothing changes.

    A bare ``**kwargs`` does NOT count (same rationale as :func:`wants_dag`).
    """
    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # non-introspectable callable: never inject
        return False
    return "artifacts" in parameters


def wants_context(fn: Callable[..., Any]) -> bool:
    """
    True when ``fn``'s signature declares an explicit ``walk_context``
    parameter.

    The engine injects its per-action walk context — plain structural
    position data (the action's node plus its ancestry chain of
    ``(group, index)`` pairs; see :class:`~.engine.WalkContext`) — only
    into functions that ask for it, mirroring :func:`wants_dag`.
    ``walk_context`` is then a reserved kwarg name: the injected context
    wins over any same-named parameter.  The name is deliberately
    unmistakably engine plumbing, so an ordinary data parameter never
    collides with it.

    The primary consumer is the artifact store's registry wrapping
    (:meth:`~.artifacts.ArtifactStore.wrap_registry`, IMP-007): every
    wrapped function declares ``walk_context`` and derives its addressing
    from it, so the engine stays free of store knowledge.  A bare
    ``**kwargs`` does NOT count (same rationale as :func:`wants_dag`).
    """
    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # non-introspectable callable: never inject
        return False
    return "walk_context" in parameters


class FunctionRegistry:
    """
    A name -> function registry for workflow actions.

    Functions are called with keyword arguments only (the engine passes
    globals, upstream results, and the action's own parameters as kwargs).
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._functions: dict[str, Callable[..., Any]] = {}
        # Cached per-function adaptation flag (decision D4): True when the
        # registered function's signature declares a ``dag`` parameter, so
        # the engine injects the scoped DAGHandle into its calls.
        self._wants_dag: dict[str, bool] = {}
        # Cached per-function artifact-store flag (IMP-005): True when the
        # registered function's signature declares an ``artifacts``
        # parameter, so the engine injects the scoped ArtifactHandle into
        # its calls (when the run has an ArtifactStore).
        self._wants_artifacts: dict[str, bool] = {}
        # Cached per-function walk-context flag (IMP-007): True when the
        # registered function's signature declares a ``walk_context``
        # parameter, so the engine injects its per-action walk context
        # (plain structural position data) into its calls.
        self._wants_context: dict[str, bool] = {}

    def register(
        self, name: str, fn: Callable[..., Any], *, warn_reserved: bool = True
    ) -> None:
        """
        Register ``fn`` under ``name`` (replacing any earlier registration).

        The function's ``wants_dag`` flag (whether its signature declares a
        ``dag`` parameter), ``wants_artifacts`` flag (whether it declares an
        ``artifacts`` parameter) and ``wants_context`` flag (whether it
        declares a ``walk_context`` parameter) are cached here, at
        registration time, so the engine never inspects a signature on the
        hot path.

        ``warn_reserved`` (default ``True``) silences the reserved-kwarg
        warning below for a batch registration whose reserved-name
        declarations ARE the documented injection contract (the library's own
        registration does this).

        Raises ``ValueError`` if ``name`` is empty or ``fn`` is not callable.

        Emits a ``UserWarning`` if ``name`` is already registered with a
        different function — the earlier registration is then replaced.
        Re-registering the same function object is a silent no-op
        (idempotent, e.g. a decorator applied more than once).  Also emits a
        ``UserWarning`` when ``fn`` declares one of the engine's reserved
        kwarg names (``dag`` / ``walk_context`` / ``artifacts``): the engine
        injects its own value for such a parameter, winning over any
        same-named parameter — rename the parameter if it is meant as data.
        """
        if not name:
            raise ValueError("function name must be a non-empty string")
        if not callable(fn):
            raise ValueError(f"function {name!r} must be callable")
        existing = self._functions.get(name)
        if existing is not None and existing is not fn:
            warnings.warn(
                f"function name {name!r} is already registered; "
                f"replacing {getattr(existing, '__name__', repr(existing))!r} "
                f"with {getattr(fn, '__name__', repr(fn))!r}",
                UserWarning,
                stacklevel=2,
            )
        self._functions[name] = fn
        self._wants_dag[name] = wants_dag(fn)
        self._wants_artifacts[name] = wants_artifacts(fn)
        self._wants_context[name] = wants_context(fn)
        if warn_reserved:
            declared = _declared_reserved(fn)
            if declared:
                warnings.warn(
                    f"function {name!r} declares the reserved kwarg name(s) "
                    f"{', '.join(repr(reserved) for reserved in declared)}; "
                    "the engine injects its own value(s) over any same-named "
                    "parameter (rename the parameter if it is meant as data)",
                    UserWarning,
                    stacklevel=2,
                )

    def get(self, name: str) -> Callable[..., Any]:
        """
        Return the function registered under ``name``.

        Raises ``ValueError`` naming the function if it is not registered.
        """
        try:
            return self._functions[name]
        except KeyError:
            raise ValueError(f"unknown function: {name!r}") from None

    def adapts(self, name: str) -> bool:
        """
        True when the function registered under ``name`` wants a ``dag`` handle.

        Raises ``ValueError`` (via :meth:`get`) for an unknown name.
        """
        self.get(name)  # unknown-name parity with get()
        return self._wants_dag.get(name, False)

    def uses_artifacts(self, name: str) -> bool:
        """
        True when the function registered under ``name`` declares an
        ``artifacts`` parameter.

        Raises ``ValueError`` (via :meth:`get`) for an unknown name.  The
        engine injects the scoped
        :class:`~.artifacts.ArtifactHandle` into such functions' calls,
        but only when the run was given an
        :class:`~.artifacts.ArtifactStore`.
        """
        self.get(name)  # unknown-name parity with get()
        return self._wants_artifacts.get(name, False)

    def wants_context(self, name: str) -> bool:
        """
        True when the function registered under ``name`` declares a
        ``walk_context`` parameter.

        Raises ``ValueError`` (via :meth:`get`) for an unknown name.  The
        engine injects the per-action walk context (plain structural
        position data) into such functions' calls.  A wrapped registry
        view (:meth:`~.artifacts.ArtifactStore.wrap_registry`) reports
        ``True`` for every name: its wrappers all derive their addressing
        from the context.
        """
        self.get(name)  # unknown-name parity with get()
        return self._wants_context.get(name, False)

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
        targets ``DEFAULT_REGISTRY`` by default.  Registering a name that
        already holds a different function emits a ``UserWarning`` (see
        :meth:`register`).
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
    Emits a ``UserWarning`` when the name already holds a different
    function, which is then replaced.
    """

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        target = registry if registry is not None else DEFAULT_REGISTRY
        target.register(name if name is not None else getattr(f, "__name__", None), f)
        return f

    if fn is None:
        return decorator
    return decorator(fn)
