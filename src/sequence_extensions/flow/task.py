"""``@task`` — retry, backoff, and timeout policy around a plain function.

A decorated task is still the function:

* **called directly** it runs inline in the caller's thread (sequential);
* **``.submit(...)``** schedules it on the current run's pool
  (concurrent) and returns a :class:`~sequence_extensions.graph.GraphFuture`.

Futures may be passed as submit arguments — they become dependency
edges, resolved to their results before the task body runs, so
``[f.submit(x) for x in items]`` followed by ``g.submit(f)`` builds a
general DAG (diamonds included), something the old series-parallel
workflow tree could not express.

Semantics (all per task, set as decorator keywords):

* ``retries`` — additional attempts after a failed one
  (``retries=2`` means up to 3 attempts).  Every attempt, successful or
  not, is one record in the run log.
* ``retry_delay_seconds`` — backoff sleep between attempts.  A retrying
  task holds its pool worker through the sleep.
* ``timeout`` — wall budget in seconds for ONE attempt, enforced by
  running the attempt in its own thread and joining with the budget.
  Python threads cannot be preempted: a timed-out attempt thread is
  abandoned as a daemon and its eventual result is discarded, but the
  task fails (and retries) promptly.  Raises
  :class:`TaskTimeoutError` (a ``TimeoutError`` naming the task) once
  attempts are exhausted.

A task body raising a non-``Exception`` ``BaseException`` (``SystemExit``,
``KeyboardInterrupt``) is recorded and re-raised wrapped in
``RuntimeError`` — the node must settle, and ``GraphFuture`` only carries
``Exception``s.
"""

from __future__ import annotations

import concurrent.futures
import functools
import threading
import time
from datetime import datetime, timezone

from sequence_extensions.flow._context import (
    RunContext,
    current_run,
    reset_current_run,
    set_current_run,
)
from sequence_extensions.flow.runlog import jsonable
from sequence_extensions.graph.graph_future import GraphFuture

#: ``pool.result(gf, timeout=0)`` binds the reachable graph without
#: waiting; concurrent binds from parallel workers must not interleave
#: (``GraphPool._visiting`` is pool-level DFS state).
_BIND_LOCK = threading.Lock()


class TaskTimeoutError(TimeoutError):
    """A task attempt exceeded its ``timeout`` budget.

    Attributes: ``task`` (task name), ``timeout`` (seconds), ``attempt``
    (the attempt that exceeded it).
    """

    def __init__(self, task, timeout, attempt):
        self.task = task
        self.timeout = timeout
        self.attempt = attempt
        super().__init__(f"task '{task}' exceeded its timeout of {timeout}s (attempt {attempt})")


class TaskFunction:
    """The object ``@task`` returns: still callable, plus ``.submit()``."""

    def __init__(self, fn, *, retries=0, retry_delay_seconds=0.0, timeout=None, name=None):
        if retries < 0:
            raise ValueError(f"retries must be >= 0, got {retries}")
        if retry_delay_seconds < 0:
            raise ValueError(f"retry_delay_seconds must be >= 0, got {retry_delay_seconds}")
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be > 0, got {timeout}")
        self.fn = fn
        self.retries = int(retries)
        self.retry_delay_seconds = float(retry_delay_seconds)
        self.timeout = None if timeout is None else float(timeout)
        self.name = name or getattr(fn, "__name__", "task")
        functools.update_wrapper(self, fn)

    def __repr__(self):
        return f"<TaskFunction {self.name} retries={self.retries} timeout={self.timeout}>"

    # ------------------------------------------------------------ #
    # Sequential (inline) execution
    # ------------------------------------------------------------ #
    def __call__(self, *args, **kwargs):
        """Run the task inline in the current thread (sequential)."""
        return self._execute(args, kwargs, current_run())

    # ------------------------------------------------------------ #
    # Concurrent execution
    # ------------------------------------------------------------ #
    def submit(self, *args, **kwargs) -> GraphFuture:
        """Schedule the task on the current run's pool.

        Futures among ``args``/``kwargs`` become dependency edges.
        Requires an active flow (call the task directly instead to run
        it sequentially).
        """
        ctx = current_run()
        if ctx is None or ctx.pool is None:
            raise RuntimeError(
                "task.submit() requires an active flow: decorate the calling "
                "function with @flow, or call the task directly to run it "
                "sequentially"
            )

        def _runner(*resolved_args, **resolved_kwargs):
            gf._flow_attempted = True
            token = set_current_run(ctx)
            try:
                return self._execute(resolved_args, resolved_kwargs, ctx)
            finally:
                reset_current_run(token)

        gf = GraphFuture(_runner, *args, **kwargs)
        gf.set_name(self.name)
        ctx.nodes.append(gf)

        def _on_settle(_future):
            # Fires in whichever thread settles the node.  A node that
            # failed WITHOUT ever executing (its dependency failed, so
            # argument resolution raised before the body ran) gets one
            # skipped record — absence of a record would be an audit gap.
            if ctx.runlog is None or gf.cancelled():
                return
            try:
                exc = gf.exception()
            except concurrent.futures.CancelledError:
                return
            if exc is None or getattr(gf, "_flow_attempted", False):
                return
            ctx.runlog.write(
                {
                    "record": "task",
                    "run_id": ctx.run_id,
                    "task": self.name,
                    "attempt": 0,
                    "status": "skipped",
                    "reason": "dependency failed",
                    "error": {"type": type(exc).__qualname__, "message": str(exc)},
                }
            )

        gf.add_done_callback(_on_settle)

        # Bind the reachable graph — submitting every ready leaf — without
        # touching any result.  The public alternative, a zero-timeout
        # ``pool.result(gf, timeout=0)`` probe, RAISES the task's own
        # exception when the task settles faster than the probe (an
        # instantly-failing dependency does exactly that), so the direct
        # bind is the only correct call here.  Cycles raise ValueError
        # here, synchronously at submit time.
        with _BIND_LOCK:
            ctx.pool._bind_graph(gf)
        return gf

    # ------------------------------------------------------------ #
    # Attempt loop (retry / backoff / timeout), shared by both paths
    # ------------------------------------------------------------ #
    def _execute(self, args, kwargs, ctx: RunContext | None):
        """Run all attempts; log each; return the result or raise the last error."""
        max_attempts = self.retries + 1
        for attempt in range(1, max_attempts + 1):
            started_clock = time.perf_counter()
            started_at = _utcnow()
            status, value = self._run_attempt(args, kwargs, ctx)
            duration_ms = int((time.perf_counter() - started_clock) * 1000)

            if status == "timeout":
                error: Exception = TaskTimeoutError(self.name, self.timeout, attempt)
            elif isinstance(value, BaseException) and not isinstance(value, Exception):
                # BaseException cannot settle a GraphFuture (it catches
                # Exception only) — wrap it so the node always settles.
                error = RuntimeError(f"{type(value).__qualname__}: {value}")
            else:
                error = value

            if ctx is not None and ctx.runlog is not None:
                self._log_attempt(
                    ctx, attempt, status, value, error, args, kwargs, started_at, duration_ms
                )

            if status == "ok":
                return value
            if attempt < max_attempts:
                if self.retry_delay_seconds > 0:
                    time.sleep(self.retry_delay_seconds)
                continue
            raise error

    def _run_attempt(self, args, kwargs, ctx: RunContext | None):
        """Run ONE attempt.

        Returns ``("ok", result)`` / ``("error", exception)`` /
        ``("timeout", None)``.  Without a timeout the body runs in the
        current thread; with one, it runs in its own thread joined with
        the budget (see the module docstring for the daemon caveat).
        """
        if self.timeout is None:
            try:
                return "ok", self.fn(*args, **kwargs)
            except BaseException as e:
                return "error", e

        box = {}

        def _target():
            token = set_current_run(ctx)
            try:
                box["result"] = self.fn(*args, **kwargs)
            except BaseException as e:
                box["error"] = e
            finally:
                reset_current_run(token)

        thread = threading.Thread(target=_target, name=f"{self.name}-attempt", daemon=True)
        thread.start()
        thread.join(self.timeout)
        if thread.is_alive():
            return "timeout", None
        if "error" in box:
            return "error", box["error"]
        return "ok", box.get("result")

    def _log_attempt(
        self, ctx, attempt, status, value, error, args, kwargs, started_at, duration_ms
    ) -> None:
        summary = ctx.runlog.summary
        record = {
            "record": "task",
            "run_id": ctx.run_id,
            "task": self.name,
            "attempt": attempt,
            "status": status,
            "args": [jsonable(a, summary=summary) for a in args],
            "kwargs": {k: jsonable(v, summary=summary) for k, v in kwargs.items()},
            "start": started_at,
            "end": _utcnow(),
            "duration_ms": duration_ms,
            "worker": threading.current_thread().name,
        }
        if status == "ok":
            record["result"] = jsonable(value, summary=summary)
        else:
            record["error"] = {"type": type(error).__qualname__, "message": str(error)}
        ctx.runlog.write(record)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def task(fn=None, *, retries=0, retry_delay_seconds=0.0, timeout=None, name=None):
    """Decorate a function as a task: retry, backoff, and timeout policy.

    Usable bare (``@task``), with keywords (``@task(retries=2)``), or
    both forms empty (``@task()``).
    """
    if fn is None:
        return lambda f: TaskFunction(
            f,
            retries=retries,
            retry_delay_seconds=retry_delay_seconds,
            timeout=timeout,
            name=name,
        )
    return TaskFunction(
        fn,
        retries=retries,
        retry_delay_seconds=retry_delay_seconds,
        timeout=timeout,
        name=name,
    )
