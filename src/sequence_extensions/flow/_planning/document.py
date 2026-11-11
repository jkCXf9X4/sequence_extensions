"""The one-schema plan document (IMP-023): plan, manifest, override, diff.

ONE schema serves the plan document (UC-A), the manifest — a projection
minus values (UC-B), the override — the same document with values set
(UC-C), re-plan and compare (UC-D), and the diff (UC-E).  Values stay raw
Python in the document (Path objects etc.); serialization is the caller's
job via the exported ``jsonable``, so ``parameters_from_document`` can
inject real values back into a run.
"""

from __future__ import annotations

import copy
import inspect

from sequence_extensions.graph.graph_future import GraphFuture, is_dependency

from .._config.options import RunOptions, _signature_parameters, fill_parameters
from .._execution.node import NodeFunction
from .dag import (
    _argument_name_map,
    _in_plan_scope,
    _node_function,
    _plan_entry_guards,
)

#: The document schema marker: every artifact (plan document, manifest,
#: override, diff input) of the plan JSON interface shares this one schema.
PLAN_SCHEMA = "flow-plan/1"


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
    for name, p, ann in _signature_parameters(sig):
        has_default = p.default is not inspect.Parameter.empty
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
    for name, p, ann in _signature_parameters(sig):
        if name in submitted and is_dependency(submitted[name]):
            continue
        has_default = p.default is not inspect.Parameter.empty
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
