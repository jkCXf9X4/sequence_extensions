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
  next sibling — a group (the paper's Listing 5) or an action (the
  paper's Listing 7 inner case).  The replaced subtree is cancelled (its
  actions do not run).  A splice attempt that is out of scope, or from
  inside a ``Parallel`` parent, raises ``ValueError``.  A function may
  instead declare a ``dag`` parameter and receive a scoped
  :class:`~.adaptation.DAGHandle` (validated write ops, transactional
  commit at function return) — but not both (one mechanism per action).
* **At most once** — every action executes at most once; the engine never
  re-runs a function (no feedback loops).

The engine is a lazy tree-walking interpreter: it walks the live node tree
as it executes (re-reading each group's children every step, so runtime
splices are seen immediately) instead of pre-building a future graph.  Every
action still runs on a pool worker thread via a :class:`GraphFuture` leaf;
parallel groups wire all their action futures at once through a join node
and wait on it with a single ``pool.result`` call.

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

import concurrent.futures
import threading
import time
from typing import Any, Callable, Union

from ..graph import GraphFuture, GraphPool
from .adaptation import ADAPTATION_BOUND, AdaptationOp, DAGHandle
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
    of the action's NEXT SIBLING — a group (the paper's Listing 5) or an
    action (the paper's Listing 7 inner case: ``inner_action_1`` may alter
    ``inner_action_2``, which is an action).  The splice stays within the
    returning action's own grouping scope: an action may only alter what is
    downstream of it inside the group it belongs to, never siblings of that
    group.

    ``parent`` is the group containing the returning action, ``index`` is
    the action's position in ``parent.children``, and ``returned`` is the
    function's return value.

    Raises ``ValueError`` when the return value is a node (or list of nodes)
    but the action has no next sibling, or the parent is a ``Parallel``
    group (read-only parallel scopes: siblings may already be executing, so
    a splice there has no defined effect).  A plain (non-node) return value
    is always allowed.
    """
    nodes = _as_node_list(returned)
    if nodes is None:
        return
    if isinstance(parent, Parallel):
        raise ValueError(
            "dynamic adaptation: action returned workflow node(s) but runs "
            "inside a parallel scope, which is read-only; parallel siblings "
            "may already be executing, so the tree cannot be adapted here"
        )
    if parent is None or index + 1 >= len(parent.children):
        raise ValueError(
            "dynamic adaptation: action returned workflow node(s) but has no "
            "next sibling to splice them into; a splicing action must be "
            "followed by the group (or action) it adapts"
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
    Walk and run a workflow node tree on a :class:`GraphPool`.

    The engine is a lazy tree-walking interpreter: it does NOT pre-build a
    future graph.  Instead it walks the live tree — re-reading each group's
    ``children`` list every step, so nodes spliced in at runtime by dynamic
    adaptation are seen immediately — and executes each action on a pool
    worker thread through a :class:`GraphFuture` leaf.  A function that
    returns workflow node(s) has them spliced in place of the action's next
    sibling (a group); the replaced group is marked executed (its actions
    do not run), and the spliced group's results become the action's result.
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
        self._pool: GraphPool | None = None
        # Bounded adaptation (decision D5): the engine counts dynamic nodes
        # added by handle commits; exceeding the bound raises a
        # deterministic ValueError (a runaway adaptation terminates).
        self._dynamic_count = 0
        self._adaptation_bound = ADAPTATION_BOUND
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
            # Eager validation: every action's function name must resolve
            # BEFORE any execution starts (parity with the old build pass).
            self._validate_node(self._root)
            self._walk_group(self._root, [])
            # The tree may have been spliced during execution, so the final
            # action is resolved AFTER the run (the last child of the root,
            # resolved recursively into groups).
            final_action = self._final_action(self._root)
            if final_action is None:
                return None
            result = final_action._engine_result
            if self._history is not None:
                self._mark_final(final_action)
            return result

    # ------------------------------------------------------------ #
    # Pre-validation (eager unknown-function errors)
    # ------------------------------------------------------------ #
    def _validate_node(self, node: _Node) -> None:
        """Resolve every action's function name in ``node``'s subtree."""
        if isinstance(node, Action):
            self._registry.get(node.function)
            return
        for child in node.children:
            self._validate_node(child)

    # ------------------------------------------------------------ #
    # Tree walking (the lazy interpreter core)
    # ------------------------------------------------------------ #
    def _walk_group(self, group: _Group, pairs: list) -> tuple[Any, list]:
        """
        Walk ``group`` (sequential or parallel) seeded with ``pairs``.

        Returns ``(group result, direct pairs)`` where ``direct pairs`` are
        the ``(action, result)`` pairs of the group's DIRECT action children
        (one-level flattening, matching the old engine's fan-in chain: a
        group contributes its direct children's futures to the chain, and
        only action futures carry results into keyword arguments).
        """
        if isinstance(group, Sequential):
            return self._walk_sequential(group, pairs)
        return self._walk_parallel(group, pairs)

    def _walk_sequential(self, group: Sequential, pairs: list) -> tuple[Any, list]:
        """
        Walk a ``Sequential`` group: strict child order.

        The live ``children`` list is RE-READ every step (``while i < len``),
        so nodes spliced in at runtime are picked up immediately.  Each
        action contributes its own ``(action, result)`` pair to the local
        chain; a group child contributes its direct action children's pairs
        (one-level flattening).  Children already executed (replaced by a
        splice) are skipped without adding pairs.
        """
        chain: list = list(pairs)
        direct: list = []
        i = 0
        while i < len(group.children):
            child = group.children[i]
            if getattr(child, "_engine_executed", False):
                # Replaced by a runtime splice: its actions already ran (or
                # never will); it contributes neither a result nor a pair.
                i += 1
                continue
            if isinstance(child, Action):
                future = self._submit_action(child, chain)
                raw = self._pool.result(future)
                result = self._handle_result(child, group, i, raw, chain)
                chain.append((child, result))
                direct.append((child, result))
            else:
                _, child_direct = self._walk_group(child, chain)
                chain.extend(child_direct)
            i += 1
        return self._group_result(group), direct

    def _walk_parallel(self, group: Parallel, pairs: list) -> tuple[Any, list]:
        """
        Walk a ``Parallel`` group: independent, concurrent children.

        The children are SNAPSHOTTED once (a parallel group's children are
        independent, so the walk does not re-read the list).  ACTION children
        are submitted as :class:`GraphFuture` leaves on the pool; GROUP
        children run on plain ``threading.Thread``s (never on pool workers —
        a walk task occupying a worker could starve the pool and deadlock).
        All action futures are wired at once through a single join future
        (``pool.result`` on the join — the wire-then-wait pattern), the
        threads are joined, and the first exception in child order is raised
        after every child has settled.
        """
        children = list(group.children)
        upstream = list(pairs)
        submitted: list[tuple[int, Action, GraphFuture]] = []
        threads: list[tuple[int, threading.Thread, dict]] = []
        # Wire every action leaf FIRST (in child order, matching the old
        # engine's build order), then start the group-child threads: the
        # pool's FIFO then runs the actions in the same order the old
        # engine submitted them.
        for position, child in enumerate(children):
            if getattr(child, "_engine_executed", False):
                continue
            if isinstance(child, Action):
                submitted.append((position, child, self._submit_action(child, upstream)))
        if submitted:
            # Wire-then-wait: bind the whole graph (submitting every leaf)
            # with a zero-timeout probe that never blocks on a result.
            probe = GraphFuture(_join_results, *[f for _, _, f in submitted])
            try:
                self._pool.result(probe, timeout=0)
            except concurrent.futures.TimeoutError:
                pass
        for position, child in enumerate(children):
            if getattr(child, "_engine_executed", False) or isinstance(child, Action):
                continue
            holder: dict = {}
            thread = threading.Thread(
                target=self._walk_child_thread,
                args=(child, upstream, holder),
                daemon=True,
            )
            threads.append((position, thread, holder))
            thread.start()
        results: list[Any] = [None] * len(children)
        errors: list[tuple[int, BaseException]] = []
        if submitted:
            join = GraphFuture(_join_results, *[f for _, _, f in submitted])
            try:
                self._pool.result(join)
            except Exception:
                # The join only runs once every dependency has settled, so
                # the per-future result() calls below are non-blocking; the
                # first in-order failure is re-raised after all children
                # (threads included) have settled.
                pass
            for position, action, future in submitted:
                try:
                    raw = future.result()
                    results[position] = self._handle_result(
                        action, group, position, raw, upstream
                    )
                except Exception as exc:
                    errors.append((position, exc))
        for _, thread, _ in threads:
            thread.join()
        for position, _thread, holder in threads:
            if "error" in holder:
                errors.append((position, holder["error"]))
            else:
                results[position] = holder.get("result")
        for _, exc in sorted(errors, key=lambda item: item[0]):
            raise exc
        direct = [
            (child, child._engine_result)
            for child in children
            if isinstance(child, Action) and not getattr(child, "_engine_executed", False)
        ]
        return results, direct

    def _walk_child_thread(self, child: _Group, upstream: list, holder: dict) -> None:
        """Run a parallel group child on a plain thread; capture its outcome."""
        try:
            holder["result"], _ = self._walk_group(child, list(upstream))
        except BaseException as exc:  # re-raised in child order by the walker
            holder["error"] = exc

    def _walk_spliced(self, parent: _Group, nodes: list, upstream: list) -> list:
        """
        Walk nodes spliced in by dynamic adaptation (the nested walk).

        Mirrors the old engine's temporary ``Sequential(*nodes)`` group: the
        nodes are walked in order with a local chain seeded from the actor's
        upstream pairs (a group node contributes its direct action children's
        pairs to that chain), and the actor's runtime result is the ordered
        list of the nodes' results.  Nodes replaced by a NESTED splice are
        skipped (they were marked executed by the nested surgery).
        """
        chain: list = list(upstream)
        results: list = []
        for node in nodes:
            if getattr(node, "_engine_executed", False):
                results.append(None)
                continue
            position = self._position_of(parent, node)
            if position < 0:
                # No longer in the live tree (replaced by a nested splice).
                results.append(None)
                continue
            if isinstance(node, Action):
                future = self._submit_action(node, chain)
                raw = self._pool.result(future)
                result = self._handle_result(node, parent, position, raw, chain)
                chain.append((node, result))
                results.append(result)
            else:
                result, child_direct = self._walk_group(node, chain)
                chain.extend(child_direct)
                results.append(result)
        return results

    def _group_result(self, group: _Group) -> Any:
        """A sequential group's result: the ordered list of its children's results."""
        return [self._child_result(child) for child in group.children
                if not getattr(child, "_engine_executed", False)]

    def _child_result(self, child: _Node) -> Any:
        """A child's contribution to its group's result list (recursive)."""
        if isinstance(child, Action):
            return child._engine_result
        return self._group_result(child)

    def _position_of(self, parent: _Group, node: _Node) -> int:
        """The live index of ``node`` in ``parent.children`` (-1 if absent)."""
        for i, child in enumerate(parent.children):
            if child is node:
                return i
        return -1

    # ------------------------------------------------------------ #
    # Action execution (every action runs on a pool worker)
    # ------------------------------------------------------------ #
    def _submit_action(self, action: Action, upstream: list) -> GraphFuture:
        """
        Submit one action's function call as a :class:`GraphFuture` leaf.

        The upstream pairs are passed as positional arguments so the future
        registers them as dependencies (strict ordering); the corresponding
        actions are passed separately for result keying.  The function call
        itself runs on a pool worker thread.
        """
        fn = self._registry.get(action.function)
        params = normalize_params(action.params)
        actions = [act for act, _ in upstream]
        return GraphFuture(
            self._run_action,
            *[result for _, result in upstream],
            fn=fn,
            params=params,
            actions=actions,
            action=action,
        )

    def _handle_result(
        self,
        action: Action,
        parent: _Group,
        index: int,
        raw: Any,
        upstream: list,
    ) -> Any:
        """
        Settle an action's raw result on the WALKER thread.

        A plain result is stored and returned.  A node-list result is a
        dynamic-adaptation splice: the scope is checked, the replaced group
        is marked executed, the returned nodes are spliced into the live
        tree and walked (nested sequential walk seeded with the actor's
        upstream pairs), and the actor's runtime result becomes the ordered
        list of the spliced nodes' results.  Splice handling runs on the
        walker thread (never inside a pool worker) so a nested walk can
        submit to the pool without starving it.
        """
        nodes = _as_node_list(raw)
        if nodes is None:
            action._engine_result = raw
            return raw
        check_splice_scope(parent, index, raw)
        next_sibling = parent.children[index + 1]
        next_sibling._engine_executed = True
        with self._lock:
            parent.children[index + 1 : index + 2] = nodes
        for node in nodes:
            _mark_dynamic(node)
        # Eager validation of the spliced nodes (parity with the old
        # engine's upfront build pass: unknown functions raise before the
        # spliced actions execute).
        for node in nodes:
            self._validate_node(node)
        results = self._walk_spliced(parent, nodes, list(upstream))
        for node in nodes:
            node._engine_executed = True
        action._engine_result = results
        return results

    def _run_action(
        self,
        *upstream_results: Any,
        fn: Callable[..., Any],
        params: dict[str, Any],
        actions: list[Action | None],
        action: Action,
    ) -> Any:
        """
        Execute one action's function (runs on a pool worker thread).

        The call kwargs are, in precedence order (own parameters win): the
        action's own parameters, the upstream results (keyed by the
        producing action's function name, with collision suffixes), and the
        global parameters.  The raw return value is passed back to the
        walker thread, which handles any returned-node splice.

        When the function's signature declares a ``dag`` parameter (the
        registry's cached ``wants_dag`` flag), a scoped
        :class:`~.adaptation.DAGHandle` is injected for the call and its op
        log is committed at function return — on this same thread, under
        one engine-lock acquisition (the commit protocol, plan section 4).
        ``dag`` is a reserved kwarg name: the injected handle wins over any
        same-named parameter.  A function that declares ``dag`` AND returns
        workflow node(s) raises ``ValueError`` (one adaptation mechanism
        per action).
        """
        kwargs: dict[str, Any] = dict(self._globals)
        used: dict[str, int] = {}
        for result, act in zip(upstream_results, actions):
            if act is None:
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
        handle = self._make_handle(action)
        if handle is not None:
            # Reserved kwarg name: the injected handle wins over any
            # same-named parameter (globals, upstream results, own params).
            kwargs["dag"] = handle
        if self._history is None:
            result = fn(**kwargs)
        else:
            result = self._record_call(action, fn, kwargs)
            if handle is not None:
                # Snapshot of the acting action's sibling list + index,
                # recorded at injection (plan section 9; replay
                # materializes a fake tree from it — Phase 6).
                record = getattr(action, "_engine_record", None)
                if record is not None:
                    record.scope = {
                        "index": handle.index,
                        "siblings": [
                            _describe_sibling(child) for child in handle.scope.children
                        ],
                    }
        if handle is not None:
            if _as_node_list(result) is not None:
                raise ValueError(
                    "dynamic adaptation: a function that declares a 'dag' "
                    "parameter must not also return workflow node(s); use "
                    "either the handle or the return-nodes protocol, not both"
                )
            self._commit(handle, action)
        return result

    # ------------------------------------------------------------ #
    # Dynamic adaptation: handle injection and the commit protocol
    # ------------------------------------------------------------ #
    def _make_handle(self, action: Action) -> DAGHandle | None:
        """
        Build the scoped handle for ``action``'s call, or ``None``.

        Returns ``None`` when the action's function does not declare a
        ``dag`` parameter (the registry's cached flag) or when the action's
        parent is not known (a detached node).  Children of a ``Parallel``
        scope get a READ-ONLY handle (finding F4): every write op raises.
        """
        if not self._registry.adapts(action.function):
            return None
        parent, index = self._locate_action(action)
        if parent is None:
            return None
        return DAGHandle(
            parent,
            index,
            read_only=isinstance(parent, Parallel),
            bound=self._adaptation_bound - self._dynamic_count,
        )

    def _locate_action(self, action: Action) -> tuple[_Group | None, int]:
        """Return ``(parent, index)`` of ``action`` in the live tree."""
        with self._lock:
            return self._find_in_tree(self._root, action)

    def _find_in_tree(
        self, group: _Group, action: Action
    ) -> tuple[_Group | None, int]:
        """Depth-first search for ``action``; returns its parent and index."""
        for index, child in enumerate(group.children):
            if child is action:
                return group, index
            if isinstance(child, (Sequential, Parallel)):
                found = self._find_in_tree(child, action)
                if found[0] is not None:
                    return found
        return None, -1

    def _commit(self, handle: DAGHandle, action: Action) -> None:
        """
        Apply a handle's recorded ops (the commit protocol, plan section 4).

        Runs at function return, on the same thread the function ran on,
        under ONE engine-lock acquisition: re-validate every op against the
        live tree, apply the tree surgery (children-list edits, in-place
        ``params.update`` for adjust, appends at the scope end), check the
        dynamic-node bound, record the ``adaptations`` on the action's
        ``ExecutionRecord`` and mark the inserted nodes dynamic.  An empty
        op log is a no-op.  Re-validation failures raise before any op is
        applied (the ops of one commit are atomic).
        """
        ops = handle.ops
        if not ops:
            return
        with self._lock:
            for op in ops:
                self._revalidate(op)
            for op in ops:
                self._apply(op)
            self._dynamic_count += sum(len(op.nodes) for op in ops)
            if self._dynamic_count > self._adaptation_bound:
                raise ValueError(
                    f"dynamic adaptation: the dynamic-node bound "
                    f"({self._adaptation_bound}) was exceeded; a runaway "
                    f"adaptation is terminated deterministically instead "
                    f"of hanging"
                )
            for node in (n for op in ops for n in op.nodes):
                _mark_dynamic(node)
        # Eager validation of the inserted nodes (parity with the
        # return-nodes splice path: an unknown function raises before the
        # inserted actions execute).
        for op in ops:
            for node in op.nodes:
                self._validate_node(node)
        record = getattr(action, "_engine_record", None)
        if record is not None:
            record.adaptations = [op.describe() for op in ops]

    def _revalidate(self, op: AdaptationOp) -> None:
        """
        Re-check one op against the live tree (under the engine lock).

        The op's target must still be in the tree and must not have started
        (``_engine_executed``).  The parallel-scope rule (finding F4) is
        enforced on the ACTOR side — a child of a ``Parallel`` scope gets a
        read-only handle, so no ops can exist for it — not on the target
        side: an action in a sequential scope may adapt the subtree of a
        FOLLOWING parallel group, because every position after the actor
        is unwalked while its function runs (the paper's Listing 7 outer
        case).
        """
        if op.kind == "append":
            return
        parent, _index = self._find_in_tree(self._root, op.target)
        if parent is None:
            raise ValueError(
                "dynamic adaptation: the op's target is no longer in the "
                "workflow tree; the tree changed after the op was recorded"
            )
        if getattr(op.target, "_engine_executed", False):
            raise ValueError(
                "dynamic adaptation: the op's target has already executed; "
                "only nodes that have not started may be adapted"
            )

    def _apply(self, op: AdaptationOp) -> None:
        """Apply one op's tree surgery (under the engine lock)."""
        if op.kind == "append":
            group = op.scope if op.scope is not None else self._root
            group.children.extend(op.nodes)
            return
        if op.kind == "adjust":
            _apply_params(op.target, op.params)
            return
        if op.kind == "replace":
            parent, index = self._find_in_tree(self._root, op.target)
            parent.children[index : index + 1] = list(op.nodes)
            return
        raise ValueError(f"dynamic adaptation: unknown op kind {op.kind!r}")

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

    def _mark_final(self, final_action: Action) -> None:
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
        record = getattr(final_action, "_engine_record", None)
        if record is not None:
            self._history.final_order = record.order

    # ------------------------------------------------------------ #
    # Final-result resolution
    # ------------------------------------------------------------ #
    def _final_action(self, group: _Group) -> Action | None:
        """
        Return the last action in ``group``'s execution order.

        Resolves the last child recursively: if it is an action, it is the
        final action; if it is a group, recurse into it.  Returns ``None``
        for an empty group (the run's result is then ``None``).
        """
        children = group.children
        if not children:
            return None
        last = children[-1]
        if isinstance(last, Action):
            return last
        return self._final_action(last)


def _join_results(*_results: Any) -> None:
    """A join node: it runs once every dependency has settled (value unused)."""
    return None


def _apply_params(target: _Node, params: dict[str, Any]) -> None:
    """
    Apply an ``adjust`` op's parameter overrides to ``target`` in place.

    An ``Action`` gets its ``params`` dict updated (existing keys
    overwritten, missing keys added); a group applies the overrides to
    every action in its subtree (the "retune the declared downstream scope"
    form).
    """
    if isinstance(target, Action):
        target.params.update(params)
        return
    for child in target.children:
        _apply_params(child, params)


def _describe_sibling(node: _Node) -> dict[str, Any]:
    """A plain descriptor of a scope snapshot's sibling (for history)."""
    if isinstance(node, Action):
        return {"kind": "action", "function": node.function}
    kind = "sequential" if isinstance(node, Sequential) else "parallel"
    return {"kind": kind, "children": len(node.children)}


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
