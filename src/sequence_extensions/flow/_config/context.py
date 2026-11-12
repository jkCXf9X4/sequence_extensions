"""The current-run context shared by ``execute_flow`` and ``@node``.

A :class:`RunContext` exists for the duration of one run.  ``execute_flow``
creates it (run identity, audit log, pool, effective options) and installs
it in the context; ``@node`` reads it at ``submit()`` time and restores it
inside pool workers and deferred-attempt callback threads, so nodes
submitted from within a node join the same run.

The execution position and the worker markers travel in the same context
slot, one immutable state object held by a single ``ContextVar``:

* ``node_path`` — the chain of node names currently executing
  (``("campaign", "phase")``); a node appends its own name while its body
  runs.  The run log records it as ``path``.
* ``node_attempt`` — the enclosing node's current attempt number
  (``parent_attempt`` on descendant records).
* ``attempt_token`` — the attempt's token; an abandoned attempt checks it
  (and its ancestors) before writing a record, so a timed-out composite
  drops late records from its subtree.
* ``run_attempt_token`` — the run-level timeout attempt token.
* ``in_worker`` / ``in_process_worker`` — set in pool workers.
* ``in_node_body`` — set while a node's function runs, wherever it runs
  (root body or pool worker).  Blocking on an incomplete future is rejected
  there; returning the future is the supported way to fan out.

``ContextVar`` values do not propagate to new threads, so every thread the
layer starts (pool workers, deferred-attempt callback threads) restores the
context explicitly around the code that may look it up.  A forked process
worker inherits the forking thread's context instead, so
``_process_node_runner`` resets the worker markers on entry.
"""

from __future__ import annotations

import contextvars
import dataclasses
import threading
from contextlib import contextmanager
from dataclasses import dataclass


class AttemptToken:
    """One node attempt: abandoned flag and its enclosing attempt token."""

    __slots__ = ("abandoned", "parent")

    def __init__(self, parent: AttemptToken | None = None):
        self.abandoned = threading.Event()
        self.parent = parent

    def abandoned_in_chain(self) -> bool:
        """True if this attempt or any enclosing attempt was abandoned."""
        token = self
        while token is not None:
            if token.abandoned.is_set():
                return True
            token = token.parent
        return False


class RunContext:
    """One run: identity, audit log, pool, options, and submitted nodes."""

    __slots__ = (
        "run_id",
        "node_name",
        "runlog",
        "pool",
        "nodes",
        "node_instances",
        "outcomes",
        "options",
        "cancelled",
    )

    def __init__(self, run_id, node_name, runlog=None, pool=None, options=None):
        self.run_id = run_id
        self.node_name = node_name
        self.runlog = runlog  # RunLog | record sink | None
        self.pool = pool
        self.nodes = []  # every GraphFuture submitted in this run (drain list)
        self.node_instances = {}  # (name, path) -> submission count, for identities
        self.outcomes = []  # deferred node outcomes, so drain waits for their logs
        self.options = options
        self.cancelled = threading.Event()

    def __repr__(self):
        return (
            f"<RunContext {self.run_id!r} node={self.node_name!r} "
            f"pool={type(self.pool).__name__} nodes={len(self.nodes)}>"
        )


@dataclass(frozen=True)
class _ContextState:
    """The execution context carried by one ContextVar.

    Immutable: every ``set_*`` replaces a single field by copy-on-write, so
    the ``ContextVar`` token/reset semantics are unchanged and a mutation is
    never visible to another thread sharing the object.
    """

    run: RunContext | None = None
    node_path: tuple = ()
    node_attempt: int | None = None
    attempt_token: AttemptToken | None = None
    run_attempt_token: AttemptToken | None = None
    in_worker: bool = False
    in_process_worker: bool = False
    in_node_body: bool = False


_EMPTY = _ContextState()

_context: contextvars.ContextVar = contextvars.ContextVar(
    "sequence_extensions_context", default=None
)

# getter name -> (setter base name, state field, value coercion)
_ACCESSORS = {
    "current_run": ("current_run", "run", None),
    "current_node_path": ("node_path", "node_path", tuple),
    "current_node_attempt": ("node_attempt", "node_attempt", None),
    "current_attempt_token": ("attempt_token", "attempt_token", None),
    "current_run_attempt_token": ("run_attempt_token", "run_attempt_token", None),
    "in_worker": ("in_worker", "in_worker", bool),
    "in_process_worker": ("in_process_worker", "in_process_worker", bool),
    "in_node_body": ("in_node_body", "in_node_body", bool),
}

# state field name -> value coercion, shared by the accessors and the scope.
_COERCE = {field: coerce for _, (_, field, coerce) in _ACCESSORS.items()}


def _state() -> _ContextState:
    """The current state, or the shared empty state outside any run."""
    st = _context.get()
    return st if st is not None else _EMPTY


def _replace(**fields):
    """Install a copy of the state with the given fields replaced."""
    return _context.set(dataclasses.replace(_state(), **fields))


def _make_accessors(getter_name, setter_name, field, coerce):
    """Build the getter/setter/resetter trio for one context field."""

    def getter():
        return _state().__getattribute__(field)

    getter.__name__ = getter_name

    def setter(value):
        return _replace(**{field: coerce(value) if coerce is not None else value})

    setter.__name__ = "set_" + setter_name

    def resetter(token):
        _context.reset(token)

    resetter.__name__ = "reset_" + setter_name
    return getter, setter, resetter


for _getter, (_setter, _field, _coerce) in _ACCESSORS.items():
    _get, _set, _reset = _make_accessors(_getter, _setter, _field, _coerce)
    globals()[_getter] = _get
    globals()["set_" + _setter] = _set
    globals()["reset_" + _setter] = _reset

del _get, _set, _reset, _getter, _setter, _field, _coerce

_MISSING = object()


@contextmanager
def execution_scope(
    *,
    ctx=_MISSING,
    path=_MISSING,
    attempt=_MISSING,
    token=_MISSING,
    run_token=_MISSING,
    worker=_MISSING,
    process_worker=_MISSING,
    in_body=_MISSING,
):
    """Install an execution position and restore it on exit.

    Omitted keyword arguments leave their field untouched.  This is the
    single place that pairs every ``set_*`` with its reset token.
    """
    provided = {}
    for field, value in (
        ("run", ctx),
        ("node_path", path),
        ("node_attempt", attempt),
        ("attempt_token", token),
        ("run_attempt_token", run_token),
        ("in_worker", worker),
        ("in_process_worker", process_worker),
        ("in_node_body", in_body),
    ):
        if value is not _MISSING:
            coerce = _COERCE.get(field)
            provided[field] = coerce(value) if coerce else value

    token = _replace(**provided) if provided else None
    try:
        yield
    finally:
        if token is not None:
            _context.reset(token)
