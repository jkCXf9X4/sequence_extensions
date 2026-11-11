"""Run-log serialization policy: ``jsonable`` and strict JSON bytes.

The policy is deterministic and self-describing: paths carry a hash, sets are
ordered, non-finite floats become typed markers, colliding dict keys are
disambiguated, and cyclic/over-deep containers become markers instead of
exhausting the stack.  Reference mode additionally sorts nested mapping keys
before serializing.
"""

from __future__ import annotations

import hashlib
import json
import math
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from sequence_extensions.graph.graph_future import GraphFuture

#: Containers longer than this are replaced by a count in summary mode.
_SUMMARY_CONTAINER_LIMIT = 8

#: Recursion guard for ``jsonable``.  A deeper container is described by a
#: marker instead of exhausting the stack.
_MAX_JSON_DEPTH = 200


def _file_sha256(path: Path):
    """Hex sha256 of a regular file's contents, or None if it cannot be read.

    Only regular files are opened: a directory, FIFO, device, or socket logs
    as a path with no hash instead of blocking or raising.
    """
    try:
        mode = path.stat().st_mode
    except OSError:
        return None
    if not stat.S_ISREG(mode):
        return None
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _stable_set_items(value, *, summary: bool) -> list:
    """Deterministic order for a set's JSONable items.

    Homogeneous, orderable sets keep their natural sorted order.  Mixed or
    otherwise unorderable sets are ordered by type name and canonical JSON, so
    the same set serializes the same way in every process (hash seed
    independent).
    """
    try:
        return [jsonable(item, summary=summary) for item in sorted(value)]
    except TypeError:
        items = [jsonable(item, summary=summary) for item in value]
        items.sort(key=lambda item: (type(item).__name__, _canon(item)))
        return items


def _dict_key(key: Any, used: dict) -> str:
    """A printable, collision-free dict key for the log.

    String keys are kept as-is.  A later key whose string form is already used
    gets a deterministic ``#<type>#<n>`` suffix, so no entry is silently lost.
    """
    try:
        base = str(key)
    except Exception:
        base = f"<unprintable {type(key).__name__}>"
    if base not in used:
        return base
    tag = type(key).__name__
    candidate = f"{base}#{tag}"
    n = 2
    while candidate in used:
        candidate = f"{base}#{tag}#{n}"
        n += 1
    return candidate


def jsonable(value: Any, *, summary: bool = False, _seen=None, _depth: int = 0) -> Any:
    """Convert a value to a JSON-serializable structure.

    * primitives pass through unchanged; non-finite floats become
      ``{"float": "nan" | "inf" | "-inf"}`` so the log stays strict JSON
    * :class:`~pathlib.Path` -> ``{"path": ..., "sha256": ...}`` (hash only
      for a readable regular file)
    * ``datetime`` -> ISO 8601 string (as-is, no timezone guessing)
    * ``bytes`` -> ``{"len": n, "sha256": ...}``
    * ``set`` -> sorted list (items converted), deterministic for mixed types
    * :class:`~sequence_extensions.graph.GraphFuture` -> ``{"node": name,
      "done": bool}``
    * a self-referential container -> ``{"type": ..., "cycle": true}``
    * a container deeper than ``_MAX_JSON_DEPTH`` -> ``{"type": ...,
      "depth_exceeded": true}``
    * anything else JSON does not know -> ``str(value)`` (an unprintable
      object is described, never allowed to break the log)

    In ``summary`` mode, containers longer than
    ``_SUMMARY_CONTAINER_LIMIT`` items are replaced by
    ``{"type": ..., "len": ...}`` — item counts, not items.
    """
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return {"float": "nan"}
        if math.isinf(value):
            return {"float": "inf" if value > 0 else "-inf"}
        return value
    if isinstance(value, Path):
        return {"path": str(value), "sha256": _file_sha256(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return {"len": len(value), "sha256": hashlib.sha256(bytes(value)).hexdigest()}
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        if _depth >= _MAX_JSON_DEPTH:
            return {"type": type(value).__name__, "depth_exceeded": True}
        if _seen is None:
            _seen = set()
        marker = id(value)
        if marker in _seen:
            return {"type": type(value).__name__, "cycle": True}
        _seen.add(marker)
        try:
            if isinstance(value, (list, tuple)):
                if summary and len(value) > _SUMMARY_CONTAINER_LIMIT:
                    return {"type": type(value).__name__, "len": len(value)}
                return [
                    jsonable(item, summary=summary, _seen=_seen, _depth=_depth + 1)
                    for item in value
                ]
            if isinstance(value, (set, frozenset)):
                if summary and len(value) > _SUMMARY_CONTAINER_LIMIT:
                    return {"type": type(value).__name__, "len": len(value)}
                return _stable_set_items(value, summary=summary)
            if summary and len(value) > _SUMMARY_CONTAINER_LIMIT:
                return {"type": "dict", "len": len(value)}
            out = {}
            for key, item in value.items():
                out[_dict_key(key, out)] = jsonable(
                    item, summary=summary, _seen=_seen, _depth=_depth + 1
                )
            return out
        finally:
            _seen.discard(marker)
    if isinstance(value, GraphFuture):
        return {"node": value.name, "done": value.done()}
    try:
        return str(value)
    except Exception:
        return f"<unprintable {type(value).__name__}>"


def _sort_nested(value):
    """Recursively sort mapping keys; lists keep order.

    Used by reference mode so a result dict built from a set (or any other
    hash-order source) serializes with the same key order in every process.
    """
    if isinstance(value, dict):
        return {
            key: _sort_nested(item)
            for key, item in sorted(
                value.items(), key=lambda pair: (type(pair[0]).__name__, str(pair[0]))
            )
        }
    if isinstance(value, (list, tuple)):
        return [_sort_nested(item) for item in value]
    return value


def _json_bytes(line: dict) -> bytes:
    """Strict-JSON line bytes, UTF-8 even for lone surrogates.

    ``ensure_ascii=False`` keeps readable Unicode; ``backslashreplace`` turns
    an unencodable surrogate into the JSON escape ``\\udXXX`` instead of
    raising.  ``allow_nan=False`` enforces strict JSON.
    """
    text = json.dumps(line, default=str, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8", "backslashreplace")


def _canon(value) -> str:
    """Canonical string of a jsonable value (sort-keys JSON)."""
    return json.dumps(value, sort_keys=True, default=str)
