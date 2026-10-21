"""The current-run context shared by ``execute_flow`` and ``@node``.

A :class:`RunContext` exists for the duration of one run.  ``execute_flow``
creates it (run identity, audit log, pool, effective options) and installs
it in a ``ContextVar``; ``@node`` reads it at ``submit()`` time and restores
it inside pool workers and deferred-attempt callback threads, so nodes
submitted from within a node join the same run.

Additional ContextVars carry the execution position and the worker
markers:

* ``_node_path`` — the chain of node names currently executing
  (``("campaign", "phase")``); a node appends its own name while its body
  runs.  The run log records it as ``path``.
* ``_node_attempt`` — the enclosing node's current attempt number
  (``parent_attempt`` on descendant records).
* ``_attempt_token`` — the attempt's token; an abandoned attempt checks it
  (and its ancestors) before writing a record, so a timed-out composite
  drops late records from its subtree.
* ``_in_worker`` / ``_in_process_worker`` — set in pool workers.  Blocking
  on an incomplete future is rejected in a worker; returning the future is
  the supported way to fan out.

``ContextVar`` values do not propagate to new threads, so every thread the
layer starts (pool workers, deferred-attempt callback threads) restores the
context explicitly around the code that may look it up.
"""

from __future__ import annotations

import contextvars
import threading
from contextlib import contextmanager


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
        self.outcomes = []  # deferred node outcomes, so drain waits for their logs
        self.options = options
        self.cancelled = threading.Event()

    def __repr__(self):
        return (
            f"<RunContext {self.run_id!r} node={self.node_name!r} "
            f"pool={type(self.pool).__name__} nodes={len(self.nodes)}>"
        )


_current_run: contextvars.ContextVar = contextvars.ContextVar(
    "sequence_extensions_current_run", default=None
)
_node_path: contextvars.ContextVar = contextvars.ContextVar(
    "sequence_extensions_node_path", default=()
)
_node_attempt: contextvars.ContextVar = contextvars.ContextVar(
    "sequence_extensions_node_attempt", default=None
)
_attempt_token: contextvars.ContextVar = contextvars.ContextVar(
    "sequence_extensions_attempt_token", default=None
)
_run_attempt_token: contextvars.ContextVar = contextvars.ContextVar(
    "sequence_extensions_run_attempt_token", default=None
)
_in_worker: contextvars.ContextVar = contextvars.ContextVar(
    "sequence_extensions_in_worker", default=False
)
_in_process_worker: contextvars.ContextVar = contextvars.ContextVar(
    "sequence_extensions_in_process_worker", default=False
)


def current_run() -> RunContext | None:
    """Return the innermost active run context, or ``None`` outside a run."""
    return _current_run.get()


def set_current_run(ctx: RunContext | None):
    """Install ``ctx`` as the current run; returns the reset token."""
    return _current_run.set(ctx)


def reset_current_run(token) -> None:
    """Restore the previous current run (pair of :func:`set_current_run`)."""
    _current_run.reset(token)


def current_node_path() -> tuple:
    """The node-name chain currently executing (empty at the root)."""
    return _node_path.get()


def set_node_path(path):
    return _node_path.set(tuple(path))


def reset_node_path(token) -> None:
    _node_path.reset(token)


def current_node_attempt():
    """The enclosing node's current attempt number, or ``None`` at the root."""
    return _node_attempt.get()


def set_node_attempt(attempt):
    return _node_attempt.set(attempt)


def reset_node_attempt(token) -> None:
    _node_attempt.reset(token)


def current_attempt_token() -> AttemptToken | None:
    return _attempt_token.get()


def set_attempt_token(token):
    return _attempt_token.set(token)


def reset_attempt_token(token) -> None:
    _attempt_token.reset(token)


def current_run_attempt_token() -> AttemptToken | None:
    """The run-level timeout attempt token, or ``None`` without one."""
    return _run_attempt_token.get()


def set_run_attempt_token(token):
    return _run_attempt_token.set(token)


def reset_run_attempt_token(token) -> None:
    _run_attempt_token.reset(token)


def in_worker() -> bool:
    return _in_worker.get()


def set_in_worker(value: bool):
    return _in_worker.set(bool(value))


def reset_in_worker(token) -> None:
    _in_worker.reset(token)


def in_process_worker() -> bool:
    return _in_process_worker.get()


def set_in_process_worker(value: bool):
    return _in_process_worker.set(bool(value))


def reset_in_process_worker(token) -> None:
    _in_process_worker.reset(token)


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
):
    """Install an execution position and restore it on exit.

    Omitted keyword arguments leave their ``ContextVar`` untouched.  This is
    the single place that pairs every ``set_*`` with its reset token.
    """
    tokens = []
    values = (
        (ctx, set_current_run, reset_current_run),
        (path, set_node_path, reset_node_path),
        (attempt, set_node_attempt, reset_node_attempt),
        (token, set_attempt_token, reset_attempt_token),
        (run_token, set_run_attempt_token, reset_run_attempt_token),
        (worker, set_in_worker, reset_in_worker),
        (process_worker, set_in_process_worker, reset_in_process_worker),
    )
    try:
        for value, setter, resetter in values:
            if value is not _MISSING:
                tokens.append((resetter, setter(value)))
        yield
    finally:
        for resetter, reset_token in reversed(tokens):
            resetter(reset_token)
