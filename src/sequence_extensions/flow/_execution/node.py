"""``@node`` and :class:`NodeFunction`: decoration, policy, submit.

Holds the decorator and the node object: policy resolution, inline
and concurrent execution.  Process-pool pickle/transport lives in
``_pickle``; ``__init__`` re-exports this module and ``_pickle`` as the
public surface."""

from __future__ import annotations

import functools
import threading

from .._config.context import (
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
from .._config.options import UNSET, NodeIdentity, fill_parameters, validate_node_policy
from .attempt import _AttemptRunner
from .futures import FlowFuture, FlowOutcome, NodeTimeoutError
from .gather import gather
from .pickle import _reduce_node_function, register_alias
from .process_pool import _process_node_runner

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

#: Identity reservation: instance numbers must be unique even when several
#: workers submit the same ``(name, path)`` concurrently.
_IDENTITY_LOCK = threading.Lock()


def _claim_identity(ctx: RunContext, name: str) -> NodeIdentity:
    """Reserve the next submission-order identity for ``name`` in ``ctx``."""
    path = current_node_path() + (name,)
    key = (name, path)
    with _IDENTITY_LOCK:
        instance = ctx.node_instances.get(key, 0) + 1
        ctx.node_instances[key] = instance
    return NodeIdentity(name, path, instance)


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
        # reference would fail pickle's identity check.  register_alias
        # rebinds the raw function under a unique private alias in its own
        # module; __reduce__ ships (alias, policy) instead.
        alias = _alias if _alias is not None else register_alias(fn, self.name)
        if alias is not None:
            self._pickle_alias = alias
        self.__node__ = self.name

    # ------------------------------------------------------------ #
    # Policy
    # ------------------------------------------------------------ #
    def _effective_policy(self, identity: NodeIdentity | None = None):
        """Resolve this attempt's policy.

        Precedence: plan override (``RunOptions.node_policies``) > explicit
        ``@node`` keyword > ``RunOptions.node_defaults`` > built-in default.
        An exact ``identity`` policy wins over a name-wide policy; callers
        without an identity look up the name only.
        """
        ctx = current_run()
        options = ctx.options if ctx is not None else None
        policies = getattr(options, "node_policies", None) if options is not None else None
        if policies is UNSET:
            policies = None
        plan_policy = None
        if policies:
            if identity is not None:
                plan_policy = policies.get(identity)
            if plan_policy is None:
                plan_policy = policies.get(self.name)
        if plan_policy is not None:
            return (
                int(plan_policy.retries),
                float(plan_policy.retry_delay_seconds),
                None if plan_policy.timeout is None else float(plan_policy.timeout),
            )
        defaults = getattr(options, "node_defaults", None) if options is not None else None
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

        # Identity is claimed before filling: an exact-entry override targets
        # this occurrence, not every node sharing the name.
        identity = _claim_identity(ctx, self.name)
        args, kwargs = fill_parameters(
            self.name,
            self.fn,
            args,
            kwargs,
            getattr(ctx.options, "parameters", None),
            identity=identity,
        )

        parent_token = token
        run_attempt_token = current_run_attempt_token()
        if ctx.pool.process_workers:
            # Process mode: the node's function must be picklable, so the
            # runner is this module-level function carrying the node and a
            # plain-dict run header; the worker buffers run-log records and
            # the run replays them before run_end.
            retries, delay, timeout = self._effective_policy(identity)
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
                        identity=identity,
                    )

            gf = FlowFuture(_runner, *args, **kwargs)
        gf.set_name(self.name)
        gf.path = identity.path
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
        identity: NodeIdentity | None = None,
    ) -> FlowOutcome:
        """Run the attempt loop; return a future settled at the final outcome."""
        retries, delay, timeout = self._effective_policy(identity)
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


#: Pickle transport for process pools lives in ``_pickle``; attach it so
#: ``NodeFunction`` still answers ``__reduce__`` without hosting the logic.
NodeFunction.__reduce__ = _reduce_node_function


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
