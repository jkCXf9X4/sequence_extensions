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

Semantics (all per task, set as decorator keywords or, when left
unset, by the active configuration —
:mod:`sequence_extensions.config`):

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

On a :class:`~sequence_extensions.flow.ProcessGraphPool` the same policy
runs in a worker process: the task and its arguments must be picklable,
and the run-log records are buffered by the worker and replayed by the
parent when the future settles (see :mod:`sequence_extensions.flow.process_pool`).
"""

from __future__ import annotations

import functools
import pickle
import re
import sys
import threading
import time
from datetime import UTC, datetime

from sequence_extensions.config import (
    UNSET,
    active_config,
    configure,
    reset_config,
    validate_task_policy,
)
from sequence_extensions.flow._context import (
    RunContext,
    current_run,
    reset_current_run,
    set_current_run,
)
from sequence_extensions.flow.process_pool import (
    ProcessGraphPool,
    _process_task_runner,
)
from sequence_extensions.flow.runlog import jsonable
from sequence_extensions.graph.graph_future import GraphFuture

#: ``pool.bind(gf)`` submits every ready leaf; concurrent binds from
#: parallel workers must not interleave (``GraphPool._visiting`` is
#: pool-level DFS state).
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

    def __reduce__(self):
        """Pickle transport for process pools (default exception pickling
        would rebuild with the message string, not the constructor)."""
        return (type(self), (self.task, self.timeout, self.attempt))


class TaskFunction:
    """The object ``@task`` returns: still callable, plus ``.submit()``.

    Policy keywords left unset (the default) resolve per call — see
    :mod:`sequence_extensions.config` — so ``configure()`` reaches
    module-level tasks after import.
    """

    def __init__(self, fn, *, retries=UNSET, retry_delay_seconds=UNSET, timeout=UNSET, name=None):
        # Each given value is checked alone; an unset one defers to the
        # active configuration at call time (validate_task_policy's
        # pass-through arguments 0/None never fire their own checks).
        if retries is not UNSET:
            validate_task_policy(retries, 0.0, None)
        if retry_delay_seconds is not UNSET:
            validate_task_policy(0, retry_delay_seconds, None)
        if timeout is not UNSET:
            validate_task_policy(0, 0.0, timeout)
        self.fn = fn
        self.retries = retries
        self.retry_delay_seconds = retry_delay_seconds
        self.timeout = timeout
        self.name = name or getattr(fn, "__name__", "task")
        functools.update_wrapper(self, fn)
        # Process-pool support: the decorator replaces the module-level
        # name with this TaskFunction, so pickling the raw function by
        # reference would fail pickle's identity check.  Rebind the raw
        # function under a private alias in its own module; __reduce__
        # ships (alias, policy) instead of the function object.
        module = sys.modules.get(getattr(fn, "__module__", None))
        if module is not None:
            alias = "__seqext_task_fn_" + re.sub(
                r"\W+", "_", getattr(fn, "__qualname__", "") or self.name
            )
            setattr(module, alias, fn)
            self._pickle_alias = (fn.__module__, alias)

    def _effective_policy(self):
        """Resolve the policy this call runs under: explicit keyword >
        active config > built-in default (config values are validated at
        load; decorator values at decoration)."""
        cfg = active_config().task
        retries = self.retries if self.retries is not UNSET else cfg.retries
        delay = (
            self.retry_delay_seconds
            if self.retry_delay_seconds is not UNSET
            else cfg.retry_delay_seconds
        )
        timeout = self.timeout if self.timeout is not UNSET else cfg.timeout
        return int(retries), float(delay), None if timeout is None else float(timeout)

    def __reduce__(self):
        """Pickle transport for process pools (see __init__).

        Ships the policy exactly as stored — ``UNSET`` pickles as the
        sentinel and resolves in the receiving process.  The engine's own
        process path never relies on that: ``submit()`` resolves the
        policy in the submitting thread and ships a concrete-valued task
        (see :meth:`submit`).
        """
        alias = getattr(self, "_pickle_alias", None)
        if alias is None:
            raise pickle.PicklingError(
                f"task '{self.name}' is not picklable: its function has no importable module"
            )
        return (
            _rebuild_task_function,
            (alias, self.retries, self.retry_delay_seconds, self.timeout, self.name),
        )

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

        if isinstance(ctx.pool, ProcessGraphPool):
            # Process mode: the node's function must be picklable, so the
            # runner is this module-level function carrying the task and a
            # plain-dict run header; the worker buffers run-log records and
            # the flow replays them before run_end (flow.py).
            #
            # The policy is resolved HERE, in the submitting thread where
            # the active configuration is visible, and shipped concrete:
            # executor dispatch pickles from its manager thread and worker
            # processes may not inherit the parent's context, so a task
            # still carrying UNSET must never cross the process boundary.
            retries, delay, timeout = self._effective_policy()
            resolved = TaskFunction(
                self.fn,
                retries=retries,
                retry_delay_seconds=delay,
                timeout=timeout,
                name=self.name,
            )
            run_info = {
                "run_id": ctx.run_id,
                "flow_name": ctx.flow_name,
                "summary": bool(ctx.runlog is not None and ctx.runlog.summary),
            }
            gf = GraphFuture(_process_task_runner, resolved, run_info, *args, **kwargs)
        else:
            # Snapshot the configuration here, in the submitting thread:
            # a new worker thread starts with an empty context and would
            # otherwise fall back to the built-in defaults.
            cfg = active_config()

            def _runner(*resolved_args, **resolved_kwargs):
                gf._flow_attempted = True
                run_token = set_current_run(ctx)
                cfg_token = configure(cfg)
                try:
                    return self._execute(resolved_args, resolved_kwargs, ctx)
                finally:
                    reset_config(cfg_token)
                    reset_current_run(run_token)

            gf = GraphFuture(_runner, *args, **kwargs)
        gf.set_name(self.name)
        ctx.nodes.append(gf)

        # Settle-time records (replayed process records, skip records)
        # are written by the flow thread in flow.py, never from a
        # done-callback: set_result wakes drain waiters before callbacks
        # finish, so a callback-side write can race run_end closing the
        # log.

        # Bind the reachable graph — submitting every ready leaf — without
        # touching any result (a pure bind; cycles raise ValueError here,
        # synchronously at submit time).
        with _BIND_LOCK:
            ctx.pool.bind(gf)
        return gf

    # ------------------------------------------------------------ #
    # Attempt loop (retry / backoff / timeout), shared by both paths
    # ------------------------------------------------------------ #
    def _execute(self, args, kwargs, ctx: RunContext | None):
        """Run all attempts; log each; return the result or raise the last error."""
        retries, delay, timeout = self._effective_policy()
        cfg = active_config()
        max_attempts = retries + 1
        for attempt in range(1, max_attempts + 1):
            started_clock = time.perf_counter()
            started_at = _utcnow()
            status, value = self._run_attempt(args, kwargs, ctx, cfg, timeout)
            duration_ms = int((time.perf_counter() - started_clock) * 1000)

            if status == "timeout":
                error: Exception = TaskTimeoutError(self.name, timeout, attempt)
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
                if delay > 0:
                    time.sleep(delay)
                continue
            raise error

    def _run_attempt(self, args, kwargs, ctx: RunContext | None, cfg, timeout):
        """Run ONE attempt.

        Returns ``("ok", result)`` / ``("error", exception)`` /
        ``("timeout", None)``.  Without a timeout the body runs in the
        current thread; with one, it runs in its own thread joined with
        the budget (see the module docstring for the daemon caveat).
        """
        if timeout is None:
            try:
                return "ok", self.fn(*args, **kwargs)
            except BaseException as e:
                return "error", e

        box = {}

        def _target():
            # Restore run context *and* configuration in the fresh
            # thread (same rationale as a pool worker): a body that
            # reads either — nested task calls, ``active_config()`` —
            # must see the submitting context, not empty-thread defaults.
            run_token = set_current_run(ctx)
            cfg_token = configure(cfg)
            try:
                box["result"] = self.fn(*args, **kwargs)
            except BaseException as e:
                box["error"] = e
            finally:
                reset_config(cfg_token)
                reset_current_run(run_token)

        thread = threading.Thread(target=_target, name=f"{self.name}-attempt", daemon=True)
        thread.start()
        thread.join(timeout)
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
    return datetime.now(UTC).isoformat()


def _rebuild_task_function(alias, retries, retry_delay_seconds, timeout, name):
    """Unpickle a TaskFunction from its module alias (see __reduce__)."""
    module = sys.modules.get(alias[0])
    fn = getattr(module, alias[1], None) if module is not None else None
    if fn is None:
        # E.g. a spawn-started worker: the alias only exists where the
        # decoration ran (module level), not in a fresh interpreter.
        raise pickle.UnpicklingError(f"task function {alias!r} is not importable")
    return TaskFunction(
        fn,
        retries=retries,
        retry_delay_seconds=retry_delay_seconds,
        timeout=timeout,
        name=name,
    )


def task(
    fn=None,
    *,
    retries=UNSET,
    retry_delay_seconds=UNSET,
    timeout=UNSET,
    name=None,
):
    """Decorate a function as a task: retry, backoff, and timeout policy.

    Usable bare (``@task``), with keywords (``@task(retries=2)``), or
    both forms empty (``@task()``).  Keywords left unset resolve per call
    from the active configuration (see :mod:`sequence_extensions.config`);
    an explicit keyword always wins.
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
