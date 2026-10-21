"""``execute_flow`` — the explicit run boundary.

A run is a call, not a decorator::

    run = execute_flow(campaign, cases_dir, options=RunOptions(max_workers=8))

The call creates the run identity (``run_id``), a bounded pool, and a
JSON-lines audit log, executes the root node, drains every submitted node,
and returns a :class:`Run`.  A failure raises the node's exception with
``.run`` attached.

``execute_flow`` is a **top-level entry point**.  A node body composes
other nodes by calling them or by submitting them and returning a future;
a nested run is not opened.  This keeps one run identity, one pool, and one
audit log for the whole node tree.

Semantics:

* **run identity** — ``run_id`` is ``<name>-<UTC timestamp>-<short uuid>``;
  ``fixed_clock=True`` pins it to ``<name>-fixed`` and makes an identical
  run byte-identical (see :mod:`sequence_extensions.flow.runlog`).
* **drain-on-return** — the run returns only after every submitted node
  settles.  A failed run cancels its own pool's pending nodes (recorded
  ``skipped``) and waits for the running ones.
* **run retries** — one run file per attempt; the exception carries the
  last attempt's :class:`Run`.
* **run timeout** — bounds the whole attempt: the root executes in a
  thread joined with the budget; on expiry the run's pool is cancelled,
  the log is abandoned (late records are dropped), ``run_end`` records
  ``timeout``, and :class:`~sequence_extensions.flow.node.NodeTimeoutError`
  is raised.
* **a caller-owned pool** (``RunOptions.pool=``) is never settled by the
  run; its lifecycle belongs to the caller.

Accepted limits: hung nodes need ``timeout=``; process pools need
picklable nodes; process workers cannot submit or return live futures, so
process-mode fan-out is built in the parent process; ``execute_flow``
inside an active run is rejected.
"""

from __future__ import annotations

import concurrent.futures
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sequence_extensions.flow._context import (
    AttemptToken,
    RunContext,
    current_run,
    in_process_worker,
    reset_attempt_token,
    reset_current_run,
    reset_in_process_worker,
    reset_in_worker,
    reset_node_attempt,
    reset_node_path,
    reset_run_attempt_token,
    set_attempt_token,
    set_current_run,
    set_in_process_worker,
    set_in_worker,
    set_node_attempt,
    set_node_path,
    set_run_attempt_token,
)
from sequence_extensions.flow._options import RunOptions
from sequence_extensions.flow.node import NodeFunction, NodeTimeoutError
from sequence_extensions.flow.process_pool import ProcessDispatchError
from sequence_extensions.flow.runlog import RunLog, jsonable
from sequence_extensions.graph.graph_future import GraphPool

try:  # package version stamped into run_start; import is cycle-free
    from sequence_extensions import __version__ as _PACKAGE_VERSION
except ImportError:  # pragma: no cover - packaging safety net
    _PACKAGE_VERSION = "unknown"

__all__ = ["Run", "execute_flow"]


@dataclass(frozen=True)
class Run:
    """The account of one run: outcome, identity, and where the truth lives."""

    result: Any
    run_id: str
    node: str
    status: str  # "ok" | "error" | "timeout"
    log: Path | None
    duration_ms: int
    attempt: int
    started: str
    ended: str
    error: BaseException | None = None


# ---------------------------------------------------------------- #
# Identity
# ---------------------------------------------------------------- #
def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "node"


def _new_run_id(name: str, *, fixed: bool) -> str:
    safe = _safe_name(name)
    if fixed:
        return f"{safe}-fixed"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"{safe}-{stamp}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------- #
# Public entry point
# ---------------------------------------------------------------- #
def execute_flow(node: NodeFunction, *args, options: RunOptions | None = None, **kwargs) -> Run:
    """Execute ``node`` as a run and return its :class:`Run`.

    ``options`` is reserved; pass a node parameter named ``options``
    positionally.  A failure raises the node's exception with ``.run``
    set to the last attempt's account.
    """
    if not isinstance(node, NodeFunction):
        raise TypeError(f"execute_flow() expects a @node function, got {node!r}")
    if options is None:
        options = RunOptions()
    if not isinstance(options, RunOptions):
        raise TypeError(f"options must be RunOptions or None, got {options!r}")
    if in_process_worker():
        raise RuntimeError(
            "execute_flow() inside a process worker is not supported in 3.0; "
            "build the process-mode graph in the parent process"
        )
    if current_run() is not None:
        raise RuntimeError(
            "execute_flow() is a top-level entry point; a node body composes nodes "
            "by calling them or by submitting them and returning a future"
        )

    resolved = options.resolve(node.name)
    if resolved.fixed_clock and int(resolved.retries) > 0:
        raise ValueError("fixed_clock reference mode does not support run retries")

    attempts = int(resolved.retries) + 1
    delay = float(resolved.retry_delay_seconds)
    for attempt in range(1, attempts + 1):
        try:
            return _run_once(node, args, kwargs, resolved, attempt)
        except BaseException as exc:
            if isinstance(exc, Exception) and attempt < attempts:
                if delay > 0:
                    time.sleep(delay)
                continue
            raise
    raise AssertionError("unreachable: the run retry loop always returns or raises")


# ---------------------------------------------------------------- #
# One run attempt
# ---------------------------------------------------------------- #
def _install_run(ctx: RunContext):
    """Install the run context and reset the execution position/worker markers."""
    return (
        set_current_run(ctx),
        set_node_path(()),
        set_node_attempt(None),
        set_attempt_token(None),
        set_run_attempt_token(None),
        set_in_worker(False),
        set_in_process_worker(False),
    )


def _restore_run(tokens) -> None:
    (
        run_token,
        path_token,
        attempt_token,
        token_token,
        run_attempt_token,
        worker_token,
        process_token,
    ) = tokens
    reset_in_process_worker(process_token)
    reset_in_worker(worker_token)
    reset_run_attempt_token(run_attempt_token)
    reset_attempt_token(token_token)
    reset_node_attempt(attempt_token)
    reset_node_path(path_token)
    reset_current_run(run_token)


def _run_once(node, args, kwargs, options, attempt) -> Run:
    run_id = _new_run_id(options.name, fixed=bool(options.fixed_clock))

    runlog = None
    if options.log is not None:
        runlog = RunLog(
            Path(options.log) / f"{run_id}.jsonl",
            summary=bool(options.summary),
            fixed_clock=bool(options.fixed_clock),
        )

    owned_pool = None
    pool = options.pool
    if pool is None:
        owned_pool = GraphPool(max_workers=options.max_workers)
        pool = owned_pool

    ctx = RunContext(
        run_id=run_id,
        node_name=options.name,
        runlog=runlog,
        pool=pool,
        options=options,
    )

    started_clock = time.perf_counter()
    started = _utcnow()
    status = "ok"
    result = None
    error: BaseException | None = None
    duration_ms = 0
    ended = started
    run_tokens = _install_run(ctx)
    try:
        if runlog is not None:
            runlog.open()
            start_record = {
                "record": "run_start",
                "run_id": run_id,
                "node": options.name,
                "attempt": attempt,
                "started": started,
                "version": _PACKAGE_VERSION,
                "args": [jsonable(a, summary=bool(options.summary)) for a in args],
                "kwargs": {
                    k: jsonable(v, summary=bool(options.summary)) for k, v in kwargs.items()
                },
            }
            runlog.write(start_record)

        try:
            result = _call_root(node, args, kwargs, options.timeout, ctx, attempt)
        except BaseException as exc:
            error = exc
            run_level_timeout = (
                isinstance(exc, NodeTimeoutError)
                and getattr(exc, "run_timeout", None) == run_id
            )
            status = "timeout" if run_level_timeout else "error"
            ctx.cancelled.set()

        if status == "ok":
            _drain(ctx)
            if owned_pool is not None:
                _settle(owned_pool)
            _write_settle_records(ctx, run_failed=False)
        else:
            if owned_pool is not None:
                _settle(owned_pool)
            if status != "timeout":
                _drain(ctx)
            _write_settle_records(ctx, run_failed=True)

        duration_ms = int((time.perf_counter() - started_clock) * 1000)
        ended = _utcnow()
        if runlog is not None:
            end_record: dict = {
                "record": "run_end",
                "run_id": run_id,
                "status": status,
                "ended": ended,
                "duration_ms": duration_ms,
            }
            if status == "ok":
                end_record["result"] = jsonable(result, summary=bool(options.summary))
            else:
                end_record["error"] = {
                    "type": type(error).__qualname__,
                    "message": str(error),
                }
            runlog.write(end_record)
    finally:
        _restore_run(run_tokens)
        if runlog is not None:
            # Safety net: an abandoned attempt must never write again.
            runlog.abandon()
            runlog.close()

    run = Run(
        result=result,
        run_id=run_id,
        node=options.name,
        status=status,
        log=runlog.path if runlog is not None else None,
        duration_ms=duration_ms,
        attempt=attempt,
        started=started,
        ended=ended,
        error=error,
    )
    if status != "ok":
        _attach_run(error, run)
        raise error
    return run


def _call_root(node, args, kwargs, timeout, ctx, attempt):
    """Run the root node, optionally bounded by the run-level timeout."""
    if timeout is None:
        return node(*args, **kwargs)

    box = {}
    outer = AttemptToken()

    def _target():
        tokens = _install_run(ctx)
        outer_token = set_run_attempt_token(outer)
        try:
            box["result"] = node(*args, **kwargs)
        except BaseException as exc:
            box["error"] = exc
        finally:
            reset_run_attempt_token(outer_token)
            _restore_run(tokens)

    import threading

    thread = threading.Thread(target=_target, name=f"{node.name}-run-attempt", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        # The attempt cannot be preempted; drop its late records and stop
        # any further retries or submits.
        outer.abandoned.set()
        ctx.cancelled.set()
        error = NodeTimeoutError(node.name, timeout, attempt)
        error.run_timeout = ctx.run_id
        raise error
    if "error" in box:
        raise box["error"]
    return box.get("result")


# ---------------------------------------------------------------- #
# Drain / settle
# ---------------------------------------------------------------- #
def _settle(pool: GraphPool) -> None:
    """Cancel pending nodes and shut the executor down, waiting for running."""
    pool.__exit__(None, None, None)


def _drain(ctx: RunContext) -> None:
    """Wait for every submitted node and deferred outcome.

    Outcomes are part of the drain because a returned future can settle
    after its GraphFuture is cancelled; waiting for the outcome guarantees
    the attempt record is in the log before ``run_end``.  Failures are
    swallowed here on purpose: every attempt is already in the audit log,
    and the exception surfaces through whichever future the caller
    gathers.  A cancelled node must not crash the return path.
    """
    seen_nodes = set()
    seen_outcomes = set()
    while True:
        pending_nodes = [node for node in ctx.nodes if node not in seen_nodes]
        pending_outcomes = [
            outcome for outcome in ctx.outcomes if outcome not in seen_outcomes
        ]
        if not pending_nodes and not pending_outcomes:
            return
        for node in pending_nodes:
            seen_nodes.add(node)
            try:
                node.result()
            except (Exception, concurrent.futures.CancelledError):
                pass
        for outcome in pending_outcomes:
            seen_outcomes.add(outcome)
            try:
                outcome.result()
            except (Exception, concurrent.futures.CancelledError):
                pass


def _settle_record(ctx: RunContext, node, *, reason: str, error=None) -> dict:
    record = {
        "record": "node",
        "run_id": ctx.run_id,
        "node": node.name,
        "path": list(getattr(node, "_seqext_path", (node.name,))),
        "attempt": 0,
        "parent_attempt": getattr(node, "_seqext_parent_attempt", None),
        "status": "skipped",
        "reason": reason,
    }
    if error is not None:
        record["error"] = {"type": type(error).__qualname__, "message": str(error)}
    return record


def _write_settle_records(ctx: RunContext, *, run_failed: bool) -> None:
    """Every settle-time record, written by the run thread before run_end.

    Replayed worker records first (process pools), then one skip record
    per node that never executed: cancelled by the run's failure, or
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
            if run_failed:
                ctx.runlog.write(_settle_record(ctx, node, reason="cancelled (run failed)"))
            continue
        try:
            exc = node.exception()
        except concurrent.futures.CancelledError:
            continue
        if exc is None:
            continue
        ctx.runlog.write(
            _settle_record(
                ctx,
                node,
                reason=(
                    "dispatch failed"
                    if isinstance(exc, ProcessDispatchError)
                    else "dependency failed"
                ),
                error=exc,
            )
        )


def _attach_run(error: BaseException, run: Run) -> None:
    """Expose the failed attempt's account on the raised exception."""
    try:
        error.run = run
    except Exception:  # pragma: no cover - exotic exception without __dict__
        pass
