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

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sequence_extensions.flow._context import (
    AttemptToken,
    RunContext,
    current_run,
    execution_scope,
    in_process_worker,
)
from sequence_extensions.flow._futures import NodeTimeoutError
from sequence_extensions.flow._identity import new_run_id, utcnow
from sequence_extensions.flow._options import RunOptions
from sequence_extensions.flow._records import run_end_record, run_start_record
from sequence_extensions.flow._settle import (
    drain,
    failed_node_paths,
    settle,
    write_settle_records,
)
from sequence_extensions.flow.node import NodeFunction
from sequence_extensions.flow.runlog import RunLog
from sequence_extensions.graph.graph_future import GraphPool

try:  # package version stamped into run_start; import is cycle-free
    from sequence_extensions import __version__ as _PACKAGE_VERSION
except ImportError:  # pragma: no cover - packaging safety net
    _PACKAGE_VERSION = "unknown"

__all__ = ["Run", "execute_flow"]

RunStatus = Literal["ok", "error", "timeout"]


@dataclass(frozen=True)
class Run:
    """The account of one run: outcome, identity, and where the truth lives.

    ``failed_nodes`` lists the paths of submitted nodes whose settled future
    carries an exception, including work the root never gathered.  It makes a
    fire-and-forget failure visible even when ``status`` reflects a successful
    root.
    """

    result: Any
    run_id: str
    node: str
    status: RunStatus
    log: Path | None
    duration_ms: int
    attempt: int
    started: str
    ended: str
    error: BaseException | None = None
    failed_nodes: tuple[tuple[str, ...], ...] = ()


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
class _RunAttempt:
    """One documented run attempt: identity, log, pool, drain, and result."""

    def __init__(self, node, args, kwargs, options: RunOptions, attempt: int):
        self.node = node
        self.args = args
        self.kwargs = kwargs
        self.options = options
        self.attempt = attempt
        self.run_id = new_run_id(options.name, fixed=bool(options.fixed_clock))
        self.runlog = (
            RunLog(
                Path(options.log) / f"{self.run_id}.jsonl",
                summary=bool(options.summary),
                fixed_clock=bool(options.fixed_clock),
            )
            if options.log is not None
            else None
        )
        self.owned_pool = None
        self.pool = options.pool
        if self.pool is None:
            self.owned_pool = GraphPool(max_workers=options.max_workers)
            self.pool = self.owned_pool
        self.ctx = RunContext(
            run_id=self.run_id,
            node_name=options.name,
            runlog=self.runlog,
            pool=self.pool,
            options=options,
        )
        self.started_clock = time.perf_counter()
        self.started = utcnow()
        self.status: RunStatus = "ok"
        self.result = None
        self.error: BaseException | None = None
        self.duration_ms = 0
        self.ended = self.started
        self.pool_settled = False
        self.failed_nodes: tuple[tuple[str, ...], ...] = ()

    def run(self) -> Run:
        try:
            with execution_scope(
                ctx=self.ctx,
                path=(),
                attempt=None,
                token=None,
                run_token=None,
                worker=False,
                process_worker=False,
            ):
                self._write_start()
                self._execute_root()
                self._finish_records()
        finally:
            self._close()
        run = self._build_run()
        if self.status != "ok":
            _attach_run(self.error, run)
            raise self.error
        return run

    def _write_start(self) -> None:
        if self.runlog is None:
            return
        self.runlog.open()
        self.runlog.write(
            run_start_record(
                run_id=self.run_id,
                node=self.options.name,
                attempt=self.attempt,
                started=self.started,
                version=_PACKAGE_VERSION,
                args=self.args,
                kwargs=self.kwargs,
                summary=bool(self.options.summary),
            )
        )

    def _execute_root(self) -> None:
        try:
            self.result = _call_root(
                self.node,
                self.args,
                self.kwargs,
                self.options.timeout,
                self.ctx,
                self.attempt,
            )
        except BaseException as exc:
            self.error = exc
            run_level_timeout = (
                isinstance(exc, NodeTimeoutError)
                and getattr(exc, "run_timeout", None) == self.run_id
            )
            self.status = "timeout" if run_level_timeout else "error"
            self.ctx.cancelled.set()

    def _finish_records(self) -> None:
        if self.status == "ok":
            drain(self.ctx)
            self._settle_pool()
            write_settle_records(self.ctx, run_failed=False)
        else:
            self._settle_pool()
            if self.status != "timeout":
                drain(self.ctx)
            write_settle_records(self.ctx, run_failed=True)

        self.failed_nodes = failed_node_paths(self.ctx)
        self.duration_ms = int((time.perf_counter() - self.started_clock) * 1000)
        self.ended = utcnow()
        if self.runlog is None:
            return
        self.runlog.write(
            run_end_record(
                run_id=self.run_id,
                status=self.status,
                ended=self.ended,
                duration_ms=self.duration_ms,
                failed_nodes=self.failed_nodes,
                result=self.result,
                error=self.error,
                summary=bool(self.options.summary),
            )
        )

    def _settle_pool(self) -> None:
        if self.owned_pool is not None:
            settle(self.owned_pool)
            self.pool_settled = True

    def _close(self) -> None:
        try:
            if self.owned_pool is not None and not self.pool_settled:
                # Unexpected failure before the normal settle branch: the
                # run still owns the pool and must not leak its executor.
                settle(self.owned_pool)
        finally:
            if self.runlog is not None:
                # Safety net: an abandoned attempt must never write again.
                self.runlog.abandon()
                self.runlog.close()

    def _build_run(self) -> Run:
        return Run(
            result=self.result,
            run_id=self.run_id,
            node=self.options.name,
            status=self.status,
            log=self.runlog.path if self.runlog is not None else None,
            duration_ms=self.duration_ms,
            attempt=self.attempt,
            started=self.started,
            ended=self.ended,
            error=self.error,
            failed_nodes=self.failed_nodes,
        )


def _run_once(node, args, kwargs, options, attempt) -> Run:
    return _RunAttempt(node, args, kwargs, options, attempt).run()


def _call_root(node, args, kwargs, timeout, ctx, attempt):
    """Run the root node, optionally bounded by the run-level timeout."""
    if timeout is None:
        return node(*args, **kwargs)

    box = {}
    outer = AttemptToken()

    def _target():
        with execution_scope(
            ctx=ctx,
            path=(),
            attempt=None,
            token=None,
            run_token=outer,
            worker=False,
            process_worker=False,
        ):
            try:
                box["result"] = node(*args, **kwargs)
            except BaseException as exc:
                box["error"] = exc

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


def _attach_run(error: BaseException, run: Run) -> None:
    """Expose the failed attempt's account on the raised exception."""
    try:
        error.run = run
    except Exception:  # pragma: no cover - exotic exception without __dict__
        pass
