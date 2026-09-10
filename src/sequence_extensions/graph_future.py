"""
graph_future — a small dependency-graph future built on a thread pool.

``GraphFuture`` nodes form a DAG: a node's ``function`` is executed once all
of its dependency nodes (passed as GraphFuture arguments) have completed, and
their results are substituted in.  Scheduling is event-driven (callback based)
with a bounded ``ThreadPoolExecutor``, so no polling or scheduler loop is
needed.  ``GraphPool`` lazily creates the executor, so it may be used with or
without the ``with`` statement (though the context manager form guarantees the
executor is shut down).
"""

import concurrent.futures
import threading


class GraphFuture:
    """
    A small dependency-graph future.

    Build a graph by passing other GraphFuture objects as arguments::

        a = GraphFuture(fn_1, 5, 4)
        b = GraphFuture(fn_2, a, 4)

    Dependency arguments are replaced with their results by the time the
    function executes.  Scheduling is driven by callbacks from a bounded
    ``ThreadPoolExecutor`` (no polling/scheduler loop).  A function may
    return another GraphFuture; that future is chained onto this node so
    its result becomes this node's result.
    """

    def __init__(self, function, /, *args, **kwargs):
        """Create a node; GraphFuture values among ``args``/``kwargs`` become dependencies."""
        self.function = function
        self.name = getattr(function, "__name__", str(function))

        # Keep positional order via integer keys: {0: arg0, 1: arg1, **kwargs}
        self.arguments = {**{i: arg for i, arg in enumerate(args)}, **kwargs}
        self.dependencies = [
            x for x in self.arguments.values() if isinstance(x, GraphFuture)
        ]

        self.queued = False
        self.future = concurrent.futures.Future()
        self._pool = None
        # Guards the check-then-set of ``queued`` and the submit decision so a
        # node is never scheduled twice (and its function never double-runs).
        self._lock = threading.RLock()
        # Dependents ({GraphFuture}) that have already attached a done-callback
        # to this node's future — guarantees each callback is attached at most
        # once (per dependent), which kills the re-attach recursion loop.
        self._callback_attached = set()

    # ------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------ #
    def __str__(self):
        """Human-readable one-liner description of this node."""
        return (
            f"[GraphFuture] {hex(id(self))} {self.name} "
            f"done={self.future.done()} queued={self.queued}"
        )

    def __repr__(self):
        """Detailed one-liner description including this node's arguments."""
        return (
            f"[GraphFuture] {hex(id(self))} {self.name} {self.arguments} "
            f"done={self.future.done()} queued={self.queued}"
        )

    def set_name(self, name) -> "GraphFuture":
        """Set a human-readable name for this node; returns ``self`` for chaining."""
        self.name = name
        return self

    # ------------------------------------------------------------ #
    # Result access
    # ------------------------------------------------------------ #
    def result(self, timeout=None):
        """Return this node's result (or obtainable future of a nested graph)."""
        return self.future.result(timeout=timeout)

    def has_result(self) -> bool:
        """True only when the node completed successfully (done, not cancelled, no exception)."""
        return (
            self.future.done()
            and not self.future.cancelled()
            and self.future.exception() is None
        )

    # ------------------------------------------------------------ #
    # Convenience passthroughs to ``self.future`` (Future-like facade)
    # ------------------------------------------------------------ #
    def done(self) -> bool:
        """Convenience passthrough to ``self.future.done()``."""
        return self.future.done()

    def cancelled(self) -> bool:
        """Convenience passthrough to ``self.future.cancelled()``."""
        return self.future.cancelled()

    def exception(self, timeout=None):
        """Convenience passthrough to ``self.future.exception(timeout)``."""
        return self.future.exception(timeout=timeout)

    def add_done_callback(self, fn) -> None:
        """Convenience passthrough to ``self.future.add_done_callback(fn)``."""
        self.future.add_done_callback(fn)

    # ------------------------------------------------------------ #
    # Scheduling (called by the GraphPool)
    # ------------------------------------------------------------ #
    def _wire(self, pool) -> None:
        """
        Queue this node once every dependency is fulfilled.

        Attaches exactly one done-callback to each still-pending dependency;
        scheduling is level-triggered via ``_on_dep_done`` so callbacks are
        never re-attached (no re-entrant recursion).  If there are no pending
        dependencies (including the zero-dependency case), submit immediately.
        """
        with self._lock:
            if self.queued:
                return
            pending = [d for d in self.dependencies if not d.future.done()]
            if pending:
                for dep in pending:
                    with dep._lock:
                        if self in dep._callback_attached:
                            continue
                        dep._callback_attached.add(self)
                        need_attach = True
                    if need_attach:
                        dep.future.add_done_callback(
                            lambda _f, node=self, p=pool: node._on_dep_done(p)
                        )
                return
        self._submit(pool)

    def _on_dep_done(self, pool) -> None:
        """Level-triggered: re-check all dependencies; submit once every one is done."""
        with self._lock:
            if self.queued:
                return
            if not all(d.future.done() for d in self.dependencies):
                return
        self._submit(pool)

    def _submit(self, pool) -> None:
        """Idempotently queue ``_run`` on the pool's executor (lock-guarded)."""
        with self._lock:
            if self.queued:
                return
            self.queued = True
            self._pool = pool
            if pool._shutdown:
                # Pool is exiting: don't enqueue fresh work; settle as cancelled.
                try:
                    self.future.set_exception(concurrent.futures.CancelledError())
                except concurrent.futures.InvalidStateError:
                    pass
                return
            pool._ensure_executor()
            pool._executor.submit(self._run)

    # ------------------------------------------------------------ #
    # Execution (runs on a pool worker thread)
    # ------------------------------------------------------------ #
    def _run(self) -> None:
        """Execute this node's function on a worker thread and settle ``future``."""
        if self._pool is None:
            self.future.set_exception(
                RuntimeError("GraphFuture executed without a bound GraphPool")
            )
            return
        try:
            args, kwargs = self._resolve_arguments()
            result = self.function(*args, **kwargs)

            if isinstance(result, GraphFuture):
                # Chain the inner graph into the pool; forward its result.
                self._pool._bind_graph(result)
                result.future.add_done_callback(self._forward_result)
            else:
                self.future.set_result(result)
        except Exception as e:
            # ``except Exception`` (not BaseException) so KeyboardInterrupt /
            # SystemExit propagate instead of being swallowed into the future.
            if not self.future.done():
                try:
                    self.future.set_exception(e)
                except concurrent.futures.InvalidStateError:
                    pass

    def _forward_result(self, inner_future) -> None:
        """Copy a chained inner GraphFuture's result into this node's future."""
        try:
            self.future.set_result(inner_future.result())
        except Exception as e:
            if not self.future.done():
                try:
                    self.future.set_exception(e)
                except concurrent.futures.InvalidStateError:
                    pass

    def _resolve_arguments(self):
        """
        Split ``self.arguments`` back into (args, kwargs), replacing any
        GraphFuture dependencies with their results.
        """
        pos = {k: v for k, v in self.arguments.items() if type(k) is int}
        kw = {k: v for k, v in self.arguments.items() if type(k) is not int}

        def materialize(v):
            return v.future.result() if isinstance(v, GraphFuture) else v

        args = [materialize(pos[k]) for k in sorted(pos)]
        kwargs = {k: materialize(v) for k, v in kw.items()}
        return args, kwargs


class GraphPool:
    """
    Evaluate a GraphFuture graph with a bounded thread pool.

    Usage::

        with GraphPool(max_workers=4) as pool:
            a = GraphFuture(fn_1, 5, 4)          # leaf, runs immediately
            b = GraphFuture(fn_2, a, 4)          # waits for a
            result = pool.result(b)              # -> b's value

    Reactor-style callbacks (not polling) drive scheduling: a leaf is
    submitted as soon as it is reached; dependents are submitted when their
    dependencies complete.  The executor's thread pool bounds concurrency.
    """

    def __init__(self, max_workers: int = 16):
        """Create a pool; the executor is created lazily on first use."""
        self.max_workers = max_workers
        self._executor = None
        self._shutdown = False
        self._nodes = []  # every bound node, so __exit__ can cancel stragglers

    # ------------------------------------------------------------ #
    # Context manager
    # ------------------------------------------------------------ #
    def _ensure_executor(self) -> None:
        """Lazily create the executor so the pool also works outside ``with``."""
        if self._executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=self.max_workers, thread_name_prefix="graph-worker"
            )

    def __enter__(self) -> "GraphPool":
        """Create the executor and return the pool (rejects re-entry)."""
        if self._executor is not None:
            raise RuntimeError("GraphPool.__enter__ called more than once")
        self._shutdown = False
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="graph-worker"
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Cancel pending work, then shut the executor down."""
        self._shutdown = True
        for node in self._nodes:
            if not node.future.done():
                try:
                    node.future.set_exception(concurrent.futures.CancelledError())
                except concurrent.futures.InvalidStateError:
                    pass  # a worker settled it concurrently
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
        # Return None -> propagate any exception from the ``with`` body.

    # ------------------------------------------------------------ #
    # Public facade
    # ------------------------------------------------------------ #
    def result(self, gf: GraphFuture):
        """Evaluate the graph reachable from ``gf`` and return its result."""
        self._bind_graph(gf)
        return gf.result()

    # ------------------------------------------------------------ #
    # Scheduling support
    # ------------------------------------------------------------ #
    def _bind_graph(self, gf: GraphFuture) -> None:
        """
        Walk the dependency graph (post-order) and wire every node.

        Cycle detection: a node seen again while still being visited (a DFS
        back-edge) means the graph is cyclic, and a ValueError is raised
        instead of deadlocking forever in ``result()``.
        """
        self._ensure_executor()
        seen = set()
        visiting = set()

        def visit(node):
            nid = id(node)
            if nid in visiting:
                raise ValueError("dependency cycle detected")
            if nid in seen:
                return
            visiting.add(nid)
            seen.add(nid)
            for dep in node.dependencies:
                visit(dep)
            visiting.discard(nid)
            node._wire(self)
            self._nodes.append(node)

        visit(gf)