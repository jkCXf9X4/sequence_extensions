"""The current-run context shared by ``@flow`` and ``@task``.

A :class:`RunContext` exists for the duration of one flow call.  ``@flow``
creates it (run identity, audit log, pool) and installs it in a
``ContextVar``; ``@task`` reads it at ``submit()`` time (in the flow's
thread) and restores it inside pool workers and attempt threads, so tasks
submitted from within a task join the same run.

``ContextVar`` values do not propagate to new threads, so every thread the
flow layer starts (pool workers, timeout attempt threads) restores the
context explicitly around the code that may look it up.
"""

from __future__ import annotations

import contextvars


class RunContext:
    """One flow run: identity, audit log, pool, and submitted nodes."""

    __slots__ = ("run_id", "flow_name", "runlog", "pool", "nodes")

    def __init__(self, run_id, flow_name, runlog=None, pool=None):
        self.run_id = run_id
        self.flow_name = flow_name
        self.runlog = runlog  # RunLog | None
        self.pool = pool  # GraphPool | None
        self.nodes = []  # every GraphFuture submitted in this run (drain list)

    def __repr__(self):
        return (
            f"<RunContext {self.run_id!r} pool={type(self.pool).__name__} nodes={len(self.nodes)}>"
        )


_current_run: contextvars.ContextVar = contextvars.ContextVar(
    "sequence_extensions_current_run", default=None
)


def current_run() -> RunContext | None:
    """Return the innermost active run context, or ``None`` outside a flow."""
    return _current_run.get()


def set_current_run(ctx: RunContext | None):
    """Install ``ctx`` as the current run; returns the reset token."""
    return _current_run.set(ctx)


def reset_current_run(token) -> None:
    """Restore the previous current run (pair of :func:`set_current_run`)."""
    _current_run.reset(token)
