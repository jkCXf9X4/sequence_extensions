import concurrent.futures


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

    # ------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------ #
    def __str__(self):
        return (
            f"[GraphFuture] {hex(id(self))} {self.name} "
            f"done={self.future.done()} queued={self.queued}"
        )

    def __repr__(self):
        return (
            f"[GraphFuture] {hex(id(self))} {self.name} {self.arguments} "
            f"done={self.future.done()} queued={self.queued}"
        )

    def set_name(self, name):
        self.name = name
        return self

    # ------------------------------------------------------------ #
    # Result access
    # ------------------------------------------------------------ #
    def result(self, timeout=None):
        """Return this node's result (or obtainable future of a nested graph)."""
        return self.future.result(timeout=timeout)

    def has_result(self):
        return self.future.done() and not self.future.cancelled()

    # ------------------------------------------------------------ #
    # Scheduling (called by the GraphPool)
    # ------------------------------------------------------------ #
    def _wire(self, pool):
        """
        Queue this node for execution once all its dependencies are done.
        Otherwise attach a callback to each pending dependency.

        Idempotent: does nothing once ``queued``.
        """
        if self.queued:
            return

        if not all(d.future.done() for d in self.dependencies):
            for dep in self.dependencies:
                dep.future.add_done_callback(
                    lambda f, node=self, p=pool: node._on_dep_done(p)
                )
            return

        self.queued = True
        self._pool = pool
        pool._executor.submit(self._run)

    def _on_dep_done(self, pool):
        self._wire(pool)

    # ------------------------------------------------------------ #
    # Execution (runs on a pool worker thread)
    # ------------------------------------------------------------ #
    def _run(self):
        try:
            args, kwargs = self._resolve_arguments()
            result = self.function(*args, **kwargs)

            if isinstance(result, GraphFuture):
                # Chain the inner graph into the pool; forward its result.
                self._pool._bind_graph(result)
                result.future.add_done_callback(self._forward_result)
            else:
                self.future.set_result(result)
        except BaseException as e:
            self.future.set_exception(e)

    def _forward_result(self, inner_future):
        try:
            self.future.set_result(inner_future.result())
        except BaseException as e:
            self.future.set_exception(e)

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
        self.max_workers = max_workers
        self._executor = None

    # ------------------------------------------------------------ #
    # Context manager
    # ------------------------------------------------------------ #
    def __enter__(self):
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="graph-worker"
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=True)
        return False  # propagate any exception

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
    def _bind_graph(self, gf: GraphFuture):
        """Walk the dependency graph (post-order) and wire every node."""
        seen = set()

        def visit(node):
            if id(node) in seen:
                return
            seen.add(id(node))
            for dep in node.dependencies:
                visit(dep)
            node._wire(self)

        visit(gf)