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
— the graph node must settle, and ``GraphFuture`` only carries
``Exception``s.

On a :class:`~sequence_extensions.flow.ProcessGraphPool` the same policy
runs in a worker process: the node and its arguments must be picklable,
and the run-log records are buffered by the worker and replayed by the
parent when the future settles.  A process worker cannot submit or return
a live future; process-mode fan-out is built in the parent process.
"""

from __future__ import annotations

import concurrent.futures
import functools
import itertools
import pickle
import re
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

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
from sequence_extensions.flow._options import UNSET, validate_node_policy
from sequence_extensions.flow.process_pool import _process_node_runner
from sequence_extensions.flow.runlog import jsonable
from sequence_extensions.graph.graph_future import GraphFuture

#: ``pool.bind(gf)`` submits every ready leaf; concurrent binds from
#: parallel workers must not interleave (``GraphPool._visiting`` is
#: pool-level DFS state).
_BIND_LOCK = threading.Lock()

#: Process-pool pickle aliases must be unique per NodeFunction.  A qualname
#: alone collides for lambdas and factory/closure nodes, which then silently
#: execute the wrong raw function in a worker.
_ALIAS_LOCK = threading.Lock()
_ALIAS_COUNTER = itertools.count()

_BLOCKED_IN_BODY = (
    "blocked on an incomplete future inside a node body; return the future "
    "instead (or submit a dependent node)"
)

#: Recursion guard for container inspection and ``gather`` planning.
_MAX_CONTAINER_DEPTH = 200


def _is_future(value) -> bool:
    return isinstance(value, (GraphFuture, concurrent.futures.Future))


def _contains_future(value, _seen=None, _depth: int = 0) -> bool:
    """True if a returned container still holds futures.

    A node should return one future (see :func:`gather`), not a list or
    dict of futures: the graph layer only awaits a single returned future.
    Self-referential containers and depth beyond ``_MAX_CONTAINER_DEPTH`` are
    treated as opaque (no future) instead of exhausting the stack; the log
    records them with a cycle/depth marker.
    """
    if _is_future(value):
        return True
    if _depth >= _MAX_CONTAINER_DEPTH:
        return False
    if isinstance(value, Mapping):
        if _seen is None:
            _seen = set()
        marker = id(value)
        if marker in _seen:
            return False
        _seen.add(marker)
        try:
            return any(_contains_future(v, _seen, _depth + 1) for v in value.values())
        finally:
            _seen.discard(marker)
    if isinstance(value, (list, tuple, set, frozenset)):
        if _seen is None:
            _seen = set()
        marker = id(value)
        if marker in _seen:
            return False
        _seen.add(marker)
        try:
            return any(_contains_future(v, _seen, _depth + 1) for v in value)
        finally:
            _seen.discard(marker)
    return False


class NodeTimeoutError(TimeoutError):
    """A node attempt exceeded its ``timeout`` budget.

    Attributes: ``node`` (node name), ``timeout`` (seconds), ``attempt``
    (the attempt that exceeded it).
    """

    def __init__(self, node, timeout, attempt):
        self.node = node
        self.timeout = timeout
        self.attempt = attempt
        super().__init__(f"node '{node}' exceeded its timeout of {timeout}s (attempt {attempt})")

    def __reduce__(self):
        """Pickle transport for process pools."""
        return (type(self), (self.node, self.timeout, self.attempt))


class FlowOutcome(concurrent.futures.Future):
    """A deferred node outcome; blocking on it inside a node body is rejected."""

    def result(self, timeout=None):
        if (in_node_body() or in_worker()) and not self.done():
            raise RuntimeError(_BLOCKED_IN_BODY)
        return super().result(timeout=timeout)


class FlowFuture(GraphFuture):
    """A submitted node's graph future; blocking on it inside a node body is rejected."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.path: tuple = ()
        self.parent_attempt = None
        self.attempted = False
        self.process_records: list[dict] | None = None

    def result(self, timeout=None):
        if (in_node_body() or in_worker()) and not self.future.done():
            raise RuntimeError(_BLOCKED_IN_BODY)
        return super().result(timeout=timeout)


class _Slot:
    """Template marker: fill me from ``values[index]``."""

    __slots__ = ("index",)

    def __init__(self, index):
        self.index = index

    def __reduce__(self):
        """Pickle transport for process pools (the template is dispatched)."""
        return (_make_slot, (self.index,))


def _make_slot(index):
    return _Slot(index)


def _enter_gather(value, _seen, _depth):
    """Cycle/depth guard shared by the ``_plan`` container branches."""
    if _depth >= _MAX_CONTAINER_DEPTH:
        raise ValueError("gather() container is deeper than the supported limit")
    if _seen is None:
        _seen = set()
    marker = id(value)
    if marker in _seen:
        raise ValueError("gather() cannot resolve a cyclic container")
    _seen.add(marker)
    return _seen, marker


def _plan(value, items, _seen=None, _depth: int = 0):
    """Template for ``value``: futures become slots, containers keep shape.

    Futures are collected into ``items`` in traversal order, which is the
    order of the collect node's dependencies (and therefore of ``values``
    in :func:`_fill`).  Mappings other than ``dict`` are resolved into a
    plain dict.  A cyclic or over-deep container raises ``ValueError``
    instead of recursing without bound.
    """
    if _is_future(value):
        items.append(value)
        return _Slot(len(items) - 1)
    if isinstance(value, Mapping):
        _seen, marker = _enter_gather(value, _seen, _depth)
        try:
            return {
                key: _plan(item, items, _seen, _depth + 1)
                for key, item in value.items()
            }
        finally:
            _seen.discard(marker)
    if isinstance(value, list):
        _seen, marker = _enter_gather(value, _seen, _depth)
        try:
            return [_plan(item, items, _seen, _depth + 1) for item in value]
        finally:
            _seen.discard(marker)
    if isinstance(value, tuple):
        _seen, marker = _enter_gather(value, _seen, _depth)
        try:
            planned = [_plan(item, items, _seen, _depth + 1) for item in value]
        finally:
            _seen.discard(marker)
        if hasattr(value, "_fields"):
            return type(value)(*planned)
        try:
            return type(value)(planned)
        except Exception:
            return tuple(planned)
    if isinstance(value, (set, frozenset)):
        _seen, marker = _enter_gather(value, _seen, _depth)
        try:
            return type(value)(_plan(item, items, _seen, _depth + 1) for item in value)
        finally:
            _seen.discard(marker)
    return value


def _fill(template, values):
    """Inverse of :func:`_plan`: rebuild the shape, slots become results."""
    if isinstance(template, _Slot):
        return values[template.index]
    if isinstance(template, Mapping):
        return {key: _fill(item, values) for key, item in template.items()}
    if isinstance(template, list):
        return [_fill(item, values) for item in template]
    if isinstance(template, tuple):
        filled = [_fill(item, values) for item in template]
        if hasattr(template, "_fields"):
            return type(template)(*filled)
        try:
            return type(template)(filled)
        except Exception:
            return tuple(filled)
    if isinstance(template, (set, frozenset)):
        return type(template)(_fill(item, values) for item in template)
    return template


def _collect_structural(template, *values):
    return _fill(template, values)


def gather(value):
    """Return a future for ``value`` with its futures replaced by results.

    Containers keep their shape, at any depth: ``{"a": submit(1)}``
    resolves to ``{"a": 1}``, a nested list stays a list, and a tuple or
    set stays a tuple or set.  Mappings other than ``dict`` resolve to a
    plain dict; namedtuples and orderable tuple subclasses keep their type.
    Only values are resolved (dict keys are kept as-is).  A bare future
    resolves to a one-element list, and any other iterable is materialized
    into a list.  The result is a :class:`FlowFuture`, so it can be returned
    from a node or passed as a dependency to :meth:`NodeFunction.submit`.

    ``gather`` needs an active run (its future is evaluated by the run's
    pool); outside one it raises ``RuntimeError`` instead of hanging.
    """
    if current_run() is None:
        raise RuntimeError(
            "gather() requires an active run: call execute_flow(...) around the node"
        )
    if _is_future(value):
        future = FlowFuture(_collect_structural, [_Slot(0)], value)
    else:
        if not isinstance(value, (list, tuple, Mapping, set, frozenset)):
            value = list(value)
        items = []
        future = FlowFuture(_collect_structural, _plan(value, items), *items)
    future.set_name("gather")
    return future


@dataclass
class _AttemptState:
    attempt: int = 0
    finished: int = 0
    done: bool = False
    timer: threading.Timer | None = None
    inner: object = None


class _AttemptRunner:
    """One node's attempt loop: retry, timeout, logging, and settlement."""

    def __init__(
        self,
        node,
        args,
        kwargs,
        ctx: RunContext | None,
        *,
        parent_token: AttemptToken | None,
        run_attempt_token: AttemptToken | None,
        retries: int,
        delay: float,
        timeout: float | None,
    ):
        self.node = node
        self.args = args
        self.kwargs = kwargs
        self.ctx = ctx
        self.parent_token = parent_token
        self.run_attempt_token = run_attempt_token
        self.delay = delay
        self.timeout = timeout
        self.max_attempts = retries + 1
        self.path = tuple(current_node_path()) + (node.name,)
        self.parent_attempt = current_node_attempt()
        self.worker_name = threading.current_thread().name
        self.base_worker = in_worker()
        self.base_process = in_process_worker()
        self.lock = threading.Lock()
        self.state = _AttemptState()
        self.outcome = FlowOutcome()
        # Per-thread "inside the attempt loop" marker.  A done-callback that
        # runs synchronously (the returned future was already settled) must
        # hand its retry back to the loop instead of nesting another attempt.
        self._local = threading.local()
        self._pending_retry = False
        if ctx is not None:
            ctx.outcomes.append(self.outcome)

    def run(self) -> FlowOutcome:
        self._start(1)
        return self.outcome

    def _settle_unexpected(self, exc) -> None:
        """Settle with an engine-side exception instead of leaving a drain hang."""
        if not isinstance(exc, Exception):
            exc = RuntimeError(f"{type(exc).__qualname__}: {exc}")
        with self.lock:
            if self.state.done or self.outcome.done():
                return
            self.state.done = True
        try:
            self.outcome.set_exception(exc)
        except concurrent.futures.InvalidStateError:
            pass

    def _finish_safely(self, attempt, status, value, token, started_at, started_clock):
        """``_finish`` from a callback/timer: never let an engine error hang."""
        try:
            return self._finish(attempt, status, value, token, started_at, started_clock)
        except BaseException as exc:
            self._settle_unexpected(exc)
            return False

    def _finish(
        self,
        attempt,
        status,
        value,
        token,
        started_at,
        started_clock,
        *,
        defer_retry: bool = False,
    ) -> bool:
        """Settle one attempt; return True when the caller should retry now.

        ``defer_retry=True`` is the synchronous path from ``_run_attempt``:
        the attempt loop continues iteratively.  Callback/timer paths use the
        default and start the next attempt on their own stack (or schedule a
        backoff timer).  A failed log write is an engine error: it settles the
        attempt and is never retried, so a broken audit log cannot hang the
        drain.
        """
        with self.lock:
            if (
                self.state.done
                or self.state.attempt != attempt
                or self.state.finished == attempt
            ):
                return False
            self.state.finished = attempt
            timer = self.state.timer
            self.state.timer = None
        if timer is not None:
            timer.cancel()
        duration_ms = int((time.perf_counter() - started_clock) * 1000)
        if status == "error" and isinstance(value, BaseException) and not isinstance(
            value, Exception
        ):
            value = RuntimeError(f"{type(value).__qualname__}: {value}")
        error = None if status == "ok" else value
        if status == "timeout":
            error = NodeTimeoutError(self.node.name, self.timeout, attempt)
            token.abandoned.set()
            with self.lock:
                inner = self.state.inner
            if inner is not None:
                try:
                    if isinstance(inner, GraphFuture):
                        inner.future.cancel()
                    else:
                        inner.cancel()
                except Exception:
                    pass
        log_error = None
        if self.ctx is not None and self.ctx.runlog is not None:
            try:
                self.node._log_attempt(
                    self.ctx,
                    self.path,
                    self.parent_attempt,
                    attempt,
                    status,
                    self.args,
                    self.kwargs,
                    value,
                    error,
                    token,
                    self.run_attempt_token,
                    started_at,
                    duration_ms,
                    allow_abandoned=(status == "timeout"),
                    worker=self.worker_name,
                )
            except Exception as exc:  # audit write failed: fail the attempt
                log_error = exc
        if log_error is not None:
            status = "error"
            error = RuntimeError(f"run-log write failed: {log_error}")
            value = error

        def settle_result() -> None:
            with self.lock:
                self.state.done = True
            try:
                self.outcome.set_result(value)
            except concurrent.futures.InvalidStateError:
                pass

        def settle_error() -> None:
            with self.lock:
                self.state.done = True
            try:
                self.outcome.set_exception(error)
            except concurrent.futures.InvalidStateError:
                pass

        if status == "ok":
            settle_result()
            return False
        if self.ctx is not None and self.ctx.cancelled.is_set():
            settle_error()
            return False
        if self.parent_token is not None and self.parent_token.abandoned_in_chain():
            settle_error()
            return False
        if log_error is None and attempt < self.max_attempts:
            if self.delay > 0:
                timer = threading.Timer(self.delay, lambda: self._start(attempt + 1))
                timer.daemon = True
                timer.start()
                return False
            if defer_retry or getattr(self._local, "in_start", False):
                return True
            self._start(attempt + 1)
            return False
        settle_error()
        return False

    def _after_body(
        self, attempt, value, token, started_at, started_clock, elapsed, *, defer_retry=False
    ) -> bool:
        if self.base_process and _is_future(value):
            return self._finish(
                attempt,
                "error",
                RuntimeError("a process worker cannot return a live future"),
                token,
                started_at,
                started_clock,
                defer_retry=defer_retry,
            )
        if not _is_future(value) and _contains_future(value):
            return self._finish(
                attempt,
                "error",
                RuntimeError(
                    "a node returned a container holding futures; return one future "
                    "(wrap the collection with gather(...))"
                ),
                token,
                started_at,
                started_clock,
                defer_retry=defer_retry,
            )
        if _is_future(value):
            if self.ctx is None or self.ctx.pool is None:
                return self._finish(
                    attempt,
                    "error",
                    RuntimeError("a node returning a future requires an active run"),
                    token,
                    started_at,
                    started_clock,
                    defer_retry=defer_retry,
                )
            if isinstance(value, GraphFuture):
                try:
                    self.ctx.pool.bind(value)
                except Exception as exc:  # dependency cycle, dispatch error
                    return self._finish(
                        attempt,
                        "error",
                        exc,
                        token,
                        started_at,
                        started_clock,
                        defer_retry=defer_retry,
                    )
            with self.lock:
                if self.state.done or self.state.finished == attempt:
                    return False
                self.state.inner = value
            if self.timeout is not None:
                remaining = self.timeout - elapsed
                if remaining <= 0:
                    return self._finish(
                        attempt,
                        "timeout",
                        None,
                        token,
                        started_at,
                        started_clock,
                        defer_retry=defer_retry,
                    )
                timer = threading.Timer(
                    remaining,
                    lambda: self._finish_safely(
                        attempt, "timeout", None, token, started_at, started_clock
                    ),
                )
                timer.daemon = True
                with self.lock:
                    self.state.timer = timer
                timer.start()

            def _on_done(future, attempt=attempt, token=token):
                try:
                    result = future.result()
                except BaseException as exc:
                    retry = self._finish_safely(
                        attempt, "error", exc, token, started_at, started_clock
                    )
                else:
                    retry = self._finish_safely(
                        attempt, "ok", result, token, started_at, started_clock
                    )
                if retry:
                    self._pending_retry = True

            self._pending_retry = False
            value.add_done_callback(_on_done)
            if self._pending_retry:
                self._pending_retry = False
                return True
            return False
        return self._finish(
            attempt,
            "ok",
            value,
            token,
            started_at,
            started_clock,
            defer_retry=defer_retry,
        )

    def _run_body(self, attempt, token):
        with execution_scope(
            ctx=self.ctx,
            path=self.path,
            attempt=attempt,
            token=token,
            run_token=self.run_attempt_token,
            worker=self.base_worker,
            process_worker=self.base_process,
            in_body=True,
        ):
            if self.ctx is not None and self.ctx.cancelled.is_set():
                raise RuntimeError(
                    f"run cancelled before node '{self.node.name}' attempt {attempt}"
                )
            if self.parent_token is not None and self.parent_token.abandoned_in_chain():
                raise RuntimeError(
                    f"attempt {attempt} of node '{self.node.name}' is abandoned"
                )
            return self.node.fn(*self.args, **self.kwargs)

    def _start(self, attempt):
        """Drive attempts iteratively; a retry never nests another attempt."""
        self._local.in_start = True
        try:
            while True:
                with self.lock:
                    if self.state.done or self.state.finished >= attempt:
                        return
                if not self._run_attempt(attempt):
                    return
                attempt += 1
        except BaseException as exc:
            self._settle_unexpected(exc)
        finally:
            self._local.in_start = False

    def _run_attempt(self, attempt) -> bool:
        """Run one attempt; True means retry immediately with the next number."""
        with self.lock:
            if self.state.done or self.state.finished >= attempt:
                return False
            self.state.attempt = attempt
            self.state.inner = None
            # A run-level timeout token is an ancestor of the root attempt,
            # so abandoning it drops every descendant record.
            token = AttemptToken(self.parent_token or self.run_attempt_token)
        started_clock = time.perf_counter()
        started_at = _utcnow()
        if self.timeout is None:
            try:
                value = self._run_body(attempt, token)
            except BaseException as exc:
                return self._finish(
                    attempt,
                    "error",
                    exc,
                    token,
                    started_at,
                    started_clock,
                    defer_retry=True,
                )
            return self._after_body(
                attempt,
                value,
                token,
                started_at,
                started_clock,
                time.perf_counter() - started_clock,
                defer_retry=True,
            )

        box = {}

        def _target():
            try:
                box["value"] = self._run_body(attempt, token)
            except BaseException as exc:
                box["error"] = exc

        thread = threading.Thread(
            target=_target, name=f"{self.node.name}-attempt", daemon=True
        )
        thread.start()
        thread.join(self.timeout)
        elapsed = time.perf_counter() - started_clock
        if thread.is_alive():
            return self._finish(
                attempt,
                "timeout",
                None,
                token,
                started_at,
                started_clock,
                defer_retry=True,
            )
        if "error" in box:
            return self._finish(
                attempt,
                "error",
                box["error"],
                token,
                started_at,
                started_clock,
                defer_retry=True,
            )
        return self._after_body(
            attempt,
            box.get("value"),
            token,
            started_at,
            started_clock,
            elapsed,
            defer_retry=True,
        )


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


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


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
