"""The one-schema plan document (IMP-023): plan, manifest, override, diff, run.

ONE schema serves the plan document (UC-A), the manifest — a projection
minus values (UC-B), the override — the same document with values set
(UC-C), re-plan and compare (UC-D), and the diff (UC-E).  Values stay raw
Python in the document (Path objects etc.); serialization is the caller's
job via the exported ``jsonable``, so ``execute_plan`` can decode real
values back into a run.
"""

from __future__ import annotations

import copy
import inspect
from pathlib import Path

from sequence_extensions.graph.graph_future import GraphFuture, is_dependency

from .._config.context import current_run
from .._config.options import (
    UNSET,
    NodeIdentity,
    NodePolicy,
    RunOptions,
    _signature_parameters,
    bind_flow_inputs,
    fill_parameters,
)
from .._execution.node import NodeFunction
from .._execution.run import Run, execute_flow
from .dag import (
    _argument_name_map,
    _in_plan_scope,
    _node_function,
    _plan_entry_guards,
)

#: The document schema marker: every artifact (plan document, manifest,
#: override, diff input) of the plan JSON interface shares this one schema.
PLAN_SCHEMA = "flow-plan/2"

#: The option fields a plan document carries; runtime-only options (``log``,
#: ``name``, ``pool``, ``node_defaults``, ``parameters``) stay in code.
_DOCUMENT_OPTION_FIELDS = (
    "max_workers",
    "summary",
    "fixed_clock",
    "retries",
    "retry_delay_seconds",
    "timeout",
)

#: The per-node policy fields a plan document carries.
_POLICY_FIELDS = ("retries", "retry_delay_seconds", "timeout")


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


def _options_document(resolved: RunOptions) -> dict:
    """The six document-visible option fields, concrete."""
    return {name: getattr(resolved, name) for name in _DOCUMENT_OPTION_FIELDS}


def _default_document_options() -> dict:
    """Concrete built-in defaults for the document's ``options`` block."""
    return _options_document(RunOptions().resolve("flow"))


def _submission_identities() -> tuple[dict[int, NodeIdentity], dict[tuple[str, tuple], int]]:
    """Map each submitted future to its identity, and count submissions per key.

    ``ctx.nodes`` is submission order, so instance numbers follow the order
    the root body submitted nodes — the same order a real run uses, not the
    post-order the document is written in.
    """
    ctx = current_run()
    submitted = list(ctx.nodes) if ctx is not None else []
    counts: dict[tuple[str, tuple], int] = {}
    by_id: dict[int, NodeIdentity] = {}
    for gf in submitted:
        name = gf.name
        path = tuple(getattr(gf, "path", ()) or (name,))
        key = (name, path)
        instance = counts.get(key, 0) + 1
        counts[key] = instance
        by_id[id(gf)] = NodeIdentity(name, path, instance)
    return by_id, counts


def _build_document(node, result, parameters: list[dict], options: RunOptions) -> dict:
    """Assemble the flow-plan/2 document from the discovered DAG."""
    doc = {
        "schema": PLAN_SCHEMA,
        "parameters": parameters,
        "nodes": [],
        "edges": [],
        "options": _options_document(options),
    }
    if not isinstance(result, GraphFuture):
        return doc

    nodes = _order_nodes(result)
    index = {id(gf): i for i, gf in enumerate(nodes)}
    submitted, submitted_counts = _submission_identities()
    fallback_counts: dict[tuple[str, tuple], int] = {}
    for i, gf in enumerate(nodes):
        identity = submitted.get(id(gf))
        if identity is None:
            # A gather future is built directly, not via submit(), so it is
            # absent from ctx.nodes.  Number it after every submitted node
            # sharing its key: deterministic and collision-free.
            path = tuple(getattr(gf, "path", ()) or (gf.name,))
            key = (gf.name, path)
            fallback_counts[key] = fallback_counts.get(key, submitted_counts.get(key, 0)) + 1
            identity = NodeIdentity(gf.name, path, fallback_counts[key])
        nf = _node_function(gf)
        if nf is None:
            kind = "gather"
            policy = {"retries": 0, "retry_delay_seconds": 0.0, "timeout": None}
            params = []
        else:
            kind = "node"
            retries, delay, timeout = nf._effective_policy(identity)
            policy = {
                "retries": int(retries),
                "retry_delay_seconds": float(delay),
                "timeout": timeout,
            }
            params = _node_parameters(gf, nf)
        doc["nodes"].append(
            {
                "id": i,
                "name": identity.name,
                "kind": kind,
                "path": list(identity.path),
                "instance": identity.instance,
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
    """The flow-plan/2 JSON document of the DAG ``node`` would execute.

    Same guard and pass as the plan document interface: schema marker, root
    ``parameters`` with bound values, per-node ``nodes`` (id/name/kind/path/
    instance/policy/params), ``edges`` as node-id pairs, and concrete
    ``options``.  Overrides (``RunOptions.parameters``) reach the plan exactly
    as they reach a run (UC-D): the root body receives filled values and the
    document reports them.  Values stay raw Python; call ``jsonable`` to
    serialize.
    """
    resolved = _plan_entry_guards(node, options)
    args, kwargs = fill_parameters(node.name, node.fn, args, kwargs, resolved.parameters)
    return _in_plan_scope(
        node,
        args,
        kwargs,
        resolved,
        lambda result: _build_document(
            node, result, _root_parameter_values(node, args, kwargs), resolved
        ),
    )


def plan_manifest(document: dict) -> dict:
    """Projection: the same document with every ``value`` field stripped.

    Only ``parameters`` and ``nodes[].params[]`` lose their ``value`` field;
    schema, nodes, edges, options, and policy are unchanged.
    """
    manifest = copy.deepcopy(document)
    for p in manifest["parameters"]:
        p.pop("value", None)
    for entry in manifest["nodes"]:
        for p in entry["params"]:
            p.pop("value", None)
    return manifest


def _select_override_nodes(nodes: list[dict], entry: dict, name: str) -> list[dict]:
    """Select the document nodes one override entry targets.

    ``path`` and ``instance`` together target one occurrence; both absent
    keeps the legacy name-wide behavior.  Exactly one of them is an error.
    """
    has_path = "path" in entry
    has_instance = "instance" in entry
    if has_path != has_instance:
        raise ValueError(
            f"node override for {name!r} must provide both 'path' and 'instance' or neither"
        )
    if not has_path:
        return [node_entry for node_entry in nodes if node_entry["name"] == name]

    path = entry["path"]
    if not isinstance(path, (list, tuple)) or not all(isinstance(part, str) for part in path):
        raise ValueError(f"path for node {name!r} must be a list or tuple of strings")
    instance = entry["instance"]
    if isinstance(instance, bool) or not isinstance(instance, int) or instance <= 0:
        raise ValueError(f"instance for node {name!r} must be a positive integer")

    selected = [
        node_entry
        for node_entry in nodes
        if node_entry["name"] == name
        and tuple(node_entry["path"]) == tuple(path)
        and node_entry["instance"] == instance
    ]
    if not selected:
        raise ValueError(
            f"unknown node identity (name={name!r}, path={list(path)!r}, "
            f"instance={instance}) in override"
        )
    return selected


def apply_override(document: dict, override: dict) -> dict:
    """Merge ``override`` values into a deep copy of ``document``.

    ``override`` is a partial document: root parameters match by name; a node
    entry matches its ``name`` and, when it also carries ``path`` and
    ``instance``, one occurrence identified by that canonical identity.
    Omitting both keeps the legacy name-wide behavior (every occurrence);
    providing only one is an error.  ``options`` is a partial merge.  An
    unknown root param, node, node identity, node param, policy key, or
    option key raises ``ValueError`` before any execution.  The input
    document is not mutated.
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
        selected = _select_override_nodes(result["nodes"], entry, name)
        params_by_name: dict[str, list[dict]] = {}
        for node_entry in selected:
            for param in node_entry["params"]:
                params_by_name.setdefault(param["name"], []).append(param)
        for spec in entry.get("params", ()):
            param_name = spec.get("name")
            targets = params_by_name.get(param_name)
            if param_name is None or not targets:
                raise ValueError(f"unknown parameter {param_name!r} on node {name!r} in override")
            for target in targets:
                target["value"] = spec["value"]

        if "policy" in entry:
            policy_override = entry["policy"]
            if not isinstance(policy_override, dict):
                raise ValueError(f"policy override for node {name!r} must be a dict")
            unknown = set(policy_override) - set(_POLICY_FIELDS)
            if unknown:
                raise ValueError(
                    f"unknown policy key(s) {sorted(unknown)} on node {name!r} in override"
                )
            for node_entry in selected:
                merged = {**node_entry.get("policy", {}), **policy_override}
                policy = NodePolicy(**merged)
                node_entry["policy"] = {
                    "retries": policy.retries,
                    "retry_delay_seconds": policy.retry_delay_seconds,
                    "timeout": policy.timeout,
                }

    if "options" in override:
        options_override = override["options"]
        if not isinstance(options_override, dict):
            raise ValueError("options override must be a dict")
        unknown = set(options_override) - set(_DOCUMENT_OPTION_FIELDS)
        if unknown:
            raise ValueError(f"unknown option key(s) {sorted(unknown)} in override")
        merged_options = {**_default_document_options(), **result.get("options", {})}
        merged_options.update(options_override)
        RunOptions(**merged_options)  # validate the merged values
        result["options"] = {name: merged_options[name] for name in _DOCUMENT_OPTION_FIELDS}

    return result


def _decode_value(value, type_name):
    """Decode a ``jsonable`` Path payload back to :class:`Path` when the type says so."""
    type_name = type_name if isinstance(type_name, str) else ""
    if isinstance(value, dict) and "path" in value and "sha256" in value:
        if type_name.endswith("Path") or not type_name:
            return Path(value["path"])
    return value


def _decode_parameters(entries) -> dict:
    """``{param_name: decoded value}`` for one parameter list."""
    values = {}
    for entry in entries:
        values[entry["name"]] = _decode_value(entry.get("value"), entry.get("type"))
    return values


def _document_key(entry: dict) -> str | NodeIdentity:
    """A document entry's overriding key: identity when it carries both fields."""
    if "path" in entry and "instance" in entry:
        return NodeIdentity(entry["name"], entry["path"], entry["instance"])
    return entry["name"]


def _node_registry(document: dict) -> dict:
    """The injection registry ``{key: {param: value}}`` (later occurrence wins).

    An entry carrying ``path`` and ``instance`` is keyed by its canonical
    identity, targeting one occurrence; a legacy entry without them is keyed
    by node name and reaches every occurrence of that name.
    """
    registry: dict = {}
    for entry in document.get("nodes", ()):
        reg = registry.setdefault(_document_key(entry), {})
        for p in entry.get("params", ()):
            reg[p["name"]] = _decode_value(p.get("value"), p.get("type"))
    return registry


def _node_policies(document: dict) -> dict:
    """The document's per-node policies, keyed by identity when present, else name."""
    policies = {}
    for entry in document.get("nodes", ()):
        policy = entry.get("policy")
        if not policy:
            continue
        unknown = set(policy) - set(_POLICY_FIELDS)
        if unknown:
            raise ValueError(
                f"unknown policy key(s) {sorted(unknown)} on node {entry['name']!r} in document"
            )
        policies[_document_key(entry)] = NodePolicy(**policy)
    return policies


def execute_plan(
    node: NodeFunction,
    document: dict,
    *,
    options: RunOptions | None = None,
    log=None,
) -> Run:
    """Execute a flow-plan/2 ``document`` against ``node`` and return its :class:`Run`.

    Decodes ``{"path": ..., "sha256": ...}`` values back to :class:`Path`,
    binds the root parameters (so a root parameter named ``options`` travels
    positionally), applies the document's per-node policies, and builds
    ``RunOptions`` from the document's ``options`` block.  ``options=``
    overlays its non-``UNSET`` fields; ``log=`` overrides the log directory.
    ``log=None`` means "do not override" (``RunOptions`` resolves ``"runs"``).
    """
    if not isinstance(node, NodeFunction):
        raise TypeError(f"execute_plan() expects a @node function, got {node!r}")
    if not isinstance(document, dict):
        raise TypeError(f"document must be a plan dict, got {document!r}")
    if document.get("schema") != PLAN_SCHEMA:
        raise ValueError(
            f"plan document schema must be {PLAN_SCHEMA!r}, got {document.get('schema')!r}"
        )
    if options is not None and not isinstance(options, RunOptions):
        raise TypeError(f"options must be RunOptions or None, got {options!r}")

    root_entries = document.get("parameters", ())
    root_values = _decode_parameters(root_entries)
    missing = [
        entry["name"]
        for entry in root_entries
        if entry.get("required") and root_values.get(entry["name"]) is None
    ]
    if missing:
        raise ValueError(f"missing required root parameter(s): {', '.join(missing)}")

    merged = _default_document_options()
    for name in _DOCUMENT_OPTION_FIELDS:
        if name in document.get("options", {}):
            merged[name] = document["options"][name]
    if options is not None:
        for field in (*_DOCUMENT_OPTION_FIELDS, "log"):
            value = getattr(options, field)
            if value is not UNSET:
                merged[field] = value
        for field in ("name", "pool", "node_defaults"):
            value = getattr(options, field)
            if value is not UNSET:
                merged[field] = value
    if log is not None:
        merged["log"] = log

    run_options = RunOptions(
        **merged,
        parameters=_node_registry(document),
        node_policies=_node_policies(document),
    )
    args, kwargs = bind_flow_inputs(node.fn, root_values)
    return execute_flow(node, *args, options=run_options, **kwargs)


def _node_key(entry: dict) -> tuple:
    """The stable node identity (name, path, instance) used by the diff."""
    return (entry["name"], tuple(entry["path"]), entry["instance"])


def _node_ref(entry: dict) -> dict:
    """A node identity as plain data, as it appears in diff records."""
    return {"name": entry["name"], "path": list(entry["path"]), "instance": entry["instance"]}


def diff_plans(a: dict, b: dict) -> dict:
    """Plain-data diff of two plan documents.

    ``changes`` lists records in deterministic order: root parameters, nodes
    (removed, added, then per-node policy and params), edges, then options.
    There is no root comparison: flow selection is external to the document.
    Identical documents give ``{"equal": True, "changes": []}``.
    """
    changes = []

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

    a_options = a.get("options", {})
    b_options = b.get("options", {})
    for name in _DOCUMENT_OPTION_FIELDS:
        if a_options.get(name) != b_options.get(name):
            changes.append(
                {
                    "kind": "option_changed",
                    "name": name,
                    "old": a_options.get(name),
                    "new": b_options.get(name),
                }
            )

    return {"equal": not changes, "changes": changes}
