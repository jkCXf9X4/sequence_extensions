"""Run a callable on a daemon thread with a join-timeout verdict.

Shared by the node attempt loop and the run-level root call: both execute
a body in a daemon thread, join it with a budget, and need the same
tri-state verdict (timed out / errored / result).  A timed-out thread is
not preempted; it may still land its side effects, so the verdict carries
no result.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class _TimedRun:
    """Outcome of a timed daemon-thread run; exactly one field applies."""

    timed_out: bool = False
    error: BaseException | None = None
    result: object = None


def _run_with_timeout(target, timeout, *, thread_name) -> _TimedRun:
    """Run ``target`` in a daemon thread joined with ``timeout``.

    ``timed_out`` when the body outlives the budget (the thread keeps
    running); ``error`` when the body raised (``BaseException``); else
    ``result``.
    """
    box = {}

    def _target():
        try:
            box["result"] = target()
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=_target, name=thread_name, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return _TimedRun(timed_out=True)
    if "error" in box:
        return _TimedRun(error=box["error"])
    return _TimedRun(result=box.get("result"))
