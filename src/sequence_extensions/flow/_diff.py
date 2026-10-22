"""Semantic comparison of run-log records (``RunLog.diff``)."""

from __future__ import annotations

import json

from sequence_extensions.flow._serialize import _canon


def _drop_future_done(value):
    """Recursively drop ``done`` from future-shaped dicts.

    ``jsonable`` gives a :class:`~sequence_extensions.graph.GraphFuture`
    the shape ``{"node": ..., "done": ...}``; the done-snapshot is a
    serialization-time accident, not an execution fact, so diff must
    not see it.
    """
    if isinstance(value, dict):
        out = {k: _drop_future_done(v) for k, v in value.items()}
        if "done" in out and "node" in out:
            out.pop("done")
        return out
    if isinstance(value, list):
        return [_drop_future_done(v) for v in value]
    return value


def _path_of(rec) -> tuple:
    """The node-name path of a record, as a hashable tuple."""
    path = rec.get("path")
    if isinstance(path, (list, tuple)) and path:
        return tuple(str(item) for item in path)
    node = rec.get("node")
    return (str(node),) if node is not None else ()


def _diff_identity(rec) -> tuple:
    """The identity of a record for comparison.

    Node records: (path, parent attempt, attempt, args, kwargs) — an
    attempt is what ran, where in the node tree, on which inputs, for the
    which time, so a fan-out (many attempts of one node) compares case by
    case and a retried composite's re-executed descendants stay distinct.
    Run records: their kind (one per run).  Never the record's position.
    """
    if rec.get("record") == "node":
        parent_attempt = rec.get("parent_attempt")
        parent_attempt = parent_attempt if isinstance(parent_attempt, int) else -1
        attempt = rec.get("attempt")
        attempt = attempt if isinstance(attempt, int) else -1
        return (
            "node",
            _path_of(rec),
            parent_attempt,
            attempt,
            _canon(rec.get("args")),
            _canon(rec.get("kwargs")),
        )
    return (str(rec.get("record")),)


def _identity_out(key) -> dict:
    """The jsonable, printable form of a diff identity.

    ``occurrence`` distinguishes repeated executions that share path, attempt,
    and inputs.  It is omitted for the first occurrence, so reports for
    ordinary (unique) records keep their historical shape.
    """
    if key[0] == "node":
        path = list(key[1])
        out = {
            "record": "node",
            "node": path[-1] if path else None,
            "path": path,
            "parent_attempt": key[2],
            "attempt": key[3],
            "args": json.loads(key[4]),
            "kwargs": json.loads(key[5]),
        }
        occurrence = key[6] if len(key) > 6 else 0
    else:
        out = {"record": key[0]}
        occurrence = key[1] if len(key) > 1 else 0
    if occurrence:
        out["occurrence"] = occurrence
    return out


def _diff_side(records, exclude) -> dict:
    """One side of a comparison: ``{identity: normalized record}``.

    Excluded fields are dropped and future ``done`` snapshots ignored
    before the identity is taken, so both come from the same
    normalization.  Repeated executions with the same identity are kept as a
    multiset: each record gets an ``occurrence`` index, assigned after a
    deterministic sort of the group.  A changed fan-out count therefore shows
    up as extra/missing occurrences instead of being collapsed.
    """
    groups: dict[tuple, list] = {}
    for rec in records:
        normalized = _drop_future_done({f: v for f, v in rec.items() if f not in exclude})
        groups.setdefault(_diff_identity(normalized), []).append(normalized)
    side = {}
    for base, group in groups.items():
        group.sort(key=_canon)
        for occurrence, record in enumerate(group):
            side[base + (occurrence,)] = record
    return side


def _diff_records(left_records, right_records, exclude) -> dict:
    """The flat comparison of two record lists."""
    left_side = _diff_side(left_records, exclude)
    right_side = _diff_side(right_records, exclude)
    only_left = sorted(left_side.keys() - right_side.keys())
    only_right = sorted(right_side.keys() - left_side.keys())
    changed = []
    for key in sorted(left_side.keys() & right_side.keys()):
        lrec, rrec = left_side[key], right_side[key]
        differing = {}
        for field in sorted(set(lrec) | set(rrec)):
            if lrec.get(field) != rrec.get(field):
                differing[field] = {
                    "left": lrec.get(field),
                    "right": rrec.get(field),
                }
        if differing:
            changed.append({**_identity_out(key), "fields": differing})
    return {
        "equal": not (only_left or only_right or changed),
        "only_left": [_identity_out(k) for k in only_left],
        "only_right": [_identity_out(k) for k in only_right],
        "changed": changed,
    }
