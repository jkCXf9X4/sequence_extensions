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
  :class:`NodeOutcome` and the parent replays them when the future
  settles — the log is still complete when the run returns.
* **Dependencies resolve in the parent.**  Edges resolve before dispatch,
  so a failed dependency skips the dependent without a process
  round-trip (same ``skipped`` record as thread mode).

Accepted limits: a node returning a future works in thread mode only;
``node.submit()`` inside a process worker is not supported (the worker has
no pool), so process-mode fan-out is built in the parent process;
``execute_flow()`` inside a process worker is rejected in 3.0; a timed-out
attempt is abandoned as a daemon thread *in the worker process*.
"""

from __future__ import annotations

import concurrent.futures
import multiprocessing
import threading

from sequence_extensions.flow._context import (
    RunContext,
    reset_current_run,
    reset_in_process_worker,
    reset_in_worker,
    reset_node_attempt,
    reset_node_path,
    set_current_run,
    set_in_process_worker,
    set_in_worker,
    set_node_attempt,
    set_node_path,
)
from sequence_extensions.flow._options import NodePolicy, RunOptions
from sequence_extensions.graph.graph_future import GraphFuture, GraphPool

__all__ = ["ProcessDispatchError", "ProcessGraphPool"]


class ProcessDispatchError(RuntimeError):
    """A node's payload could not be dispatched to a worker process.

    Wraps pickling failures and executor breakdowns; the run log records
    the node as ``skipped`` with reason ``dispatch failed``.
    """


class NodeOutcome:
    """Worker-to-parent transport for one node execution.

    Carries the value or error, the buffered attempt records, and whether
    the node body was attempted at all.
    """

    __slots__ = ("value", "error", "records", "attempted")

    def __init__(self, value, error, records, attempted):
        self.value = value
        self.error = error
        self.records = records
        self.attempted = attempted


class _RecordBuffer:
    """A :class:`~sequence_extensions.flow.runlog.RunLog` stand-in that
    collects records in worker memory."""

    def __init__(self, summary: bool):
        self.summary = bool(summary)
        self.records: list = []
        self.abandoned = False

    def write(self, record: dict) -> None:
        self.records.append(record)

    def abandon(self) -> None:
        self.abandoned = True


def _process_node_runner(node_fn, run_info, *args, **kwargs):
    """Worker-side entry point for one node (picklable by contract).

    Runs the node's attempt loop against an in-memory record buffer and
    returns a :class:`NodeOutcome` for the parent to replay.
    """
    threading.current_thread().name = f"proc-{multiprocessing.current_process().name}"
    sink = _RecordBuffer(run_info["summary"])
    defaults = run_info.get("node_defaults")
    if defaults is not None and not isinstance(defaults, NodePolicy):
        defaults = None
    ctx = RunContext(
        run_id=run_info["run_id"],
        node_name=run_info["node_name"],
        runlog=sink,
        options=RunOptions(node_defaults=defaults),
    )
    run_token = set_current_run(ctx)
    path_token = set_node_path(tuple(run_info.get("parent_path") or ()))
    attempt_token = set_node_attempt(run_info.get("parent_attempt"))
    worker_token = set_in_worker(False)
    process_token = set_in_process_worker(True)
    error = None
    try:
        value = node_fn._execute(args, kwargs, ctx)
    except Exception as exc:  # _execute already wraps BaseExceptions
        value = None
        error = exc
    finally:
        reset_in_process_worker(process_token)
        reset_in_worker(worker_token)
        reset_node_attempt(attempt_token)
        reset_node_path(path_token)
        reset_current_run(run_token)
    return NodeOutcome(value=value, error=error, records=sink.records, attempted=True)


class ProcessGraphPool(GraphPool):
    """Evaluate a GraphFuture graph with a bounded process pool.

    Same surface as :class:`~sequence_extensions.graph.GraphPool`
    (``bind``, ``result``, context manager, pool-scoped cancellation on
    exit); the workers are processes.  ``max_workers=None`` keeps the
    executor's own default (the CPU count).
    """

    def __init__(self, max_workers=None):
        """Create a process pool; the executor is created lazily on first use."""
        super().__init__(max_workers=max_workers)

    def _ensure_executor(self) -> None:
        """Lazily create the process executor (subclass seam)."""
        if self._executor is None:
            self._executor = concurrent.futures.ProcessPoolExecutor(max_workers=self.max_workers)

    def _submit_node(self, node: GraphFuture) -> None:
        """Dispatch a node to a worker process (subclass seam).

        Dependencies resolve here, in the parent, before dispatch: a
        failed dependency settles the node with that exception — the
        same path thread mode takes inside ``GraphFuture._run``.
        """
        if self._shutdown:
            try:
                node.future.set_exception(concurrent.futures.CancelledError())
            except concurrent.futures.InvalidStateError:
                pass
            return
        self._ensure_executor()
        try:
            args, kwargs = node._resolve_arguments()
        except Exception as exc:
            node.future.set_exception(exc)  # dependency failure
            return
        try:
            pfuture = self._executor.submit(node.function, *args, **kwargs)
        except Exception as exc:
            node.future.set_exception(ProcessDispatchError(f"{type(exc).__name__}: {exc}"))
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
                if isinstance(outcome, NodeOutcome):
                    # Visible to done-callbacks before the settle completes.
                    node._process_records = outcome.records
                    node._process_attempted = outcome.attempted
                    if outcome.error is None:
                        node.future.set_result(outcome.value)
                    else:
                        node.future.set_exception(outcome.error)
                else:
                    node.future.set_result(outcome)
            except concurrent.futures.InvalidStateError:
                pass

        pfuture.add_done_callback(_settle)
