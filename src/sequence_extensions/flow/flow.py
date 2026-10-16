"""``@flow`` — run identity, pool, and audit-log wiring around a function.

The decorated function is called exactly as before; the wrapper adds:

* **run identity** — a ``run_id`` (``<flow>-<UTC timestamp>-<short uuid>``)
  and a JSON-lines audit log, one file per run.  Default location:
  ``runs/<run_id>.jsonl`` under the current directory; ``log=`` selects
  another directory; ``log=None`` disables the file (tasks still run,
  just unlogged).
* **a bounded pool** — a :class:`~sequence_extensions.graph.GraphPool`
  with ``max_workers`` threads that the run's ``task.submit()`` calls
  use, unless a caller-owned ``pool=`` is supplied (never settled by
  the flow; the owner owns its lifecycle).  A
  :class:`~sequence_extensions.flow.ProcessGraphPool` swaps the workers
  for processes — CPU-bound tasks parallelize for real.  The flow body
  itself is ordinary sequential Python.
* **drain-on-return** — the flow returns only after every submitted task
  has settled, so the audit log is complete the moment the call returns.
  A flow that fails cancels its pending tasks (recorded as ``skipped``)
  and waits for the running ones.

Accepted limitations, documented here on purpose:

* **Hung tasks need ``timeout=``.**  Drain waits for every submitted
  task; Python threads cannot be preempted, so only a task-level
  ``timeout`` bounds a stuck body.
* **A retrying task holds its pool worker** through the backoff sleep.
* **Process pools need picklable tasks.**  On a
  :class:`~sequence_extensions.flow.ProcessGraphPool`, tasks and
  arguments must be picklable (module-level functions, plain data); a
  task returning a ``GraphFuture`` works in thread mode only; nested
  ``submit()`` inside a worker is unsupported.
"""

from __future__ import annotations

import concurrent.futures
import functools
import re
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sequence_extensions import config
from sequence_extensions.config import UNSET, active_config
from sequence_extensions.flow._context import (
    RunContext,
    reset_current_run,
    set_current_run,
)
from sequence_extensions.flow.process_pool import ProcessDispatchError
from sequence_extensions.flow.runlog import RunLog, jsonable
from sequence_extensions.graph.graph_future import GraphPool

try:  # package version stamped into run_start; import is cycle-free
    from sequence_extensions import __version__ as _PACKAGE_VERSION
except ImportError:  # pragma: no cover - packaging safety net
    _PACKAGE_VERSION = "unknown"

#: Default directory for run logs (relative to the current directory).
#: Kept as a re-export: the constant lives in :mod:`sequence_extensions.config`.
DEFAULT_LOG_DIR = config.DEFAULT_LOG_DIR

_LOG_PATH_TYPES = (str, Path)


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _new_run_id(flow_name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", flow_name).strip("-") or "flow"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"{safe}-{stamp}-{uuid.uuid4().hex[:8]}"


def _settle(pool: GraphPool) -> None:
    """Cancel pending nodes and shut the executor down, waiting for running.

    ``GraphPool.__exit__`` called directly (no ``__enter__`` needed — the
    executor is created lazily; a pool that never ran anything is a
    no-op).  See the module docstring for the process-wide cancel caveat.
    """
    pool.__exit__(None, None, None)


def _drain(ctx: RunContext) -> None:
    """Wait for every submitted node; repeat until no new nodes appear.

    Failures are swallowed here on purpose: every attempt is already in
    the audit log, and the exception surfaces through whichever future
    the caller gathers.  A node that was cancelled (another pool's
    exit — see module docstring) must not crash the flow's return path.
    """
    seen = set()
    while True:
        pending = [node for node in ctx.nodes if node not in seen]
        if not pending:
            return
        for node in pending:
            seen.add(node)
            try:
                node.result()
            except (Exception, concurrent.futures.CancelledError):
                pass


def _write_settle_records(ctx: RunContext, *, flow_failed: bool) -> None:
    """Every settle-time record, written by the flow thread before run_end.

    Replayed worker records first (process pools), then one skip record
    per node that never executed: cancelled by the flow's failure, or
    failed because its dependency or process dispatch failed.  Never
    called from a done-callback — ``set_result`` wakes drain waiters
    before callbacks finish, so a callback-side write could race
    ``run_end`` closing the log.
    """
    if ctx.runlog is None:
        return
    for node in ctx.nodes:
        for record in getattr(node, "_process_records", None) or ():
            ctx.runlog.write(record)
    for node in ctx.nodes:
        if getattr(node, "_flow_attempted", False) or getattr(node, "_process_attempted", False):
            continue
        if node.cancelled():
            if flow_failed:
                ctx.runlog.write(
                    {
                        "record": "task",
                        "run_id": ctx.run_id,
                        "task": node.name,
                        "attempt": 0,
                        "status": "skipped",
                        "reason": "cancelled (flow failed)",
                    }
                )
            continue
        try:
            exc = node.exception()
        except concurrent.futures.CancelledError:
            continue
        if exc is None:
            continue
        ctx.runlog.write(
            {
                "record": "task",
                "run_id": ctx.run_id,
                "task": node.name,
                "attempt": 0,
                "status": "skipped",
                "reason": (
                    "dispatch failed"
                    if isinstance(exc, ProcessDispatchError)
                    else "dependency failed"
                ),
                "error": {"type": type(exc).__qualname__, "message": str(exc)},
            }
        )


def flow(
    fn=None,
    *,
    name: str | None = None,
    max_workers=UNSET,
    log=UNSET,
    summary=UNSET,
    pool: GraphPool | None = None,
):
    """Decorate a function as a flow: run identity + pool + audit log.

    Keywords (``max_workers``, ``log``, ``summary``) left unset resolve
    per call from the active configuration — see
    :mod:`sequence_extensions.config`; an explicit keyword always wins.

    Keywords:

    * ``name`` — flow name for the run id and log records (default: the
      function's ``__name__``).
    * ``max_workers`` — thread pool size for the run's ``task.submit()``
      calls.
    * ``log`` — directory for ``<run_id>.jsonl`` (default: ``"runs"``);
      ``None`` disables the file.
    * ``summary`` — summarize bulky values in the log (item counts
      instead of items); paths are always path-plus-hash.
    * ``pool`` — a caller-owned pool to submit on instead of a fresh
      per-run thread pool: a :class:`~sequence_extensions.graph.GraphPool`
      (threads) or a :class:`~sequence_extensions.flow.ProcessGraphPool`
      (processes, for CPU-bound tasks).  A caller-owned pool is never
      settled by the flow; its lifecycle is the owner's.

    The function body is plain Python.  Tasks are called directly
    (sequential) or via ``task.submit()`` (concurrent); passing futures
    as submit arguments creates dependency edges.

    The wrapper carries two attributes tooling can rely on:
    ``__flow__`` (the flow name — how ``flow-runner`` discovers flows)
    and ``last_run`` (a dict with ``run_id``, ``status``, ``log``,
    ``duration_ms`` of the most recent call; concurrent calls to the
    same flow race — last writer wins).
    """

    def _decorate(fn: Callable) -> Callable:
        if log is not UNSET and log is not None and not isinstance(log, _LOG_PATH_TYPES):
            raise TypeError(f"log must be a directory path or None, got {log!r}")
        if pool is not None and not isinstance(pool, GraphPool):
            raise TypeError(f"pool must be a GraphPool or None, got {pool!r}")
        flow_name = name or getattr(fn, "__name__", "flow")

        @functools.wraps(fn)
        def _wrapper(*args, **kwargs):
            # Resolve unset keywords per call — the active configuration,
            # or the built-in defaults without one.  Explicit keywords
            # (closure values) keep winning.
            cfg = active_config()
            workers = max_workers if max_workers is not UNSET else cfg.flow.max_workers
            log_dir = log if log is not UNSET else cfg.flow.log
            summarize = summary if summary is not UNSET else cfg.flow.summary
            if log_dir == "":  # the config-file spelling of "disabled"
                log_dir = None
            run_id = _new_run_id(flow_name)
            runlog = None
            if log_dir is not None:
                runlog = RunLog(Path(log_dir) / f"{run_id}.jsonl", summary=summarize)
            ctx = RunContext(run_id=run_id, flow_name=flow_name, runlog=runlog)
            started = time.perf_counter()
            status = "ok"
            if runlog is not None:
                runlog.open()
                runlog.write(
                    {
                        "record": "run_start",
                        "run_id": run_id,
                        "flow": flow_name,
                        "started": _utcnow(),
                        "version": _PACKAGE_VERSION,
                        "args": [jsonable(a, summary=summarize) for a in args],
                        "kwargs": {k: jsonable(v, summary=summarize) for k, v in kwargs.items()},
                    }
                )
            owned_pool = None if pool is not None else GraphPool(max_workers=workers)
            ctx.pool = pool if pool is not None else owned_pool
            token = set_current_run(ctx)
            try:
                result = fn(*args, **kwargs)
            except BaseException as error:
                status = "error"
                if owned_pool is not None:
                    _settle(owned_pool)
                else:
                    # A caller-owned pool is never settled by the flow;
                    # drain instead so no record lands after run_end.
                    _drain(ctx)
                _write_settle_records(ctx, flow_failed=True)
                if runlog is not None:
                    runlog.write(
                        {
                            "record": "run_end",
                            "run_id": run_id,
                            "status": "error",
                            "ended": _utcnow(),
                            "duration_ms": int((time.perf_counter() - started) * 1000),
                            "error": {
                                "type": type(error).__qualname__,
                                "message": str(error),
                            },
                        }
                    )
                raise
            else:
                _drain(ctx)
                if owned_pool is not None:
                    _settle(owned_pool)
                _write_settle_records(ctx, flow_failed=False)
                if runlog is not None:
                    runlog.write(
                        {
                            "record": "run_end",
                            "run_id": run_id,
                            "status": "ok",
                            "ended": _utcnow(),
                            "duration_ms": int((time.perf_counter() - started) * 1000),
                            "result": jsonable(result, summary=summarize),
                        }
                    )
                return result
            finally:
                _wrapper.last_run = {
                    "run_id": run_id,
                    "flow": flow_name,
                    "status": status,
                    "log": str(runlog.path) if runlog is not None else None,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                }
                reset_current_run(token)
                if runlog is not None:
                    runlog.close()

        _wrapper.__flow__ = flow_name
        _wrapper.last_run = None
        return _wrapper

    if fn is None:
        return _decorate
    return _decorate(fn)
