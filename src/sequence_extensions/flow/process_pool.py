"""``ProcessGraphPool`` — a process-pool executor for CPU-bound nodes.

A :class:`~sequence_extensions.graph.GraphPool` subclass driving a
:class:`concurrent.futures.ProcessPoolExecutor` behind the same
``bind`` / ``result`` / exit surface, so ``execute_flow(..., options=
RunOptions(pool=ProcessGraphPool()))`` swaps local parallelism from threads
to worker processes — the fix for CPU-bound node bodies, which the GIL
serializes under a thread pool.

Contract:

* **Picklable payloads.**  Nodes and their arguments must be picklable —
  module-level functions and plain data.  A lambda or closure fails at
  dispatch and surfaces as :class:`ProcessDispatchError`.
* **Records replay in the parent.**  A worker cannot write the parent's
  open run-log file, so the worker buffers attempt records in a
  `_ProcessOutcome` and the parent replays them when the future settles —
  the log is still complete when the run returns.
* **Dependencies resolve in the parent.**  Edges resolve before dispatch,
  so a failed dependency skips the dependent without a process
  round-trip (same ``skipped`` record as thread mode).

Accepted limits: a node body running in a process worker cannot return a
live future; ``node.submit()`` inside a process worker is not supported
(the worker has no pool), so process-mode fan-out is built in the parent
process; ``execute_flow()`` inside a process worker is rejected in 3.0; a
timed-out attempt is abandoned as a daemon thread *in the worker process*.
"""

from __future__ import annotations

import concurrent.futures
import multiprocessing
import threading

from sequence_extensions.flow._context import RunContext, execution_scope
from sequence_extensions.flow._options import RunOptions
from sequence_extensions.graph.graph_future import (
    GraphFuture,
    GraphPool,
    _set_exception_if_pending,
)

__all__ = ["ProcessDispatchError", "ProcessGraphPool"]


class ProcessDispatchError(RuntimeError):
    """A node's payload could not be dispatched to a worker process.

    Wraps pickling failures and executor breakdowns; the run log records
    the node as ``skipped`` with reason ``dispatch failed``.
    """


class _ProcessOutcome:
    """Worker-to-parent transport for one node execution."""

    __slots__ = ("value", "error", "records")

    def __init__(self, value, error, records):
        self.value = value
        self.error = error
        self.records = records


class _RecordBuffer:
    """A :class:`~sequence_extensions.flow.runlog.RunLog` stand-in that
    collects records in worker memory."""

    def __init__(self, summary: bool):
        self.summary = bool(summary)
        self.records: list = []

    def write(self, record: dict) -> None:
        self.records.append(record)


def _process_node_runner(node_fn, run_info, *args, **kwargs):
    """Worker-side entry point for one node (picklable by contract).

    Runs the node's attempt loop against an in-memory record buffer and
    returns a `_ProcessOutcome` for the parent to replay.
    """
    threading.current_thread().name = f"proc-{multiprocessing.current_process().name}"
    sink = _RecordBuffer(run_info["summary"])
    ctx = RunContext(
        run_id=run_info["run_id"],
        node_name=run_info["node_name"],
        runlog=sink,
        options=RunOptions(node_defaults=run_info.get("node_defaults")),
    )
    error = None
    with execution_scope(
        ctx=ctx,
        path=tuple(run_info.get("parent_path") or ()),
        attempt=run_info.get("parent_attempt"),
        worker=False,
        process_worker=True,
        # A fork inherits the parent's context: reset the body marker so this
        # worker's own node body (inside _execute) is the only body in scope.
        in_body=False,
    ):
        try:
            value = node_fn._execute(args, kwargs, ctx)
        except Exception as exc:  # _execute already wraps BaseExceptions
            value = None
            error = exc
    return _ProcessOutcome(value=value, error=error, records=sink.records)


class ProcessGraphPool(GraphPool):
    """Evaluate a GraphFuture graph with a bounded process pool.

    Same surface as :class:`~sequence_extensions.graph.GraphPool`
    (``bind``, ``result``, context manager, pool-scoped cancellation on
    exit); the workers are processes.  ``max_workers=None`` keeps the
    executor's own default (the CPU count).
    """

    process_workers = True

    def __init__(self, max_workers=None):
        """Create a process pool; ``None`` keeps the executor's CPU-count default."""
        super().__init__(max_workers=max_workers)

    def _ensure_executor(self) -> None:
        """Lazily create the process executor (subclass seam)."""
        if self._shutdown:
            return
        if self._executor is None:
            self._executor = concurrent.futures.ProcessPoolExecutor(max_workers=self.max_workers)

    def _submit_node(self, node: GraphFuture) -> None:
        """Dispatch a node to a worker process (subclass seam).

        Dependencies resolve here, in the parent, before dispatch: a
        failed dependency settles the node with that exception — the
        same path thread mode takes inside ``GraphFuture._run``.
        """
        with self._bind_lock:
            if self._shutdown:
                node.future.cancel()
                return
            self._ensure_executor()
            executor = self._executor
        try:
            args, kwargs = node._resolve_arguments()
        except Exception as exc:
            _set_exception_if_pending(node.future, exc)  # dependency failure
            return
        try:
            pfuture = executor.submit(node.function, *args, **kwargs)
        except Exception as exc:
            _set_exception_if_pending(
                node.future, ProcessDispatchError(f"{type(exc).__name__}: {exc}")
            )
            return

        def _settle(pfuture, node=node):
            """Settle the node's future from the process future (parent).

            InvalidStateError: the node's future was already cancelled
            (pool exit raced the worker result) — the completion is
            discarded, mirroring thread-mode behavior.
            """
            try:
                if pfuture.cancelled():
                    node.future.cancel()
                    return
                try:
                    outcome = pfuture.result()
                except Exception as exc:
                    node.future.set_exception(ProcessDispatchError(f"{type(exc).__name__}: {exc}"))
                    return
                if isinstance(outcome, _ProcessOutcome):
                    # Visible to done-callbacks before the settle completes.
                    node.process_records = outcome.records
                    node.attempted = True
                    if outcome.error is None:
                        node.future.set_result(outcome.value)
                    else:
                        node.future.set_exception(outcome.error)
                else:
                    node.future.set_result(outcome)
            except concurrent.futures.InvalidStateError:
                pass

        pfuture.add_done_callback(_settle)
