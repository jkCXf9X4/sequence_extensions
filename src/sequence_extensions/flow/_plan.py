"""The plan pass: pre-execution DAG discovery and the one-schema document.

``plan`` runs a composite body with a construct-only ``_PlanPool`` (records
edges, never schedules) and returns a :class:`FlowPlan` — the same graph a
real run would execute, nothing run, no run log written.

``plan_document`` is the JSON interface (``IMP-023``): ONE schema serves the
plan document (UC-A), the manifest — a projection minus values (UC-B), the
override — the same document with values set (UC-C), re-plan and compare
(UC-D), and the diff (UC-E).  Values stay raw Python in the document (Path
objects etc.); serialization is the caller's job via the exported
``jsonable``, so ``parameters_from_document`` can inject real values back
into a run.
"""

from __future__ import annotations

import copy
import inspect
from dataclasses import dataclass
from typing import Any

from sequence_extensions.flow._context import (
    RunContext,
    current_run,
    execution_scope,
    in_process_worker,
)
from sequence_extensions.flow._options import RunOptions, fill_parameters
from sequence_extensions.flow.node import NodeFunction
from sequence_extensions.graph.graph_future import GraphFuture, GraphPool, _is_dependency

#: The document schema marker: every artifact (plan document, manifest,
#: override, diff input) of the plan JSON interface shares this one schema.
PLAN_SCHEMA = "flow-plan/1"


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
    for name, p in sig.parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        annotation = p.annotation
        ann = (
            getattr(annotation, "__name__", str(annotation))
            if annotation is not inspect.Parameter.empty
            else ""
        )
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
        if _is_dependency(value):
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


# ---------------------------------------------------------------- #
# The one-schema document (IMP-023): plan, manifest, override, diff
# ---------------------------------------------------------------- #
def _order_nodes(result) -> list[GraphFuture]:
    """Post-order walk of the graph reachable from ``result`` (leaves first)."""
    nodes: list[GraphFuture] = []
    visited: set[int] = set()

    def visit(gf) -> None:
        gid = id(gf)
        if gid in visited:
            return
        visited.add(gid)
        for dep in gf.dependencies:
            if isinstance(dep, GraphFuture):
                visit(dep)
        nodes.append(gf)

    visit(result)
    return nodes


def _root_parameter_values(node, args, kwargs) -> list[dict]:
    """The root callable's parameters with their bound values (defaults filled)."""
    try:
        sig = inspect.signature(node.fn)
    except (TypeError, ValueError):
        return []
    bound = sig.bind(*args, **kwargs)
    bound.apply_defaults()
    out = []
    for name, p in sig.parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        has_default = p.default is not inspect.Parameter.empty
        annotation = p.annotation
        ann = (
            getattr(annotation, "__name__", str(annotation))
            if annotation is not inspect.Parameter.empty
            else ""
        )
        out.append(
            {
                "name": name,
                "type": ann,
                "required": not has_default,
                "default": None if not has_default else p.default,
                "value": bound.arguments.get(name),
            }
        )
    return out


def _node_parameters(gf, nf: NodeFunction) -> list[dict]:
    """A node's settable parameters: its signature minus dependency edges.

    A parameter whose submitted value is a future is an edge, not a settable
    parameter.  ``value`` is the submitted plain value when code passed one,
    else the signature default (``None`` when required and not submitted).
    """
    try:
        sig = inspect.signature(nf.fn)
    except (TypeError, ValueError):
        return []
    names = _argument_name_map(nf)
    submitted = {}
    for key, value in gf.arguments.items():
        name = names.get(key) if isinstance(key, int) else key
        if name is None:
            continue
        submitted[name] = value
    out = []
    for name, p in sig.parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if name in submitted and _is_dependency(submitted[name]):
            continue
        has_default = p.default is not inspect.Parameter.empty
        annotation = p.annotation
        ann = (
            getattr(annotation, "__name__", str(annotation))
            if annotation is not inspect.Parameter.empty
            else ""
        )
        value = submitted[name] if name in submitted else (p.default if has_default else None)
        out.append(
            {
                "name": name,
                "type": ann,
                "required": not has_default,
                "default": None if not has_default else p.default,
                "value": value,
            }
        )
    return out


def _build_document(node, result, parameters: list[dict]) -> dict:
    """Assemble the flow-plan/1 document from the discovered DAG."""
    doc = {
        "schema": PLAN_SCHEMA,
        "root": node.name,
        "parameters": parameters,
        "nodes": [],
        "edges": [],
    }
    if not isinstance(result, GraphFuture):
        return doc

    nodes = _order_nodes(result)
    index = {id(gf): i for i, gf in enumerate(nodes)}
    counts: dict[str, int] = {}
    for i, gf in enumerate(nodes):
        name = gf.name
        counts[name] = counts.get(name, 0) + 1
        nf = _node_function(gf)
        if nf is None:
            kind = "gather"
            policy = {"retries": 0, "retry_delay_seconds": 0.0, "timeout": None}
            params = []
        else:
            kind = "node"
            retries, delay, timeout = nf._effective_policy()
            policy = {
                "retries": int(retries),
                "retry_delay_seconds": float(delay),
                "timeout": timeout,
            }
            params = _node_parameters(gf, nf)
        doc["nodes"].append(
            {
                "id": i,
                "name": name,
                "kind": kind,
                "path": list(getattr(gf, "path", ()) or (name,)),
                "instance": counts[name],
                "policy": policy,
                "params": params,
            }
        )
    doc["edges"] = [
        {"from": i, "to": index[id(dep)]}
        for i, gf in enumerate(nodes)
        for dep in gf.dependencies
        if isinstance(dep, GraphFuture) and id(dep) in index
    ]
    return doc


def plan_document(node: NodeFunction, *args, options: RunOptions | None = None, **kwargs) -> dict:
    """The one-schema JSON document of the DAG ``node`` would execute.

    Same guard and pass as :func:`plan`, but returns the flow-plan/1
    document: schema marker, root, root ``parameters`` with bound values,
    per-node ``nodes`` (id/name/kind/path/instance/policy/params), and
    ``edges`` as node-id pairs.  Overrides (``RunOptions.parameters``)
    reach the plan exactly as they reach a run (UC-D): the root body
    receives filled values and the document reports them.  Values stay raw
    Python; call ``jsonable`` to serialize.
    """
    resolved = _plan_entry_guards(node, options)
    args, kwargs = fill_parameters(node.name, node.fn, args, kwargs, resolved.parameters)
    return _in_plan_scope(
        node,
        args,
        kwargs,
        resolved,
        lambda result: _build_document(node, result, _root_parameter_values(node, args, kwargs)),
    )


def plan_manifest(document: dict) -> dict:
    """Projection: the same document with every ``value`` field stripped.

    Only ``parameters`` and ``nodes[].params[]`` lose their ``value`` field;
    schema, root, nodes, edges, and policy are unchanged.
    """
    manifest = copy.deepcopy(document)
    for p in manifest["parameters"]:
        p.pop("value", None)
    for entry in manifest["nodes"]:
        for p in entry["params"]:
            p.pop("value", None)
    return manifest


def apply_override(document: dict, override: dict) -> dict:
    """Merge ``override`` values into a deep copy of ``document``.

    ``override`` is a partial document: root parameters match by name; node
    overrides match by node name and apply to every occurrence of that name
    (UC-C).  An unknown node or parameter name raises ``ValueError`` before
    any execution.  The input document is not mutated.
    """
    result = copy.deepcopy(document)

    root_params = {p["name"]: p for p in result["parameters"]}
    for entry in override.get("parameters", ()):
        name = entry.get("name")
        if name is None or name not in root_params:
            raise ValueError(f"unknown root parameter {name!r} in override")
        root_params[name]["value"] = entry["value"]

    node_names = {entry["name"] for entry in result["nodes"]}
    for entry in override.get("nodes", ()):
        name = entry.get("name")
        if name is None or name not in node_names:
            raise ValueError(f"unknown node {name!r} in override")
        # One target per occurrence: a node override reaches every node of
        # that name (UC-C).
        params_by_name: dict[str, list[dict]] = {}
        for node_entry in result["nodes"]:
            if node_entry["name"] != name:
                continue
            for param in node_entry["params"]:
                params_by_name.setdefault(param["name"], []).append(param)
        for spec in entry.get("params", ()):
            param_name = spec.get("name")
            targets = params_by_name.get(param_name)
            if param_name is None or not targets:
                raise ValueError(f"unknown parameter {param_name!r} on node {name!r} in override")
            for target in targets:
                target["value"] = spec["value"]

    return result


def parameters_from_document(document: dict) -> dict:
    """The injection registry ``{node_name: {param: value}}`` for a document.

    Root parameters sit under ``document["root"]``; each node's parameters
    sit under its name.  When several occurrences of a node share a name,
    their parameter maps merge (a later occurrence wins).
    """
    registry = {document["root"]: {p["name"]: p["value"] for p in document["parameters"]}}
    for entry in document["nodes"]:
        reg = registry.setdefault(entry["name"], {})
        for p in entry["params"]:
            reg[p["name"]] = p["value"]
    return registry


def _node_key(entry: dict) -> tuple:
    """The stable node identity (name, path, instance) used by the diff."""
    return (entry["name"], tuple(entry["path"]), entry["instance"])


def _node_ref(entry: dict) -> dict:
    """A node identity as plain data, as it appears in diff records."""
    return {"name": entry["name"], "path": list(entry["path"]), "instance": entry["instance"]}


def diff_plans(a: dict, b: dict) -> dict:
    """Plain-data diff of two plan documents.

    ``changes`` lists records in deterministic order: root, root parameters,
    nodes (removed, added, then per-node policy and params), then edges.
    Identical documents give ``{"equal": True, "changes": []}``.
    """
    changes = []

    if a["root"] != b["root"]:
        changes.append({"kind": "root_changed", "old": a["root"], "new": b["root"]})

    a_params = {p["name"]: p for p in a["parameters"]}
    b_params = {p["name"]: p for p in b["parameters"]}
    for name, p in a_params.items():
        if name not in b_params:
            changes.append({"kind": "parameter_removed", "name": name, "value": p.get("value")})
    for name, p in b_params.items():
        if name not in a_params:
            changes.append({"kind": "parameter_added", "name": name, "value": p.get("value")})
    for name, pa in a_params.items():
        pb = b_params.get(name)
        if pb is None:
            continue
        for field in ("type", "required", "default", "value"):
            if pa.get(field) != pb.get(field):
                changes.append(
                    {
                        "kind": "parameter_changed",
                        "name": name,
                        "field": field,
                        "old": pa.get(field),
                        "new": pb.get(field),
                    }
                )

    a_nodes = {_node_key(e): e for e in a["nodes"]}
    b_nodes = {_node_key(e): e for e in b["nodes"]}
    for key, entry in a_nodes.items():
        if key not in b_nodes:
            changes.append({"kind": "node_removed", "node": _node_ref(entry)})
    for key, entry in b_nodes.items():
        if key not in a_nodes:
            changes.append({"kind": "node_added", "node": _node_ref(entry)})
    for key, ea in a_nodes.items():
        eb = b_nodes.get(key)
        if eb is None:
            continue
        if ea["policy"] != eb["policy"]:
            changes.append(
                {
                    "kind": "policy_changed",
                    "node": _node_ref(ea),
                    "old": ea["policy"],
                    "new": eb["policy"],
                }
            )
        a_p = {p["name"]: p for p in ea["params"]}
        b_p = {p["name"]: p for p in eb["params"]}
        for name, p in a_p.items():
            if name not in b_p:
                changes.append(
                    {
                        "kind": "param_removed",
                        "node": _node_ref(ea),
                        "name": name,
                        "value": p.get("value"),
                    }
                )
        for name, p in b_p.items():
            if name not in a_p:
                changes.append(
                    {
                        "kind": "param_added",
                        "node": _node_ref(ea),
                        "name": name,
                        "value": p.get("value"),
                    }
                )
        for name, pa in a_p.items():
            pb = b_p.get(name)
            if pb is None:
                continue
            for field in ("type", "required", "default", "value"):
                if pa.get(field) != pb.get(field):
                    changes.append(
                        {
                            "kind": "param_changed",
                            "node": _node_ref(ea),
                            "name": name,
                            "field": field,
                            "old": pa.get(field),
                            "new": pb.get(field),
                        }
                    )

    a_edges = {(e["from"], e["to"]) for e in a["edges"]}
    b_edges = {(e["from"], e["to"]) for e in b["edges"]}
    for edge in a["edges"]:
        key = (edge["from"], edge["to"])
        if key not in b_edges:
            changes.append({"kind": "edge_removed", "from": edge["from"], "to": edge["to"]})
    for edge in b["edges"]:
        key = (edge["from"], edge["to"])
        if key not in a_edges:
            changes.append({"kind": "edge_added", "from": edge["from"], "to": edge["to"]})

    return {"equal": not changes, "changes": changes}
