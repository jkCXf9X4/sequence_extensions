"""
Execution engine for the V&V workflow layer.

The engine executes the node tree produced by
:mod:`sequence_extensions.workflow.schema` (``Action`` / ``Sequential`` /
``Parallel``) on top of the :class:`sequence_extensions.graph` substrate
(``GraphFuture`` / ``GraphPool``).  The semantics follow the paper
"Automation Nation: Taming Complex V&V Workflows" (16th International
Modelica & FMI Conference, September 2025, Lucerne, Switzerland;
DOI 10.3384/ecp12076741), section 4.2:

* **Sequential** — children execute in strict order: child ``i + 1`` depends
  on child ``i``.
* **Parallel** — children are independent and run CONCURRENTLY on the
  ``GraphPool``'s thread pool; the group's result is the ordered list of its
  children's results, and each child's result is also passed to the next
  sibling as its own keyword argument (fan-in).
* **Global parameters** — the root group's ``.globals`` (the
  ``<VerificationWorkflow>`` wrapper's parameter elements) are passed as
  default keyword arguments to EVERY function; an action's own ``.params``
  win over globals, and upstream results win over both.
* **Dynamic adaptation** — a registered function may return an
  ``Action`` / ``Sequential`` / ``Parallel`` node (or a list of them); the
  returned node(s) are spliced into the workflow in place of the action's
  next sibling, which must be a group (the paper's Listings 5 and 7).  The
  replaced group's subtree is cancelled (its actions do not run).  A splice
  attempt that is out of scope raises ``ValueError``.
* **At most once** — every action executes at most once; the engine never
  re-runs a function (no feedback loops).

Public surface (pinned): :func:`run_workflow`, :func:`Test_Framework`.
Internal but unit-testable: :func:`check_splice_scope`.

Opt-in execution history: pass ``history=RunHistory()`` (see
:mod:`sequence_extensions.workflow.history`) to ``run_workflow`` /
``Test_Framework`` to record per-action evidence — including actions
spliced in at runtime by dynamic adaptation, in true completion order —
and replay it deterministically with
:func:`sequence_extensions.workflow.history.replay`.  Without a
``history`` argument the engine behaves exactly as before.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Union

from ..graph import GraphFuture, GraphPool
from .history import ExecutionRecord, RunHistory, recordable_result, resolve_group_path
from .params import normalize_params
from .registry import DEFAULT_REGISTRY, FunctionRegistry
from .schema import Action, Parallel, Sequential, parse_workflow

__all__ = [
    "Test_Framework",
    "check_splice_scope",
    "run_workflow",
]

_Node = Union[Action, Sequential, Parallel]
_Group = Union[Sequential, Parallel]
# Result placeholder for a node cancelled by a splice (its actions do not run).
_SENTINEL = object()


# --------------------------------------------------------------------------- #
# Dynamic adaptation: splice / scope check
# --------------------------------------------------------------------------- #


def check_splice_scope(
    parent: _Group | None,
    index: int,
    returned: Any,
) -> None:
    """
    Validate that a function's returned node(s) may be spliced into the
    workflow (paper section 4.2, dynamic adaptation).

    A function may return an ``Action`` / ``Sequential`` / ``Parallel`` node
    (or a list of them); the node(s) are spliced into the workflow in place
    of the action's NEXT SIBLING, which must therefore be a group (the
    paper's Listings 5 and 7: the driver action is followed by the group it
    adapts).  The splice stays within the returning action's own grouping
    scope: an action may only alter what is downstream of it inside the
    group it belongs to, never siblings of that group.

    ``parent`` is the group containing the returning action, ``index`` is
    the action's position in ``parent.children``, and ``returned`` is the
    function's return value.

    Raises ``ValueError`` when the return value is a node (or list of nodes)
    but the action has no next sibling, or the next sibling is not a group
    (out-of-scope splice attempt).  A plain (non-node) return value is
    always allowed.
    """
    nodes = _as_node_list(returned)
    if nodes is None:
        return
    if parent is None or index + 1 >= len(parent.children):
        raise ValueError(
            "dynamic adaptation: action returned workflow node(s) but has no "
            "next sibling to splice them into; a splicing action must be "
            "followed by the group it adapts"
        )
    next_sibling = parent.children[index + 1]
    if not isinstance(next_sibling, (Sequential, Parallel)):
        raise ValueError(
            "dynamic adaptation: action returned workflow node(s) but its "
            "next sibling is not a group; a splice may only replace a group "
            "within the action's own grouping scope"
        )


def _mark_dynamic(node: _Node) -> None:
    """
    Mark ``node`` and its whole subtree as spliced in by dynamic adaptation.

    The flag is read by the history recording (an action's record carries
    ``dynamic=True`` when the action was not in the parsed workflow but was
    returned by an upstream function at runtime).  It is a plain attribute
    set, so it is inert when no history is requested.
    """
    node._engine_dynamic = True
    if isinstance(node, (Sequential, Parallel)):
        for child in node.children:
            _mark_dynamic(child)


def _as_node_list(returned: Any) -> list[_Node] | None:
    """
    Normalize a function's return value to a list of workflow nodes.

    Returns ``None`` when the value is a plain (non-node) result.  A single
    node is wrapped in a one-element list; a list/tuple must contain only
    nodes (anything else is a plain result and yields ``None``).
    """
    if isinstance(returned, (Action, Sequential, Parallel)):
        return [returned]
    if isinstance(returned, (list, tuple)):
        if returned and all(isinstance(item, (Action, Sequential, Parallel)) for item in returned):
            return list(returned)
    return None


# --------------------------------------------------------------------------- #
# Execution engine
# --------------------------------------------------------------------------- #


class _Engine:
    """
    Build and run a workflow node tree on a :class:`GraphPool`.

    The engine walks the tree once, creating one :class:`GraphFuture` per
    action (each action executes at most once) and one per group (the group's
    result is the ordered list of its children's results).  A function that
    returns workflow node(s) has them spliced in place of the action's next
    sibling (a group); the replaced group's subtree is cancelled so its
    actions do not run, and the spliced group's result becomes the action's
    result.
    """

    def __init__(
        self,
        root: _Group,
        registry: FunctionRegistry,
        parameters: dict[str, Any] | None = None,
        history: RunHistory | None = None,
    ) -> None:
        """Create an engine for ``root``; ``parameters`` override XML globals."""
        self._registry = registry
        self._globals: dict[str, Any] = dict(root.globals)
        if parameters:
            self._globals.update(parameters)
        self._root = root
        self._lock = threading.Lock()
        self._cancelled: set[GraphFuture] = set()
        self._pool: GraphPool | None = None
        # Opt-in execution history (None = record nothing; the engine then
        # behaves exactly as if this feature did not exist).
        self._history = history

    # ------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------ #
    def run(self) -> Any:
        """
        Execute the workflow and return the final result.

        The final result is the result of the last action in the root
        group's execution order (the last child, resolved recursively into
        groups).  Raises ``ValueError`` for an unknown function name or an
        out-of-scope splice attempt, and propagates any exception raised by
        a function.
        """
        with GraphPool() as pool:
            self._pool = pool
            root_future = self._build(self._root, [])
            pool.result(root_future)
            # The tree may have been spliced during execution, so the final
            # action is resolved AFTER the run (the last child of the root,
            # resolved recursively into groups).
            final_future = self._find_final_future(self._root)
            if final_future is None:
                return None
            result = final_future.result()
            if self._history is not None:
                self._mark_final(final_future)
            return result

    # ------------------------------------------------------------ #
    # Graph construction
    # ------------------------------------------------------------ #
    def _build(self, node: _Node, upstream: list[GraphFuture]) -> GraphFuture:
        """
        Build the :class:`GraphFuture` for ``node``.

        ``upstream`` are the futures whose results are passed to the node's
        functions as keyword arguments (the results of the actions that
        precede it in execution order).  Returns the node's future.
        """
        if isinstance(node, Action):
            return self._build_action(node, upstream)
        if isinstance(node, Sequential):
            return self._build_sequential(node, upstream)
        return self._build_parallel(node, upstream)

    def _build_action(self, action: Action, upstream: list[GraphFuture]) -> GraphFuture:
        """
        Build the future for one action.

        The upstream futures are passed as positional arguments so
        :class:`GraphFuture` registers them as dependencies (ordering); the
        corresponding actions are passed separately for result keying.
        """
        parent, index = self._locate(action)
        fn = self._registry.get(action.function)
        params = normalize_params(action.params)
        actions = [getattr(f, "_action", None) for f in upstream]
        future = GraphFuture(
            self._run_action,
            *upstream,
            fn=fn,
            params=params,
            actions=actions,
            action=action,
            parent=parent,
            index=index,
            engine=self,
            upstream_futures=upstream,
        )
        action._engine_future = future
        future._action = action
        return future

    def _build_sequential(self, group: Sequential, upstream: list[GraphFuture]) -> GraphFuture:
        """
        Build a :class:`Sequential` group: strict child order.

        Child ``i + 1`` depends on child ``i``; the next child's upstream is
        the previous children's fan-in futures (an action contributes its
        own future; a group contributes its direct children's futures).
        """
        futures: list[GraphFuture] = []
        chain: list[GraphFuture] = list(upstream)
        for child in group.children:
            child_f = self._build(child, chain)
            futures.append(child_f)
            if isinstance(child, Action):
                chain = chain + [child_f]
            else:
                chain = chain + child._engine_fan_in
        return self._group_future(group, futures)

    def _build_parallel(self, group: Parallel, upstream: list[GraphFuture]) -> GraphFuture:
        """
        Build a :class:`Parallel` group: independent, concurrent children.

        All children depend only on the actions before the group, so the
        ``GraphPool`` runs them concurrently.
        """
        futures = [self._build(child, list(upstream)) for child in group.children]
        return self._group_future(group, futures)

    def _group_future(self, group: _Group, futures: list[GraphFuture]) -> GraphFuture:
        """
        Build the future for a group: the ordered list of its children's
        results.  Records the group's fan-in futures (its direct children's
        futures, passed to the next sibling) and its internal futures (the
        group's future + all internal action futures, for splice cancellation).
        """
        group._engine_fan_in = futures
        future = GraphFuture(self._collect, *futures, group=group, engine=self)
        group._engine_future = future
        internal: set[GraphFuture] = {future}
        for child, f in zip(group.children, futures):
            if isinstance(child, Action):
                internal.add(f)
            else:
                internal |= child._engine_internal
        group._engine_internal = internal
        return future

    # ------------------------------------------------------------ #
    # Execution helpers (run on pool worker threads)
    # ------------------------------------------------------------ #
    def _run_action(
        self,
        *upstream_results: Any,
        fn: Callable[..., Any],
        params: dict[str, Any],
        actions: list[Action | None],
        action: Action,
        parent: _Group | None,
        index: int,
        engine: _Engine,
        upstream_futures: list[GraphFuture],
    ) -> Any:
        """
        Execute one action's function and splice in any returned nodes.

        The call kwargs are, in precedence order (own parameters win): the
        action's own parameters, the upstream results (keyed by the
        producing action's function name, with collision suffixes), and the
        global parameters.  If the function returns workflow node(s), they
        are spliced in place of the action's next sibling (a group); the
        replaced group's subtree is cancelled and the spliced group's result
        becomes this action's result.
        """
        if engine._skip(action._engine_future):
            return _SENTINEL
        kwargs: dict[str, Any] = dict(engine._globals)
        used: dict[str, int] = {}
        for result, act in zip(upstream_results, actions):
            if act is None or result is _SENTINEL:
                continue
            name = act.function
            if name in used:
                used[name] += 1
                key = f"{name}_{used[name]}"
            else:
                used[name] = 1
                key = name
            kwargs[key] = result
        kwargs.update(params)
        if engine._history is None:
            result = fn(**kwargs)
        else:
            result = engine._record_call(action, fn, kwargs)
        nodes = _as_node_list(result)
        if nodes is None:
            return result
        check_splice_scope(parent, index, result)
        next_sibling = parent.children[index + 1]
        engine._cancel(next_sibling)
        with engine._lock:
            parent.children[index + 1 : index + 2] = nodes
        for node in nodes:
            _mark_dynamic(node)
        spliced = engine._build_sequential(Sequential(*nodes), list(upstream_futures))
        return engine._pool.result(spliced)

    def _collect(self, *results: Any, group: _Group, engine: _Engine) -> Any:
        """
        A group's result: the ordered list of its children's results.

        Returns ``_SENTINEL`` if the group was cancelled by a splice.
        """
        if engine._skip(group._engine_future):
            return _SENTINEL
        return list(results)

    # ------------------------------------------------------------ #
    # Execution history (opt-in)
    # ------------------------------------------------------------ #
    def _record_call(
        self,
        action: Action,
        fn: Callable[..., Any],
        kwargs: dict[str, Any],
    ) -> Any:
        """
        Call ``fn(**kwargs)`` and record the call as an ExecutionRecord.

        The record captures what ACTUALLY executed: the action's registry
        name, the resolved function's name, the resolved parameters (the
        exact ``kwargs`` the function received), the result (a dynamic-
        adaptation return normalized by ``recordable_result``) or the
        exception, timestamps taken around the call, the group path at
        call time, and whether the action was spliced in at runtime.  The
        record is appended to the history when the call completes, so the
        history is in true completion order.  An exception is re-raised
        after being recorded.
        """
        record = ExecutionRecord(
            name=action.function,
            function=getattr(fn, "__name__", type(fn).__name__),
            params=dict(kwargs),
            group_path=self._path_of(action),
            dynamic=getattr(action, "_engine_dynamic", False),
        )
        # Identity-keyed link so the final action's record can be found
        # exactly, even if a later splice shifts tree positions.
        action._engine_record = record
        record.started_at = time.time()
        try:
            result = fn(**kwargs)
        except BaseException as exc:
            record.ended_at = time.time()
            record.exception = exc
            self._history.add(record)
            raise
        record.ended_at = time.time()
        record.result = recordable_result(result)
        self._history.add(record)
        return result

    def _path_of(self, action: Action) -> str:
        """
        The action's group path, read under the engine lock.

        Splices mutate ``children`` lists under the same lock, so taking it
        here guarantees the walk sees a consistent tree (the path as it
        stood at call time).
        """
        with self._lock:
            return resolve_group_path(self._root, action)

    def _mark_final(self, final_future: GraphFuture) -> None:
        """
        Mark the run's final action on the history (for ``replay``).

        ``replay`` returns the replayed value of the run's final action —
        the action whose result ``run_workflow`` / ``Test_Framework``
        returned — so the engine records that action's completion-order
        index on the history after a successful run.  The record is found
        by identity (``action._engine_record``, set in ``_record_call``),
        which stays exact even when a late splice shifts tree positions
        after the action recorded its group path.
        """
        action = getattr(final_future, "_action", None)
        record = getattr(action, "_engine_record", None) if action is not None else None
        if record is not None:
            self._history.final_order = record.order

    # ------------------------------------------------------------ #
    # Splice support
    # ------------------------------------------------------------ #
    def _cancel(self, group: _Group) -> None:
        """Cancel a group's subtree (its future + all internal action futures)."""
        with self._lock:
            self._cancelled.add(group._engine_future)
            self._cancelled |= group._engine_internal

    def _skip(self, future: GraphFuture) -> bool:
        """True if ``future`` was cancelled by a splice (its function is skipped)."""
        with self._lock:
            return future in self._cancelled

    # ------------------------------------------------------------ #
    # Introspection helpers
    # ------------------------------------------------------------ #
    def _locate(self, action: Action) -> tuple[_Group | None, int]:
        """
        Find the group containing ``action`` and the action's index in it.

        Returns ``(None, -1)`` when the action is the root (which is always
        a group, so this only happens for a malformed tree).
        """
        if action is self._root:
            return None, -1
        stack: list[_Group] = [self._root]
        while stack:
            group = stack.pop()
            for i, child in enumerate(group.children):
                if child is action:
                    return group, i
                if isinstance(child, (Sequential, Parallel)):
                    stack.append(child)
        return None, -1

    def _find_final_future(self, group: _Group) -> GraphFuture | None:
        """
        Return the future of the last action in ``group``'s execution order.

        Resolves the last child recursively: if it is an action, its future;
        if it is a group, recurse into it.  Returns ``None`` for an empty
        group.
        """
        children = group.children
        if not children:
            return None
        last = children[-1]
        if isinstance(last, Action):
            return last._engine_future
        return self._find_final_future(last)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def run_workflow(
    xml_source: str | bytes,
    registry: FunctionRegistry | None = None,
    parameters: dict[str, Any] | None = None,
    history: RunHistory | None = None,
) -> Any:
    """
    Parse a workflow XML document and execute it; return the final result.

    ``xml_source`` is the workflow XML (see
    :func:`sequence_extensions.workflow.schema.parse_workflow`).  ``registry``
    is the function registry (defaults to ``DEFAULT_REGISTRY``).
    ``parameters`` are extra global parameters: they are merged over the
    XML's global parameters (``<VerificationWorkflow>`` wrapper elements),
    with ``parameters`` winning on a name clash.  The final result is the
    return value of the last action in the root group's execution order.

    ``history`` is OPT-IN execution recording (default ``None`` = record
    nothing, zero behavior change): pass a
    :class:`sequence_extensions.workflow.history.RunHistory` to capture
    per-action evidence — including actions spliced in at runtime by
    dynamic adaptation, in true completion order — which can then be
    replayed deterministically with
    :func:`sequence_extensions.workflow.history.replay`.

    Raises ``ValueError`` for invalid XML, an unknown function name (naming
    the function), or an out-of-scope dynamic-adaptation splice attempt.
    """
    root = parse_workflow(xml_source)
    engine = _Engine(
        root,
        registry if registry is not None else DEFAULT_REGISTRY,
        parameters,
        history,
    )
    return engine.run()


def Test_Framework(
    seq: _Group,
    parameters: dict[str, Any] | None = None,
    registry: FunctionRegistry | None = None,
    history: RunHistory | None = None,
) -> Any:
    """
    Execute a workflow built via the Python API (the paper's Listing 10).

    ``seq`` is the root group (``Sequential`` / ``Parallel``); ``parameters``
    are global parameters passed to every function (an action's own
    parameters win); ``registry`` is the function registry (defaults to
    ``DEFAULT_REGISTRY``).  Returns the final result: the return value of
    the last action in the root group's execution order.

    ``history`` is OPT-IN execution recording (default ``None`` = record
    nothing, zero behavior change); see :func:`run_workflow`.

    The paper's call form ``Test_Framework(parameters=common_parameters,
    seq=top_seq)`` executes the workflow and returns its final result.
    """
    engine = _Engine(
        seq,
        registry if registry is not None else DEFAULT_REGISTRY,
        parameters,
        history,
    )
    return engine.run()
