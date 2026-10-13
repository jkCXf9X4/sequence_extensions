"""JSON-lines audit log — the executed truth of a flow run.

One file per run, one JSON object per line, written while things happen
(attempt granularity for tasks).  The log is the product: diffable,
greppable, and language-neutral.  Large payloads are never inlined; by
convention a task returns a :class:`~pathlib.Path` for anything bulky, and
paths are logged as path plus content hash.

Record kinds (all get ``seq`` and ``schema`` added on write):

* ``run_start`` — written by ``@flow`` at entry (identity, args).
* ``task`` — one record per task attempt: ``status`` is ``ok`` (with
  ``result``), ``error`` (with ``error``), ``timeout`` (with ``error``),
  or ``skipped`` (``attempt`` 0 — the node never executed because a
  dependency failed or the flow failed and cancelled it).
* ``run_end`` — written at exit (``status`` ok/error, result or error).
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from sequence_extensions.graph.graph_future import GraphFuture

#: Bumped whenever the record format changes in a way readers must know about.
SCHEMA_VERSION = 1

#: Containers longer than this are replaced by a count in summary mode.
_SUMMARY_CONTAINER_LIMIT = 8


def _file_sha256(path: Path):
    """Hex sha256 of a file's contents, or None if it cannot be read."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def jsonable(value: Any, *, summary: bool = False) -> Any:
    """Convert a value to a JSON-serializable structure.

    * primitives pass through unchanged
    * :class:`~pathlib.Path` -> ``{"path": ..., "sha256": ...}`` (hash only
      when the file exists and is readable)
    * ``datetime`` -> ISO 8601 string (as-is, no timezone guessing)
    * ``bytes`` -> ``{"len": n, "sha256": ...}``
    * ``set`` -> sorted list (items converted)
    * :class:`~sequence_extensions.graph.GraphFuture` -> ``{"node": name,
      "done": bool}``
    * anything else JSON does not know -> ``str(value)``

    In ``summary`` mode, containers longer than
    ``_SUMMARY_CONTAINER_LIMIT`` items are replaced by
    ``{"type": ..., "len": ...}`` — item counts, not items.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return {"path": str(value), "sha256": _file_sha256(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return {"len": len(value), "sha256": hashlib.sha256(bytes(value)).hexdigest()}
    if isinstance(value, (list, tuple)):
        if summary and len(value) > _SUMMARY_CONTAINER_LIMIT:
            return {"type": type(value).__name__, "len": len(value)}
        return [jsonable(item, summary=summary) for item in value]
    if isinstance(value, (set, frozenset)):
        if summary and len(value) > _SUMMARY_CONTAINER_LIMIT:
            return {"type": type(value).__name__, "len": len(value)}
        try:
            items = sorted(value)
        except TypeError:
            items = list(value)
        return [jsonable(item, summary=summary) for item in items]
    if isinstance(value, dict):
        if summary and len(value) > _SUMMARY_CONTAINER_LIMIT:
            return {"type": "dict", "len": len(value)}
        return {str(key): jsonable(item, summary=summary) for key, item in value.items()}
    if isinstance(value, GraphFuture):
        return {"node": value.name, "done": value.done()}
    return str(value)


class RunLog:
    """Thread-safe JSON-lines writer; one file per run.

    ``write`` is safe from any thread (tasks log their attempts from pool
    workers).  ``seq`` (per-run monotonic record number) and ``schema`` are
    added to every record on write.  Writing to a closed (or never opened)
    log raises — the flow layer closes the log only after every record is
    in, so a late write is a bug, not a dropped line.
    """

    def __init__(self, path, *, summary: bool = False):
        self.path = Path(path)
        self.summary = bool(summary)
        self._lock = threading.Lock()
        self._seq = 0
        self._fh = None

    # ------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------ #
    def open(self) -> None:
        """Create the parent directory and open the file for writing."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", encoding="utf-8")

    def close(self) -> None:
        """Close the file (idempotent)."""
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    # ------------------------------------------------------------ #
    # Writing / reading
    # ------------------------------------------------------------ #
    def write(self, record: dict) -> None:
        """Append one record as a JSON line (thread-safe, flushed)."""
        if self._fh is None:
            raise RuntimeError(f"RunLog.write on a closed log: {self.path}")
        with self._lock:
            self._seq += 1
            line = {"seq": self._seq, "schema": SCHEMA_VERSION, **record}
            self._fh.write(json.dumps(line, default=str, ensure_ascii=False) + "\n")
            self._fh.flush()

    @staticmethod
    def records(path) -> list:
        """Read a run log back as a list of dicts, in file order."""
        out = []
        with open(Path(path), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out
