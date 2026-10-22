"""One node's attempt loop: retry, timeout, logging, and settlement.

The loop is iterative: a zero-delay retry returns a signal to ``_start``
instead of nesting another attempt, so a large retry count cannot exhaust
the interpreter stack.  Every attempt settles its outcome, including on a
failed log write; drain therefore cannot wait on an orphaned future.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sequence_extensions.flow._context import (
    AttemptToken,
    RunContext,
    current_node_attempt,
    current_node_path,
    execution_scope,
    in_process_worker,
    in_worker,
)
from sequence_extensions.flow._futures import FlowOutcome, NodeTimeoutError, _is_future
from sequence_extensions.flow._gather import _contains_future
from sequence_extensions.graph.graph_future import GraphFuture


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


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
