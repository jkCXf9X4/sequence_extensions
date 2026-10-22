"""``@node`` — the one composable unit: policy plus ``.submit()``.

A decorated node is still the function:

* **called directly** it runs inline in the caller's thread.  Outside a node
  body it returns the body's value (waiting for a returned future if
  needed).  Inside a node body — on the driver or in a pool worker — it
  cannot wait: an unsettled call returns a future/outcome, and the caller
  should return it.
* **``.submit(...)``** schedules it on the run's pool (concurrent) and
  returns a :class:`FlowFuture`.

A node may return a concrete value or a future.  A returned future (from
``.submit()`` or :func:`gather`) is bound to the run's pool and its result
is forwarded by the graph layer; the worker is freed immediately.  The
node's attempt record, retry policy, and timeout are applied when that
future settles.  This is how nested composite nodes fan out without
blocking a pool worker and without opening a second run.

Semantics (per node, set as decorator keywords or, when left unset, by
``RunOptions.node_defaults`` of the active run):

* ``retries`` — additional attempts after a failed one (``retries=2``
  means up to 3 attempts).  Every attempt is one record in the run log.
* ``retry_delay_seconds`` — backoff sleep between attempts.  The delay is a
  timer, not a held worker.
* ``timeout`` — wall budget in seconds for ONE attempt.  The body runs in
  its own thread joined with the budget; if it returns a future, the
  remaining budget is a timer.  Python threads cannot be preempted: a
  timed-out attempt is abandoned, its late records (and those of its
  subtree) are dropped, and :class:`NodeTimeoutError` is raised once
  attempts are exhausted.

A node body raising a non-``Exception`` ``BaseException`` (``SystemExit``,
``KeyboardInterrupt``) is recorded and re-raised wrapped in ``RuntimeError``
— the graph node must settle; a non-``Exception`` is wrapped before it
reaches the future.

On a :class:`~sequence_extensions.flow.ProcessGraphPool` the same policy
runs in a worker process: the node and its arguments must be picklable,
and the run-log records are buffered by the worker and replayed by the
parent when the future settles.  A process worker cannot submit or return
a live future; process-mode fan-out is built in the parent process.
"""

from __future__ import annotations

import functools
import itertools
import pickle
import re
import sys
import threading

from sequence_extensions.flow._attempt import _AttemptRunner, _utcnow
from sequence_extensions.flow._context import (
    AttemptToken,
    RunContext,
    current_attempt_token,
    current_node_attempt,
    current_node_path,
    current_run,
    current_run_attempt_token,
    execution_scope,
    in_node_body,
    in_process_worker,
    in_worker,
)
from sequence_extensions.flow._futures import FlowFuture, FlowOutcome, NodeTimeoutError
from sequence_extensions.flow._gather import gather
from sequence_extensions.flow._options import UNSET, validate_node_policy
from sequence_extensions.flow.process_pool import _process_node_runner
from sequence_extensions.flow.runlog import jsonable

__all__ = [
    "FlowFuture",
    "FlowOutcome",
    "NodeFunction",
    "NodeTimeoutError",
    "gather",
    "node",
]

#: ``pool.bind(gf)`` submits every ready leaf; concurrent binds from
#: parallel workers must not interleave (``GraphPool._visiting`` is
#: pool-level DFS state).
_BIND_LOCK = threading.Lock()

#: Process-pool pickle aliases must be unique per NodeFunction.  A qualname
#: alone collides for lambdas and factory/closure nodes, which then silently
#: execute the wrong raw function in a worker.
_ALIAS_LOCK = threading.Lock()
_ALIAS_COUNTER = itertools.count()


class NodeFunction:
    """The object ``@node`` returns: still callable, plus ``.submit()``.

    Policy keywords left unset resolve per call from the active run's
    ``node_defaults`` (or the built-in default outside a run).
    """

    def __init__(
        self,
        fn,
        *,
        retries=UNSET,
        retry_delay_seconds=UNSET,
        timeout=UNSET,
        name=None,
        _alias=None,
    ):
        if not callable(fn):
            raise TypeError(f"@node expects a callable, got {fn!r}")
        if name is not None and (not isinstance(name, str) or not name):
            raise ValueError(f"name must be a non-empty string, got {name!r}")
        validate_node_policy(retries, retry_delay_seconds, timeout)
        self.fn = fn
        self.retries = retries
        self.retry_delay_seconds = retry_delay_seconds
        self.timeout = timeout
        self.name = name or getattr(fn, "__name__", "node")
        # Copy the function's metadata, but not arbitrary attributes: a
        # decorated function may carry its own ``retries`` / ``timeout`` /
        # ``name`` attributes, and those must not override the node policy.
        functools.update_wrapper(self, fn, updated=())
        # Process-pool support: the decorator replaces the module-level
        # name with this NodeFunction, so pickling the raw function by
        # reference would fail pickle's identity check.  Rebind the raw
        # function under a unique private alias in its own module; __reduce__
        # ships (alias, policy) instead of the function object.  The counter
        # keeps lambdas and factory closures distinct: a qualname alone
        # collides and would execute the wrong function in a worker.
        if _alias is not None:
            self._pickle_alias = _alias
        else:
            module = sys.modules.get(getattr(fn, "__module__", None))
            if module is not None:
                with _ALIAS_LOCK:
                    tag = next(_ALIAS_COUNTER)
                stem = re.sub(r"\W+", "_", getattr(fn, "__qualname__", "") or self.name)
                alias = f"__seqext_node_fn_{stem}_{tag}"
                setattr(module, alias, fn)
                self._pickle_alias = (fn.__module__, alias)
        self.__node__ = self.name

    # ------------------------------------------------------------ #
    # Policy
    # ------------------------------------------------------------ #
    def _effective_policy(self):
        """Resolve this attempt's policy: explicit keyword > run defaults > built-in."""
        ctx = current_run()
        defaults = getattr(ctx.options, "node_defaults", None) if ctx is not None else None
        if defaults is UNSET:
            defaults = None
        retries = self.retries if self.retries is not UNSET else getattr(defaults, "retries", 0)
        delay = (
            self.retry_delay_seconds
            if self.retry_delay_seconds is not UNSET
            else getattr(defaults, "retry_delay_seconds", 0.0)
        )
        timeout = self.timeout if self.timeout is not UNSET else getattr(defaults, "timeout", None)
        return int(retries), float(delay), None if timeout is None else float(timeout)

    def __reduce__(self):
        """Pickle transport for process pools (see __init__)."""
        alias = getattr(self, "_pickle_alias", None)
        if alias is None:
            raise pickle.PicklingError(
                f"node '{self.name}' is not picklable: its function has no importable module"
            )
        return (
            _rebuild_node_function,
            (alias, self.retries, self.retry_delay_seconds, self.timeout, self.name),
        )

    def __repr__(self):
        return f"<NodeFunction {self.name} retries={self.retries} timeout={self.timeout}>"

    # ------------------------------------------------------------ #
    # Sequential (inline) execution
    # ------------------------------------------------------------ #
    def __call__(self, *args, **kwargs):
        """Run the node inline in the current thread.

        Outside a node body this waits for a returned future and gives back
        the value.  Inside a node body (driver or pool worker) a body that
        has not settled returns its future instead; return it to let the
        graph continue without blocking.
        """
        outcome = self._execute_deferred(
            args,
            kwargs,
            current_run(),
            parent_token=current_attempt_token(),
            run_attempt_token=current_run_attempt_token(),
        )
        if (in_node_body() or in_worker()) and not outcome.done():
            return outcome
        return outcome.result()

    # ------------------------------------------------------------ #
    # Concurrent execution
    # ------------------------------------------------------------ #
    def submit(self, *args, **kwargs) -> FlowFuture:
        """Schedule the node on the current run's pool.

        Futures among ``args``/``kwargs`` become dependency edges.  A
        worker may submit: the call returns a future and does not wait, so
        the pool cannot deadlock.  Blocking on an incomplete future inside a
        node body raises with guidance.
        """
        ctx = current_run()
        if in_process_worker():
            raise RuntimeError(
                "node.submit() inside a process worker is not supported: build the "
                "process-mode graph in the parent process"
            )
        if ctx is None or ctx.pool is None:
            raise RuntimeError(
                "node.submit() requires an active run: call execute_flow(...) around "
                "the node, or call the node directly to run it sequentially"
            )
        token = current_attempt_token()
        if token is not None and token.abandoned_in_chain():
            raise RuntimeError("node.submit() on an abandoned attempt")
        if ctx.cancelled.is_set():
            raise RuntimeError("node.submit() on a cancelled run")

        parent_token = token
        run_attempt_token = current_run_attempt_token()
        if ctx.pool.process_workers:
            # Process mode: the node's function must be picklable, so the
            # runner is this module-level function carrying the node and a
            # plain-dict run header; the worker buffers run-log records and
            # the run replays them before run_end.
            retries, delay, timeout = self._effective_policy()
            resolved = NodeFunction(
                self.fn,
                retries=retries,
                retry_delay_seconds=delay,
                timeout=timeout,
                name=self.name,
                _alias=getattr(self, "_pickle_alias", None),
            )
            run_info = {
                "run_id": ctx.run_id,
                "node_name": ctx.node_name,
                "summary": bool(ctx.runlog is not None and ctx.runlog.summary),
                "node_defaults": ctx.options.node_defaults,
                "parent_path": list(current_node_path()),
                "parent_attempt": current_node_attempt(),
            }
            gf = FlowFuture(_process_node_runner, resolved, run_info, *args, **kwargs)
        else:
            # Capture the position here, in the submitting thread: a new
            # worker thread starts empty and must restore it around the body.
            parent_path = current_node_path()
            parent_attempt = current_node_attempt()

            def _runner(*resolved_args, **resolved_kwargs):
                gf.attempted = True
                with execution_scope(
                    ctx=ctx,
                    path=parent_path,
                    attempt=parent_attempt,
                    worker=True,
                    process_worker=False,
                ):
                    return self._execute_deferred(
                        resolved_args,
                        resolved_kwargs,
                        ctx,
                        parent_token=parent_token,
                        run_attempt_token=run_attempt_token,
                    )

            gf = FlowFuture(_runner, *args, **kwargs)
        gf.set_name(self.name)
        gf.path = current_node_path() + (self.name,)
        gf.parent_attempt = current_node_attempt()
        ctx.nodes.append(gf)

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
        """Synchronous helper for process workers: run and return the value."""
        outcome = self._execute_deferred(
            args,
            kwargs,
            ctx,
            parent_token=current_attempt_token(),
            run_attempt_token=current_run_attempt_token(),
        )
        return outcome.result()

    def _execute_deferred(
        self,
        args,
        kwargs,
        ctx: RunContext | None,
        *,
        parent_token: AttemptToken | None,
        run_attempt_token: AttemptToken | None,
    ) -> FlowOutcome:
        """Run the attempt loop; return a future settled at the final outcome."""
        retries, delay, timeout = self._effective_policy()
        return _AttemptRunner(
            self,
            args,
            kwargs,
            ctx,
            parent_token=parent_token,
            run_attempt_token=run_attempt_token,
            retries=retries,
            delay=delay,
            timeout=timeout,
        ).run()

    def _log_attempt(
        self,
        ctx,
        path,
        parent_attempt,
        attempt,
        status,
        args,
        kwargs,
        value,
        error,
        token,
        run_attempt_token,
        started_at,
        duration_ms,
        *,
        allow_abandoned: bool = False,
        worker: str,
    ) -> None:
        if token.parent is not None and token.parent.abandoned_in_chain():
            return
        if token.abandoned.is_set() and not allow_abandoned:
            return
        if run_attempt_token is not None and run_attempt_token.abandoned.is_set():
            return
        summary = ctx.runlog.summary
        record = {
            "record": "node",
            "run_id": ctx.run_id,
            "node": self.name,
            "path": list(path),
            "attempt": attempt,
            "parent_attempt": parent_attempt,
            "status": status,
            "args": [jsonable(a, summary=summary) for a in args],
            "kwargs": {k: jsonable(v, summary=summary) for k, v in kwargs.items()},
            "start": started_at,
            "end": _utcnow(),
            "duration_ms": duration_ms,
            "worker": worker,
        }
        if status == "ok":
            record["result"] = jsonable(value, summary=summary)
        else:
            record["error"] = {"type": type(error).__qualname__, "message": str(error)}
        ctx.runlog.write(record)


def _rebuild_node_function(alias, retries, retry_delay_seconds, timeout, name):
    """Unpickle a NodeFunction from its module alias (see __reduce__)."""
    module = sys.modules.get(alias[0])
    fn = getattr(module, alias[1], None) if module is not None else None
    if fn is None:
        # E.g. a spawn-started worker: the alias only exists where the
        # decoration ran (module level), not in a fresh interpreter.
        raise pickle.UnpicklingError(f"node function {alias!r} is not importable")
    return NodeFunction(
        fn,
        retries=retries,
        retry_delay_seconds=retry_delay_seconds,
        timeout=timeout,
        name=name,
        _alias=alias,
    )


def node(
    fn=None,
    *,
    retries=UNSET,
    retry_delay_seconds=UNSET,
    timeout=UNSET,
    name=None,
):
    """Decorate a function as a node: retry, backoff, and timeout policy.

    Usable bare (``@node``), with keywords (``@node(retries=2)``), or both
    forms empty (``@node()``).  Keywords left unset resolve per call from
    the active run's ``node_defaults``; an explicit keyword always wins.
    """
    if fn is None:
        return lambda f: NodeFunction(
            f,
            retries=retries,
            retry_delay_seconds=retry_delay_seconds,
            timeout=timeout,
            name=name,
        )
    return NodeFunction(
        fn,
        retries=retries,
        retry_delay_seconds=retry_delay_seconds,
        timeout=timeout,
        name=name,
    )
