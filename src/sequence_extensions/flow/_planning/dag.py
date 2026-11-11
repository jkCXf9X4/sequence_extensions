"""The plan pass: pre-execution DAG discovery.

``plan`` runs a composite body with a construct-only ``_PlanPool`` (records
edges, never schedules) and returns a :class:`FlowPlan` — the same graph a
real run would execute, nothing run, no run log written.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from sequence_extensions.graph.graph_future import GraphFuture, GraphPool, is_dependency

from .._config.context import (
    RunContext,
    current_run,
    execution_scope,
    in_process_worker,
)
from .._config.options import RunOptions, _signature_parameters
from .._execution.node import NodeFunction


# ---------------------------------------------------------------- #
# Plan pass (pre-execution DAG discovery)
# ---------------------------------------------------------------- #
class _PlanPool(GraphPool):
    """A GraphPool that records the graph but never executes any node.

    The root body runs on the driver during ``plan()``; every ``submit`` /
    ``gather`` inside it builds a ``FlowFuture`` and binds its edges, but
    ``_submit_node`` is a no-op, so no worker thread is ever scheduled and
    no node body executes.  The discovered DAG is what a real run would
    execute — same edges, same fan-out width, nothing run.
    """

    process_workers = False

    def __init__(self):
        super().__init__(max_workers=None)

    def _ensure_executor(self):
        # Never create a thread pool: plan mode schedules nothing.
        return

    def _submit_node(self, node):
        # Record the node as bound but do not schedule it.  Edges are already
        # captured at ``GraphFuture`` construction, so the DAG is complete
        # without running anything.
        with self._bind_lock:
            if node.future.done():
                return
        self._nodes.append(node)


@dataclass(frozen=True)
class FlowParameter:
    """One root-node parameter: what a user may set before the run.

    ``name`` is the parameter name, ``annotation`` its declared type (as a
    string, or ``""`` when unannotated), ``required`` is True when the
    parameter has no default, and ``default`` is the default value (``None``
    when absent).
    """

    name: str
    annotation: str
    required: bool
    default: Any | None = None


@dataclass(frozen=True)
class FlowNodeInfo:
    """Per-node parameter surface: policy knobs plus plain argument values.

    ``policy`` is the resolved ``(retries, retry_delay_seconds, timeout)``
    for this node (decorator keyword, overridden by ``RunOptions`` node
    defaults).  ``arguments`` lists the non-future argument values this node
    was submitted with, as ``(name, value)`` pairs — the data a user's root
    parameters flow into, in submit order.  Dependency edges are not listed
    here; they are in :attr:`FlowPlan.edges`.
    """

    name: str
    policy: tuple[int, float, float | None] = (0, 0.0, None)
    arguments: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class FlowPlan:
    """The pre-execution dependency graph of a run, without running it.

    ``nodes`` lists every submitted/gathered node in bind order (leaves
    first); each entry is ``(name, path)``.  ``edges`` lists the dependency
    edges as ``(dependent_index, dependency_index)`` indices into ``nodes``,
    so fan-out (one dependency feeding several nodes) and fan-in (gather)
    are both explicit.  ``root`` is the name of the node the run would
    execute.

    ``parameters`` lists the root node's callable parameters (the user-facing
    inputs of the whole flow); ``node_info`` gives each node's policy knobs
    and plain argument values, one entry per ``nodes`` occurrence.
    """

    root: str
    nodes: tuple[tuple[str, tuple, int], ...]  # (name, path, instance) per occurrence
    edges: tuple[tuple[int, int], ...]  # (dependent, dependency) node indices
    parameters: tuple[FlowParameter, ...] = ()
    node_info: tuple[FlowNodeInfo, ...] = ()

    def names(self):
        """Node names in bind order, one per occurrence (fan-out repeats)."""
        return tuple(name for name, _path, _inst in self.nodes)


def _plan_entry_guards(node, options):
    """The shared plan-pass guards; returns the resolved options."""
    if not isinstance(node, NodeFunction):
        raise TypeError(f"plan() expects a @node function, got {node!r}")
    if options is None:
        options = RunOptions()
    if not isinstance(options, RunOptions):
        raise TypeError(f"options must be RunOptions or None, got {options!r}")
    if in_process_worker():
        raise RuntimeError("plan() inside a process worker is not supported")
    if current_run() is not None:
        raise RuntimeError("plan() is a top-level entry point")
    return options.resolve(node.name)


def _in_plan_scope(node, args, kwargs, resolved, build):
    """Run the root body under a construct-only pool; ``build(result)`` inside the scope.

    The build runs inside the execution scope so policy resolution
    (``_effective_policy``) sees the plan's ``RunOptions`` node defaults.
    """
    pool = _PlanPool()
    ctx = RunContext(
        run_id=f"{resolved.name}-plan",
        node_name=resolved.name,
        runlog=None,
        pool=pool,
        options=resolved,
    )
    with execution_scope(
        ctx=ctx,
        path=(),
        attempt=None,
        token=None,
        run_token=None,
        worker=False,
        process_worker=False,
        in_body=True,
    ):
        result = node.fn(*args, **kwargs)
        return build(result)


def plan(node: NodeFunction, *args, options: RunOptions | None = None, **kwargs) -> FlowPlan:
    """Discover the DAG ``node`` would execute, without running any node.

    The root body runs once (its plain logic executes — e.g. a
    ``sorted(...)`` fan-out source — so the fan-out width is concrete), while
    every ``submit`` / ``gather`` inside it builds and binds its edges but is
    never scheduled.  The result is a :class:`FlowPlan`: the same graph a real
    run would execute, with nothing run and no run log written.  The plan
    also exposes the user-facing parameter surface — the root node's callable
    parameters (:attr:`FlowPlan.parameters`) and each node's policy knobs and
    plain argument values (:attr:`FlowPlan.node_info`).
    """
    resolved = _plan_entry_guards(node, options)
    return _in_plan_scope(
        node,
        args,
        kwargs,
        resolved,
        lambda result: _build_plan(node, result, parameters=_root_parameters(node.fn)),
    )


def _root_parameters(root_fn) -> tuple[FlowParameter, ...]:
    """The root node's callable parameters — the flow's user-facing inputs."""
    try:
        sig = inspect.signature(root_fn)
    except (TypeError, ValueError):
        return ()
    params = []
    for name, p, ann in _signature_parameters(sig):
        has_default = p.default is not inspect.Parameter.empty
        params.append(
            FlowParameter(
                name=name,
                annotation=ann,
                required=not has_default,
                default=None if not has_default else p.default,
            )
        )
    return tuple(params)


def _node_function(gf) -> NodeFunction | None:
    """Recover the ``NodeFunction`` behind a submitted ``FlowFuture``.

    ``submit()`` wraps the node in a ``_runner`` closure that captures the
    ``NodeFunction`` as ``self``; a ``gather`` node's ``_collect_structural``
    has no node behind it and returns ``None``.
    """
    fn = gf.function
    for cell in getattr(fn, "__closure__", None) or ():
        if isinstance(cell.cell_contents, NodeFunction):
            return cell.cell_contents
    return None


def _argument_name_map(nf: NodeFunction) -> dict[int, str]:
    """Positional index -> parameter name for a node's plain arguments."""
    try:
        sig = inspect.signature(nf.fn)
    except (TypeError, ValueError):
        return {}
    names = {}
    position = 0
    for name, p in sig.parameters.items():
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            names[position] = name
            position += 1
    return names


def _plain_arguments(gf, nf: NodeFunction) -> tuple[tuple[str, Any], ...]:
    """The non-future arguments a node was submitted with, named and ordered."""
    names = _argument_name_map(nf)
    out = []
    for key in sorted(gf.arguments):
        value = gf.arguments[key]
        if is_dependency(value):
            continue
        name = names.get(key, str(key)) if isinstance(key, int) else str(key)
        out.append((name, value))
    return tuple(out)


def _build_plan(
    node: NodeFunction,
    result,
    *,
    parameters: tuple[FlowParameter, ...],
) -> FlowPlan:
    """Collect the DAG reachable from the root body's returned future.

    Runs inside ``plan``'s execution scope so ``_effective_policy`` resolves
    against the plan's ``RunOptions`` node defaults.
    """
    if not isinstance(result, GraphFuture):
        return FlowPlan(root=node.name, nodes=(), edges=(), parameters=parameters)

    nodes: list[GraphFuture] = []
    index: dict[int, int] = {}
    visited: set[int] = set()

    def visit(gf) -> None:
        gid = id(gf)
        if gid in visited:
            return
        visited.add(gid)
        for dep in gf.dependencies:
            if isinstance(dep, GraphFuture):
                visit(dep)
        index[gid] = len(nodes)
        nodes.append(gf)

    visit(result)

    edges = []
    for i, gf in enumerate(nodes):
        for dep in gf.dependencies:
            if isinstance(dep, GraphFuture) and id(dep) in index:
                edges.append((i, index[id(dep)]))

    counts: dict[str, int] = {}
    entries = []
    info = []
    for gf in nodes:
        name = gf.name
        counts[name] = counts.get(name, 0) + 1
        path = getattr(gf, "path", ()) or (name,)
        entries.append((name, tuple(path), counts[name]))
        nf = _node_function(gf)
        if nf is None:
            info.append(FlowNodeInfo(name=name))
        else:
            retries, delay, timeout = nf._effective_policy()
            info.append(
                FlowNodeInfo(
                    name=name,
                    policy=(int(retries), float(delay), timeout),
                    arguments=_plain_arguments(gf, nf),
                )
            )
    return FlowPlan(
        root=node.name,
        nodes=tuple(entries),
        edges=tuple(edges),
        parameters=parameters,
        node_info=tuple(info),
    )
