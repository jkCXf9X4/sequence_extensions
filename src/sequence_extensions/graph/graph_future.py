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

import atexit
import concurrent.futures
import threading
import weakref

# Every GraphPool still alive, so the atexit handler can shut down lazily
# created executors of pools used without ``with``.
_LIVE_POOLS = weakref.WeakSet()


def _shutdown_live_pools() -> None:
    """Idempotently shut down the executors of all live pools (atexit hook)."""
    for pool in list(_LIVE_POOLS):
        if pool._executor is not None:
            pool._executor.shutdown(wait=True, cancel_futures=True)


atexit.register(_shutdown_live_pools)


def _is_dependency(value) -> bool:
    """A graph node may depend on another graph node or a plain Future."""
    return isinstance(value, (GraphFuture, concurrent.futures.Future))


def _dependency_future(dep):
    """The underlying ``concurrent.futures.Future`` of a dependency."""
    return dep.future if isinstance(dep, GraphFuture) else dep


def _set_exception_if_pending(future, exc) -> None:
    """Settle ``future`` with ``exc`` unless cancellation won the race."""
    if future.done():
        return
    try:
        future.set_exception(exc)
    except concurrent.futures.InvalidStateError:
        pass


class GraphFuture:
    """
    A small dependency-graph future.

    Build a graph by passing other GraphFuture objects (or plain
    ``concurrent.futures.Future`` values) as arguments::

        a = GraphFuture(fn_1, 5, 4)
        b = GraphFuture(fn_2, a, 4)

    Dependency arguments are replaced with their results by the time the
    function executes.  Scheduling is driven by callbacks from a bounded
    ``ThreadPoolExecutor`` (no polling/scheduler loop).  A function may
    return a GraphFuture or a plain Future; that future is chained onto
    this node so its result becomes this node's result.
    """

    def __init__(self, *args, **kwargs):
        """Create a node; Future values among the arguments become dependencies.

        Both :class:`GraphFuture` and plain :class:`concurrent.futures.Future`
        values are awaited before the function runs, so a node can depend on a
        future produced outside the graph layer.

        The function is normally the first positional argument.  The
        ``GraphFuture(function=fn, args=(...))`` keyword form is also
        accepted.  When a positional function is present, ``function`` and
        ``args`` in ``kwargs`` are ordinary arguments for the node instead
        of constructor keywords — a node may legitimately accept parameters
        with those names.
        """
        if args:
            function = args[0]
            positional = args[1:]
        elif "function" in kwargs:
            function = kwargs.pop("function")
            positional = tuple(kwargs.pop("args", ()))
        else:
            raise TypeError("GraphFuture() missing required argument: 'function'")

        self.function = function
        self.name = getattr(function, "__name__", str(function))

        # Keep positional order via integer keys: {0: arg0, 1: arg1, **kwargs}
        self.arguments = {**{i: arg for i, arg in enumerate(positional)}, **kwargs}
        self.dependencies = [x for x in self.arguments.values() if _is_dependency(x)]

        self.queued = False
        self.future = concurrent.futures.Future()
        self._pool = None
        # Guards the check-then-set of ``queued`` and the submit decision so a
        # node is never scheduled twice (and its function never double-runs).
        self._lock = threading.RLock()
        # Dependency ids whose done-callback is already attached to this node.
        # One callback per dependency is enough; repeated binds must not attach
        # a second one.
        self._attached_dep_ids = set()

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
        """
        Return this node's result, blocking until it is available.

        ``timeout`` (seconds) bounds the wait; on expiry a ``TimeoutError`` is
        raised.  Raises ``CancelledError`` if the node was cancelled, and
        propagates the node's function exception if it failed.
        """
        return self.future.result(timeout=timeout)

    def has_result(self) -> bool:
        """True only when the node completed successfully (done, not cancelled, no exception)."""
        return (
            self.future.done() and not self.future.cancelled() and self.future.exception() is None
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
            pending = [d for d in self.dependencies if not _dependency_future(d).done()]
            if pending:
                for dep in pending:
                    dep_id = id(dep)
                    if dep_id in self._attached_dep_ids:
                        continue
                    self._attached_dep_ids.add(dep_id)
                    _dependency_future(dep).add_done_callback(
                        lambda _f, node=self, p=pool: node._on_dep_done(p)
                    )
                return
        self._submit(pool)

    def _on_dep_done(self, pool) -> None:
        """Level-triggered: re-check all dependencies; submit once every one is done."""
        with self._lock:
            if self.queued:
                return
            if not all(_dependency_future(d).done() for d in self.dependencies):
                return
        self._submit(pool)

    def _submit(self, pool) -> None:
        """Idempotently mark queued and hand the node to the pool (lock-guarded)."""
        with self._lock:
            if self.queued:
                return
            self.queued = True
            self._pool = pool
        pool._submit_node(self)

    # ------------------------------------------------------------ #
    # Execution (runs on a pool worker thread)
    # ------------------------------------------------------------ #
    def _run(self) -> None:
        """Execute this node's function on a worker thread and settle ``future``."""
        if self._pool is None:
            _set_exception_if_pending(
                self.future, RuntimeError("GraphFuture executed without a bound GraphPool")
            )
            return
        if self.future.done():
            # The pool may have cancelled this node after it was queued but
            # before the worker picked it up; do not run side effects then.
            return
        try:
            args, kwargs = self._resolve_arguments()
            result = self.function(*args, **kwargs)

            if isinstance(result, GraphFuture):
                # Chain the inner graph into the pool; forward its result.
                # ``source=self`` keeps the running node in the cycle set,
                # so a node that returns itself (directly or through a
                # dependency) is rejected instead of waiting forever.
                self._pool._bind_graph(result, source=self)
                result.future.add_done_callback(self._forward_result)
            elif isinstance(result, concurrent.futures.Future):
                # A node may return a plain future (e.g. a deferred flow
                # attempt). No worker waits: the callback forwards its result.
                result.add_done_callback(self._forward_result)
            else:
                try:
                    self.future.set_result(result)
                except concurrent.futures.InvalidStateError:
                    # Cancelled at pool exit while the body ran to
                    # completion — the completion is discarded.
                    pass
        except Exception as e:
            # ``except Exception`` (not BaseException) so KeyboardInterrupt /
            # SystemExit propagate instead of being swallowed into the future.
            if not self.future.done():
                try:
                    self.future.set_exception(e)
                except concurrent.futures.InvalidStateError:
                    pass

    def _forward_result(self, inner_future) -> None:
        """Copy a chained future's result into this node's future."""
        try:
            try:
                self.future.set_result(inner_future.result())
            except concurrent.futures.InvalidStateError:
                pass
        except Exception as e:
            if not self.future.done():
                try:
                    self.future.set_exception(e)
                except concurrent.futures.InvalidStateError:
                    pass

    def _resolve_arguments(self):
        """
        Split ``self.arguments`` back into (args, kwargs), replacing any
        Futures with their results.
        """
        pos = {k: v for k, v in self.arguments.items() if isinstance(k, int)}
        kw = {k: v for k, v in self.arguments.items() if not isinstance(k, int)}

        def materialize(v):
            return _dependency_future(v).result() if _is_dependency(v) else v

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

    Lifecycle: the executor is created lazily on first use, so the pool works
    with or without the ``with`` statement.  Pools used without ``with`` are
    shut down at interpreter exit by an atexit handler.  Re-entering a pool
    (``__enter__`` twice, including after a previous ``__exit__``) raises
    ``RuntimeError``; ``__exit__`` cancels this pool's pending nodes and
    shuts the executor down.  Reactor-style callbacks (not polling) drive
    scheduling: a leaf is submitted as soon as it is reached; dependents are
    submitted when their dependencies complete.  The executor's worker pool
    bounds concurrency.
    """

    #: Pool subclasses that ship work to separate processes override this.
    process_workers = False

    def __init__(self, max_workers: int | None = 16):
        """Create a pool; the executor is created lazily on first use."""
        if max_workers is not None and (
            isinstance(max_workers, bool)
            or not isinstance(max_workers, int)
            or max_workers < 1
        ):
            raise ValueError(f"max_workers must be a positive integer or None, got {max_workers!r}")
        self.max_workers = max_workers
        self._executor = None
        self._shutdown = False
        self._entered = False
        self._nodes = []  # every bound node, so __exit__ can cancel stragglers
        self._node_ids = set()
        # Serializes binding and pool lifecycle: public binds, binds from
        # node bodies returning futures, and shutdown all touch _visiting /
        # _nodes / _node_ids.  It is an RLock because _wire -> _submit_node
        # runs while the binder holds it.
        self._bind_lock = threading.RLock()
        # Pool-level DFS state; protected by _bind_lock.
        self._visiting = set()
        _LIVE_POOLS.add(self)

    # ------------------------------------------------------------ #
    # Context manager
    # ------------------------------------------------------------ #
    def _ensure_executor(self) -> None:
        """Lazily create the executor so the pool also works outside ``with``."""
        if self._shutdown:
            return
        if self._executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=self.max_workers, thread_name_prefix="graph-worker"
            )

    def __enter__(self) -> "GraphPool":
        """Create the executor and return the pool (rejects ANY re-entry)."""
        with self._bind_lock:
            if self._entered:
                raise RuntimeError("GraphPool.__enter__ called more than once")
            self._entered = True
            self._shutdown = False
            self._ensure_executor()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Cancel this pool's pending nodes, then shut the executor down.

        Cancellation is pool-scoped: only nodes bound to *this* pool
        (``self._nodes``) are cancelled, so pools of concurrent flows in
        one process do not interfere.  A node never bound to any pool is
        left pending — bind nodes through ``pool.result()`` / ``pool.bind()``.
        """
        # Do not hold the bind lock across executor.shutdown(wait=True):
        # a worker returning a GraphFuture may be waiting for that lock.
        with self._bind_lock:
            self._shutdown = True
            nodes = list(self._nodes)
            executor = self._executor
        for node in nodes:
            if not node.future.done():
                node.future.cancel()
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
            with self._bind_lock:
                if self._executor is executor:
                    self._executor = None
        # Return None -> propagate any exception from the ``with`` body.

    # ------------------------------------------------------------ #
    # Public facade
    # ------------------------------------------------------------ #
    def result(self, gf: GraphFuture, timeout=None):
        """
        Evaluate the graph reachable from ``gf`` and return its result.

        Blocks until the result is available; ``timeout`` (seconds) bounds the
        wait and raises ``TimeoutError`` on expiry.
        """
        self._bind_graph(gf)
        return gf.result(timeout=timeout)

    def bind(self, gf: GraphFuture) -> None:
        """
        Bind the graph reachable from ``gf`` without touching any result.

        Submits every ready leaf to this pool and wires the rest for
        event-driven scheduling; raises ``ValueError`` on a dependency
        cycle.  A pure bind: unlike ``result(gf, timeout=0)``, it never
        raises a settled node's own exception.
        """
        self._bind_graph(gf)

    # ------------------------------------------------------------ #
    # Scheduling support
    # ------------------------------------------------------------ #
    def _submit_node(self, node: GraphFuture) -> None:
        """Queue ``node`` for execution on this pool (dispatch seam).

        Subclasses redirect execution here — e.g. a process-pool subclass
        ships the node's function and resolved arguments to a worker
        process instead of running ``node._run`` on a worker thread.
        """
        with self._bind_lock:
            if self._shutdown:
                # Pool is exiting: don't enqueue fresh work; settle as cancelled.
                node.future.cancel()
                return
            self._ensure_executor()
            executor = self._executor
        try:
            executor.submit(node._run)
        except Exception as exc:
            _set_exception_if_pending(node.future, exc)

    def _bind_graph(self, gf: GraphFuture, *, source=None) -> None:
        """
        Walk the dependency graph (post-order) and wire every node.

        Cycle detection: a node seen again while still being visited (a DFS
        back-edge) means the graph is cyclic, and a ValueError is raised
        instead of deadlocking forever in ``result()``.  ``source`` is the
        node whose body is chaining ``gf``; keeping it in the visit set
        catches a node that returns itself.

        All binds on one pool are serialized.  Without this, concurrent
        binds would corrupt the shared ``_visiting`` set (false cycles) and
        append nodes without a common ordering.  A shut-down pool still
        wires nodes so their futures settle as cancelled; it just cannot
        create a new executor.
        """
        with self._bind_lock:
            self._ensure_executor()
            seen = set()
            visited_nodes = []
            source_id = id(source) if source is not None else None
            if source_id is not None:
                if source_id in self._visiting:
                    raise ValueError("dependency cycle detected")
                self._visiting.add(source_id)
            try:
                def visit(node):
                    nid = id(node)
                    if nid in self._visiting:
                        raise ValueError("dependency cycle detected")
                    if nid in seen:
                        return
                    self._visiting.add(nid)
                    seen.add(nid)
                    visited_nodes.append(node)
                    try:
                        for dep in node.dependencies:
                            if isinstance(dep, GraphFuture):
                                visit(dep)
                        node._wire(self)
                        if nid not in self._node_ids:
                            self._node_ids.add(nid)
                            self._nodes.append(node)
                    finally:
                        self._visiting.discard(nid)

                visit(gf)
                if self._shutdown:
                    for node in visited_nodes:
                        if not node.future.done():
                            node.future.cancel()
            finally:
                if source_id is not None:
                    self._visiting.discard(source_id)
