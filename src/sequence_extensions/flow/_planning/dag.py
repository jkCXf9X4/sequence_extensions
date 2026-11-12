"""The plan pass: pre-execution DAG discovery.

``plan_document`` runs a composite body with a construct-only ``_PlanPool``
(records edges, never schedules) and builds the ``flow-plan/2`` document —
the same graph a real run would execute, nothing run, no run log written.
"""

from __future__ import annotations

import inspect

from sequence_extensions.graph.graph_future import GraphPool

from .._config.context import (
    RunContext,
    current_run,
    execution_scope,
    in_process_worker,
)
from .._config.options import RunOptions
from .._execution.node import NodeFunction


# ---------------------------------------------------------------- #
# Plan pass (pre-execution DAG discovery)
# ---------------------------------------------------------------- #
class _PlanPool(GraphPool):
    """A GraphPool that records the graph but never executes any node.

    The root body runs on the driver during ``plan_document()``; every ``submit`` /
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


def _plan_entry_guards(node, options):
    """The shared plan-pass guards; returns the resolved options."""
    if not isinstance(node, NodeFunction):
        raise TypeError(f"plan_document() expects a @node function, got {node!r}")
    if options is None:
        options = RunOptions()
    if not isinstance(options, RunOptions):
        raise TypeError(f"options must be RunOptions or None, got {options!r}")
    if in_process_worker():
        raise RuntimeError("plan_document() inside a process worker is not supported")
    if current_run() is not None:
        raise RuntimeError("plan_document() is a top-level entry point")
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
